import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type WaveSurfer from 'wavesurfer.js'
import { api, type LineEdit } from '../api'
import { Captions } from '../captions/Captions'
import {
  LOOP_PAUSES_MS, MIN_WORD_MS, PLAY_SPEEDS, clipRange, jumpTarget,
  lineIndexAt, loopSpan, repairTiming, sectionAt, stepSpeed, stripNiqqud, type LoopSpan,
} from '../captions/timing'
import { useHoldForKeys } from '../holdKeys'
import { Icon } from '../icons'
import { useNumberPref, usePref } from '../prefs'
import { debug } from '../debug'
import { EchoOut } from '../player/echoOut'
import { Player, type PlayerMode } from '../player/Player'
import { LINE_ID, RATING_LABELS, lineToRate, nextRating, usePracticeLog } from '../practice'
import type { Peaks, Section, SectionKind, Song, Tier, Track } from '../types'
import { FlagsPanel, TIMING_FLAGS } from './FlagsPanel'
import { BreakdownPanel } from './BreakdownPanel'
import { LineList } from './LineList'
import { Review } from './Review'
import { ShortcutMap } from './ShortcutMap'
import { SuggestionsBox } from './SuggestionsBox'
import { ClipsPanel, DrillsPanel, SectionsPanel } from './StructurePanels'
import { SECTION_KINDS, makeClip, makeSection, nextId, resizeSection, sectionRange, type WordRange } from './structure'
import { Timeline } from './Timeline'
import { WordInspector, type Edge } from './WordInspector'

const SAVE_DELAY_MS = 700
const TAP_LEAD_MS = 1500
const LINE_BAR_MS = 20000 // how long the split / join bar (with its Undo) stays

/** The lines a line edit changes, as they are before it (an undo gives them back their English). */
function linesBefore(s: Song, body: LineEdit & { action: 'split' | 'join' | 'move' }) {
  const i = body.action === 'join' ? s.lines.findIndex((l) => l.id === body.lineId)
    : s.lines.findIndex((l) => l.words.some((w) => w.id === body.wordId))
  if (body.action === 'split') return [s.lines[i]]
  if (body.action === 'move' && body.to === 'prev') return [s.lines[i - 1], s.lines[i]]
  return [s.lines[i], s.lines[i + 1]]
}
const TAP_MAX_GAP_MS = 8000 // no tap for this long while playing ends tap mode
const TAP_PUSH_LIMIT_MS = 1000 // taps may nudge the neighbouring lines' words by at most this much

/** Apply tap times to a line's words, then make the whole song monotonic again. Returns how far (ms) the
 *  repair had to move any word outside the line: large means the taps ran over later lines. */
function applyTaps(s: Song, lineId: string, taps: number[]): number {
  const line = s.lines.find((l) => l.id === lineId)!
  const tapped = new Set<string>()
  line.words.forEach((w, k) => {
    if (k >= taps.length) return
    const dur = w.endMs - w.startMs
    w.startMs = Math.round(taps[k])
    w.endMs = Math.round(k + 1 < taps.length ? taps[k + 1] : taps[k] + dur)
    w.flags = without(w.flags, TIMING_FLAGS)
    tapped.add(w.id)
  })
  const all = allWords(s)
  const before = all.map((w) => w.startMs)
  const inLine = new Set(line.words.map((w) => w.id))
  let pushed = 0
  for (const i of repairTiming(all, s.song.durationMs)) {
    if (!inLine.has(all[i].id)) pushed = Math.max(pushed, Math.abs(all[i].startMs - before[i]))
    if (!tapped.has(all[i].id) && !all[i].flags.includes('timing-adjusted')) all[i].flags.push('timing-adjusted')
  }
  return pushed
}

type SaveState = 'saved' | 'pending' | 'saving' | 'error'
const without = (flags: string[], remove: string[]) => flags.filter((f) => !remove.includes(f))
const allWords = (s: Song) => s.lines.flatMap((l) => l.words)
const fmt = (ms: number) => `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(2).padStart(5, '0')}`

type Tab = 'sections' | 'words' | 'lesson'

/** The letters that identify a word (what the server checks): no vowel points, punctuation or letter case. */
const letterKey = (s: string) => [...stripNiqqud(s)].filter((ch) => /[\p{L}\p{N}]/u.test(ch)).join('').toLowerCase()

export function Editor({ id }: { id: string }) {
  const [song, setSong] = useState<Song | null>(null)
  const [peaks, setPeaks] = useState<Peaks | null>(null) // the track playing
  const [vocalPeaks, setVocalPeaks] = useState<Peaks | null>(null) // the singing: sizes the word beads
  const [loadError, setLoadError] = useState<string | null>(null)
  const [timeMs, setTimeMs] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [track, setTrackState] = useState<Track>('original')
  const [showNiqqud, setShowNiqqud] = usePref('niqqud', false)
  const [speed, setSpeed] = useState(1)
  const [loop, setLoop] = useState<LoopSpan | null>(null) // a section or a line
  const [loopPauseMs, setLoopPauseMs] = useNumberPref('loopPauseMs', 0)
  const [loopFade, setLoopFade] = usePref('loopFade', true)
  const [jumpSec, setJumpSec] = useNumberPref('jumpSec', 5) // J / L: seconds back / forward; 0 = by line
  const loopOpts = useRef({ pauseMs: loopPauseMs, fade: loopFade })
  loopOpts.current = { pauseMs: loopPauseMs, fade: loopFade }
  const gapTimer = useRef<number | undefined>(undefined) // the pause between loop passes
  const echo = useRef<EchoOut | null>(null) // the fade between loop passes
  const [zoom, setZoom] = useState(0)
  const [breakdownLineId, setBreakdownLineId] = useState<string | null>(null)
  const lineAnchor = useRef<string | null>(null) // first line of a Shift-click line selection
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [edge, setEdge] = useState<Edge>('both')
  // The word panel opens only when asked (double-click a word, E, or a pick in the Flags list): a plain click
  // just selects, so the line list keeps its room. Arrow-key nudges need the panel open, so they're never unseen.
  const [editing, setEditing] = useState(false)
  const [tap, setTap] = useState<{ lineId: string; taps: number[]; fromMs: number } | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('saved')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [range, setRange] = useState<WordRange | null>(null)
  const [sectionKind, setSectionKind] = useState<SectionKind>('chorus')
  const [tab, setTab] = useState<Tab>('sections')
  const [player, setPlayer] = useState<PlayerMode | null>(null)
  const [reviewing, setReviewing] = useState(false)
  const [popover, setPopover] = useState<'settings' | 'keys' | null>(null) // the bar's settings and keyboard popovers
  const popoverRef = useRef<HTMLSpanElement>(null)
  const [popoverLeft, setPopoverLeft] = useState(false) // open rightwards when the buttons sit near the left edge
  const togglePopover = (p: 'settings' | 'keys') => {
    setPopoverLeft((popoverRef.current?.getBoundingClientRect().right ?? 1000) < 420)
    setPopover((cur) => (cur === p ? null : p))
  }
  // A popover closes on a click anywhere else.
  useEffect(() => {
    if (!popover) return
    const away = (e: MouseEvent) => { if (!popoverRef.current?.contains(e.target as Node)) setPopover(null) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [popover])

  const ws = useRef<WaveSurfer | null>(null)
  const bound = useRef(new WeakSet<WaveSurfer>())
  const songRef = useRef(song)
  songRef.current = song
  const loopRef = useRef(loop)
  loopRef.current = loop
  const speedRef = useRef(speed)
  speedRef.current = speed
  const version = useRef(0)
  const savedVersion = useRef(0)
  const saving = useRef(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    Promise.all([api.song(id), api.peaks(id, 'vocals'), api.peaks(id, 'original')]).then(([s, v, o]) => {
      setSong(s); setVocalPeaks(v); setPeaks(o)
      // Open on what needs doing: words to check first, otherwise the song's sections.
      if (s.lines.some((l) => l.words.some((w) => w.flags.length))) setTab('words')
    }, (e: Error) => setLoadError(e.message))
    api.practice(id).then((p) => setLineLoops(p.lineLoops), () => {})
    api.learning(id).then((l) => { setRatings(l.ratings); setNewWordIds(new Set(l.newWordIds)) }, () => {})
  }, [id])

  // Self-ratings per line (keys 1 / 2 / 3, or the ✓ button on a line) and the words new to you.
  const [ratings, setRatings] = useState<Record<string, number>>({})
  const [newWordIds, setNewWordIds] = useState<Set<string>>(() => new Set())
  const [markNew, setMarkNew] = usePref('markNewWords', false)
  const rate = (lineId: string, pressed: number) => {
    const next = nextRating(ratings[lineId], pressed)
    setRatings((m) => { const c = { ...m }; if (next === null) delete c[lineId]; else c[lineId] = next; return c })
    const n = songRef.current!.lines.findIndex((l) => l.id === lineId) + 1
    setNotice(`Line ${n}: ${next === null ? 'rating cleared' : RATING_LABELS[next]}`)
    api.rateLine(id, lineId, next).catch((e: Error) => {
      setNotice(`Rating not saved: ${e.message}`)
      api.learning(id).then((l) => setRatings(l.ratings), () => {})
    })
  }

  // Practice log: playing time here, and passes of each line loop (shown on the line list as ⟳ n).
  const [lineLoops, setLineLoops] = useState<Record<string, number>>({})
  const countLoop = usePracticeLog(id, 'studio', playing && !player)

  // --- autosave ------------------------------------------------------------------
  const save = useCallback(async () => {
    const v = version.current, s = songRef.current
    if (saving.current || !s || v === savedVersion.current) return
    saving.current = true
    setSaveState('saving')
    try {
      await api.save(id, s)
      savedVersion.current = v
      setSaveError(null)
      setSaveState(version.current === v ? 'saved' : 'pending')
    } catch (e) {
      setSaveState('error')
      setSaveError((e as Error).message)
    } finally {
      saving.current = false
      if (version.current !== v) schedule()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])
  const schedule = () => { window.clearTimeout(timer.current); timer.current = window.setTimeout(save, SAVE_DELAY_MS) }

  /** Apply a change to a copy of the song, then autosave. */
  const edit = (mutate: (s: Song) => void) => {
    setSong((prev) => { if (!prev) return prev; const next = structuredClone(prev); mutate(next); return next })
    version.current++
    setSaveState('pending')
    schedule()
  }

  /** Wait until every edit made so far is on disk. */
  const flushSave = async () => {
    window.clearTimeout(timer.current)
    for (let i = 0; i < 100 && (saving.current || version.current !== savedVersion.current); i++) {
      if (saving.current) await new Promise((r) => setTimeout(r, 100))
      else await save()
    }
  }

  /** Add or remove a lyric word. Done on the server (renumbers ids, moves clips, backs up); the editor then
   *  takes the saved song as its new state. Throws with the server's message on a refused edit. */
  const changeWords = async (body: Parameters<typeof api.editWords>[1]) => {
    await flushSave()
    const r = await api.editWords(id, body)
    version.current++
    savedVersion.current = version.current
    setSong(r.song)
    setSaveState('saved')
    setRange(null)
    setSelectedId(r.wordId)
    setNotice(body.action === 'insert' ? `Word added (${r.wordId}): check its timing` : 'Word deleted')
  }

  // --- where lines break: split, join, move an edge word ------------------------------------------
  // Done on the server, which renumbers ids and moves sections, clips, ratings and loop counts with them. The
  // changed lines are then translated again (read-only call; applied here as a normal edit, and only if nothing
  // else changed the lines meanwhile). The bar keeps an Undo: the opposite edit, with the old English.
  const [lineBar, setLineBar] = useState<{ text: string; note: string; undo: LineEdit | null } | null>(null)
  const lineSeq = useRef(0)
  useEffect(() => {
    if (!lineBar) return
    const t = window.setTimeout(() => setLineBar(null), LINE_BAR_MS)
    return () => window.clearTimeout(t)
  }, [lineBar])
  const changeLines = async (body: LineEdit, text: string) => {
    await flushSave()
    const before = songRef.current!
    const r = await api.editLines(id, body)
    const seq = ++lineSeq.current
    version.current++
    savedVersion.current = version.current
    setSong(r.song)
    setSaveState('saved')
    setRange(null)
    setSelectedId(r.wordId)
    lineAnchor.current = null
    setBreakdownLineId(null)
    if (loopRef.current && LINE_ID.test(loopRef.current.id)) setLoop(null) // its line may have a new id
    api.learning(id).then((l) => { setRatings(l.ratings); setNewWordIds(new Set(l.newWordIds)) }, () => {})
    api.practice(id).then((p) => setLineLoops(p.lineLoops), () => {})
    if (body.english || body.action === 'restore') { setLineBar({ text, note: '', undo: null }); return } // an undo: its English is restored
    if (body.action === 'delete') { setLineBar({ text, note: '', undo: r.undo }); return } // no line changed its words: nothing to translate
    const english = Object.fromEntries(linesBefore(before, body).map((l) => [l.id, l.english]))
    setLineBar({ text, note: 'translating the changed lines…', undo: { ...r.undo, english } })
    const sent = Object.fromEntries(r.song.lines.filter((l) => r.lineIds.includes(l.id)).map((l) => [l.id, l.english]))
    api.translateLines(id, r.lineIds).then((t) => {
      if (seq !== lineSeq.current) return // the lines changed again: these ids mean other lines now
      edit((s) => {
        for (const l of s.lines) if (t.english[l.id] && l.english === sent[l.id]) l.english = t.english[l.id]
      })
      setLineBar((b) => (b && seq === lineSeq.current ? { ...b, note: 'English updated' } : b))
    }, (e: Error) => {
      if (seq === lineSeq.current) setLineBar((b) => (b ? { ...b, note: `English not updated (${e.message}): check these lines` } : b))
    })
  }
  const lineOp = (body: LineEdit, text: string) => { changeLines(body, text).catch((e: Error) => setNotice(e.message)) }

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (version.current !== savedVersion.current) e.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  // --- the one clock: the audio element -----------------------------------------
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      const w = ws.current
      if (w) setTimeMs(w.getCurrentTime() * 1000)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    // The loop point runs on a timer, not the screen refresh: browsers stop that in a hidden tab.
    const check = window.setInterval(() => {
      const w = ws.current, l = loopRef.current, fader = echo.current
      if (!w || !l || fader?.busy) return
      const t = w.getCurrentTime() * 1000, fade = loopOpts.current.fade && fader
      if (t < (fade ? l.lastMs : l.endMs)) return
      countLoop(l.id)
      if (LINE_ID.test(l.id)) setLineLoops((m) => ({ ...m, [l.id]: (m[l.id] ?? 0) + 1 }))
      if (fade) { fader.run(l.firstMs, loopOpts.current.pauseMs, speedRef.current); return }
      w.setTime(l.startMs / 1000) // next pass, after the pause if one is set
      if (loopOpts.current.pauseMs > 0) {
        w.pause()
        gapTimer.current = window.setTimeout(() => { if (loopRef.current === l) w.play() }, loopOpts.current.pauseMs)
      }
    }, 10)
    return () => { cancelAnimationFrame(raf); window.clearInterval(check) }
  }, [playing])

  useEffect(() => () => echo.current?.dispose(), [])

  const onReady = useCallback((w: WaveSurfer) => {
    ws.current = w
    const media = w.getMediaElement()
    if (!echo.current && media) echo.current = new EchoOut(media)
    debug.audioTimeMs = () => (ws.current?.getCurrentTime() ?? 0) * 1000
    if (bound.current.has(w)) return
    bound.current.add(w)
    w.on('play', () => { window.clearTimeout(gapTimer.current); applySpeed(); setPlaying(true) }) // a track switch reloads the media, so re-apply
    w.on('pause', () => setPlaying(false))
    w.on('timeupdate', (t) => setTimeMs(t * 1000))
  }, [])

  /** Slowed playback keeps its pitch. */
  function applySpeed() {
    const m = ws.current?.getMediaElement() as (HTMLMediaElement & { preservesPitch: boolean }) | undefined
    if (!m) return
    m.preservesPitch = true
    m.defaultPlaybackRate = speedRef.current
    m.playbackRate = speedRef.current
  }
  useEffect(applySpeed, [speed])

  /** The waveform shows the track you hear, so its peaks arrive before the switch. */
  const setTrack = (t: Track) => {
    if (t === track) return
    api.peaks(id, t).then((p) => { setPeaks(p); setTrackState(t) }, (e: Error) => setNotice(`Couldn't switch track: ${e.message}`))
  }

  const words = useMemo(() => (song ? allWords(song) : []), [song])
  const activeWordId = useMemo(() => words.find((w) => w.startMs <= timeMs && timeMs < w.endMs)?.id ?? null, [words, timeMs])
  const selected = words.find((w) => w.id === selectedId) ?? null

  // --- timing edits --------------------------------------------------------------
  /** Clamp to neighbours and the 40 ms minimum; always re-renders so a rejected drag snaps back. */
  const setTimes = (wordId: string, start: number, end: number, side: Edge) => {
    edit((s) => {
      const ws_ = allWords(s), i = ws_.findIndex((w) => w.id === wordId), w = ws_[i]
      const prevEnd = i > 0 ? ws_[i - 1].endMs : 0
      const nextStart = i < ws_.length - 1 ? ws_[i + 1].startMs : s.song.durationMs
      let a = Math.max(prevEnd, Math.round(start)), b = Math.min(nextStart, Math.round(end))
      if (b - a < MIN_WORD_MS) { if (side === 'start') a = b - MIN_WORD_MS; else b = a + MIN_WORD_MS }
      if (a < prevEnd || b > nextStart) return
      if (a !== w.startMs || b !== w.endMs) { w.startMs = a; w.endMs = b; w.flags = without(w.flags, TIMING_FLAGS) }
    })
  }

  const nudge = (delta: number) => {
    if (!selected) return
    const i = words.indexOf(selected)
    const prevEnd = i > 0 ? words[i - 1].endMs : 0
    const nextStart = i < words.length - 1 ? words[i + 1].startMs : song!.song.durationMs
    let { startMs: a, endMs: b } = selected
    if (edge === 'both') {
      const d = Math.max(prevEnd - a, Math.min(nextStart - b, delta))
      a += d; b += d
    } else if (edge === 'start') a = Math.max(prevEnd, Math.min(b - MIN_WORD_MS, a + delta))
    else b = Math.min(nextStart, Math.max(a + MIN_WORD_MS, b + delta))
    setTimes(selected.id, a, b, edge)
  }

  // --- spelling ------------------------------------------------------------------------
  /** Change how a word is written (vowel points, punctuation, capitals), keeping its letters. */
  const applySpelling = async (wordId: string, text: string) => {
    const word = allWords(songRef.current!).find((w) => w.id === wordId)!
    const next = text.trim().normalize('NFC')
    if (!next || /\s/.test(next)) throw new Error('One word, no spaces')
    if (letterKey(next) !== letterKey(word.plain)) throw new Error('Keep the same letters: to change them, add the right word and delete this one')
    edit((s) => { allWords(s).find((w) => w.id === wordId)!.plain = next })
  }

  // --- selection / playback ----------------------------------------------------------
  /** Click selects a word; Shift-click extends a range from the selected word. */
  const selectWord = (wordId: string, shift = false) => {
    if (shift && selectedId && selectedId !== wordId) {
      const a = words.findIndex((x) => x.id === selectedId), b = words.findIndex((x) => x.id === wordId)
      setRange({ fromWord: words[Math.min(a, b)].id, toWord: words[Math.max(a, b)].id })
      return
    }
    const w = words.find((x) => x.id === wordId)
    setRange(null)
    setSelectedId(wordId)
    setEdge('both')
    if (w && ws.current && !ws.current.isPlaying()) {
      ws.current.setTime(w.startMs / 1000)
      ws.current.setScrollTime(Math.max(0, w.startMs / 1000 - 1))
    }
  }

  /** Drag on the waveform: every word overlapping the dragged span. */
  const rangeFromDrag = (startMs: number, endMs: number) => {
    const hit = words.filter((w) => w.endMs > startMs && w.startMs < endMs)
    if (!hit.length) return
    setSelectedId(hit[0].id)
    setRange({ fromWord: hit[0].id, toWord: hit.at(-1)!.id })
  }

  // The selection actions (section, clip) work on a range only: Shift-click, a line number, or a drag on the waveform
  // (drag over a single word for a one-word clip). A plain word click shows no bar.
  const activeRange: WordRange | null = range
  const editWord = (wordId: string) => { selectWord(wordId); setEditing(true) }
  const rangeWords = useMemo(() => {
    if (!activeRange) return []
    const a = words.findIndex((w) => w.id === activeRange.fromWord), b = words.findIndex((w) => w.id === activeRange.toWord)
    return words.slice(a, b + 1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [words, activeRange?.fromWord, activeRange?.toWord])
  const rangeIds = useMemo(() => new Set(range ? rangeWords.map((w) => w.id) : []), [range, rangeWords])

  const makeSectionFromRange = () => {
    if (!activeRange) return
    edit((s) => { makeSection(s, activeRange, sectionKind) })
    setTab('sections')
    setNotice(`${sectionKind} section made`)
  }
  const makeClipFromRange = () => {
    if (!activeRange || !song) return
    const id = nextId('C', song.clips.map((c) => c.id))
    edit((s) => { makeClip(s, activeRange) })
    setTab('lesson')
    setNotice(`Clip ${id} made (${rangeWords.length} word${rangeWords.length > 1 ? 's' : ''})`)
  }
  // --- section playback ---------------------------------------------------------------
  const playSection = (s: Section) => {
    const r = sectionRange(song!, s)
    setLoop(null)
    ws.current?.play(r.startMs / 1000, r.endMs / 1000)
  }
  /** Loop a stretch until turned off (same id again = off, keep playing). Lines and sections share this. */
  const toggleLoop = (id: string, startMs: number, endMs: number) => {
    if (loop?.id === id) { setLoop(null); return }
    const span = loopSpan(id, startMs, endMs, song!.song.durationMs)
    setLoop(span)
    if (loopFade) echo.current?.prepare() // here, because browsers only allow this from a click or key press
    ws.current?.pause() // clears a "stop at" left by a one-time play
    ws.current?.play(span.startMs / 1000)
  }
  const loopSection = (s: Section) => { const r = sectionRange(song!, s); toggleLoop(s.id, r.startMs, r.endMs) }
  const loopLine = (lineId: string) => {
    const l = song!.lines.find((x) => x.id === lineId)!
    toggleLoop(lineId, l.words[0].startMs, l.words.at(-1)!.endMs)
  }
  // Loop off: full volume again, and no pending pass.
  useEffect(() => {
    if (loop) return
    window.clearTimeout(gapTimer.current)
    echo.current?.cancel()
  }, [loop])
  // Turning the fade off mid-loop must not leave a transition half done.
  useEffect(() => { if (!loopFade) echo.current?.cancel(); else if (loopRef.current) echo.current?.prepare() }, [loopFade])
  const clipSection = (s: Section) => {
    const r = sectionRange(song!, s)
    const id = nextId('C', song!.clips.map((c) => c.id))
    edit((x) => { makeClip(x, r).name = s.label })
    setNotice(`Clip ${id} made from ${s.label}`)
  }

  const openPlayer = (mode: PlayerMode) => {
    ws.current?.pause()
    setPlayer(mode)
  }

  // --- line list: line-set selection, play a line, breakdown -------------------------------
  const lineOfWord = (wordId: string) => song!.lines.find((l) => l.words.some((w) => w.id === wordId))!
  /** Click: that line. Shift-click: every line from the first clicked one to this one. */
  const selectLine = (lineId: string, shift: boolean) => {
    const lines = song!.lines, idx = (id: string) => lines.findIndex((l) => l.id === id)
    const anchor = shift && lineAnchor.current ? lineAnchor.current : lineId
    if (!shift) lineAnchor.current = lineId
    const [a, b] = [idx(anchor), idx(lineId)].sort((x, y) => x - y)
    setRange({ fromWord: lines[a].words[0].id, toWord: lines[b].words.at(-1)!.id })
    setSelectedId(null)
    if (ws.current && !ws.current.isPlaying()) ws.current.setTime(lines[a].words[0].startMs / 1000)
  }
  const playLine = (lineId: string) => {
    const l = song!.lines.find((x) => x.id === lineId)!
    setLoop(null)
    ws.current?.play(l.words[0].startMs / 1000, l.words.at(-1)!.endMs / 1000)
  }
  const openBreakdown = (lineId: string) => { setBreakdownLineId(lineId); setTab('words') }
  /** A word click also follows in the breakdown when one is open. */
  const clickWord = (wordId: string, shift: boolean) => {
    selectWord(wordId, shift)
    if (!shift && tab === 'words' && breakdownLineId) setBreakdownLineId(lineOfWord(wordId).id)
  }

  // --- tap-to-time ------------------------------------------------------------------
  const tapLine = () => {
    if (!song || !ws.current) return
    const line = selected ? song.lines.find((l) => l.words.some((w) => w.id === selected.id))! : song.lines[lineIndexAt(song.lines, timeMs)]
    const fromMs = Math.max(0, line.words[0].startMs - TAP_LEAD_MS)
    setTap({ lineId: line.id, taps: [], fromMs })
    ws.current.setTime(fromMs / 1000)
    ws.current.play()
  }

  const finishTap = (t: { lineId: string; taps: number[] }, why = '') => {
    ws.current?.pause()
    setTap(null)
    if (!t.taps.length) { if (why) setNotice(`Tap mode ended (${why}); nothing changed`); return }
    // Try it on a copy first: taps that would shove other lines' words around (a late Space press) are refused,
    // instead of crushing every later word to the minimum length.
    const pushed = applyTaps(structuredClone(song!), t.lineId, t.taps)
    if (pushed > TAP_PUSH_LIMIT_MS) {
      setNotice(`Taps not applied: they would move later lines by ${(pushed / 1000).toFixed(1)} s. Press T to try again.`)
      return
    }
    edit((s) => { applyTaps(s, t.lineId, t.taps) })
    const n = Math.min(t.taps.length, song!.lines.find((l) => l.id === t.lineId)!.words.length)
    setNotice(`Tap-timed ${n} word(s)${why ? ` (tap mode ended: ${why})` : ''}`)
  }

  // A tap session ends by itself when the taps stop: no stale Space press minutes later can land as a word start.
  useEffect(() => {
    if (!tap || !playing) return
    if (timeMs - (tap.taps.at(-1) ?? tap.fromMs) > TAP_MAX_GAP_MS) finishTap(tap, `no tap for ${TAP_MAX_GAP_MS / 1000} s`)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeMs])

  useEffect(() => {
    if (!tap || !song) return
    const n = song.lines.find((l) => l.id === tap.lineId)!.words.length
    if (tap.taps.length >= n + 1) finishTap(tap) // last tap = end of the last word
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tap])

  // --- keyboard ---------------------------------------------------------------------
  // After a menu, checkbox or slider is changed, hand focus back to the page so the playback keys keep working.
  useEffect(() => {
    const release = (e: Event) => {
      const el = e.target as HTMLElement
      const choice = el.tagName === 'SELECT' || (el.tagName === 'INPUT' && ['checkbox', 'radio', 'range'].includes((el as HTMLInputElement).type))
      if (choice) window.setTimeout(() => el.blur(), 0)
    }
    document.addEventListener('change', release)
    return () => document.removeEventListener('change', release)
  }, [])

  /** J back · K play/pause · L forward (by jumpSec seconds, or by line) · I loop this line · O loop this section
   *  · U slower · N faster. All act at the playhead. */
  const lineKey = (key: string) => {
    const w = ws.current
    if (!w || !song) return
    const lines = song.lines
    const t = w.getCurrentTime() * 1000
    const i = lineIndexAt(lines, t)
    const seek = (ms: number) => { echo.current?.cancel(); w.setTime(ms / 1000); setTimeMs(ms) }
    if (key === 'u' || key === 'n') {
      const next = stepSpeed(speed, key === 'n')
      setSpeed(next)
      setNotice(`Speed ${Math.round(next * 100)}%`)
    } else if (key === 'k') w.playPause()
    else if (key === 'j' || key === 'l') seek(jumpTarget(lines, t, key === 'l', jumpSec, song.song.durationMs))
    else if (key === 'i' || key === 'o') {
      // Same key again stops it. (Asking the playhead would misfire: a loop starts a little before its line.)
      const loopIsSection = !!loop && song.sections.some((s) => s.id === loop.id)
      if (loop && loopIsSection === (key === 'o')) { setLoop(null); return }
    }
    if (key === 'i') loopLine(lines[i].id)
    else if (key === 'o') {
      const s = sectionAt(song, i)
      if (s) loopSection(s)
      else setNotice('No section here to loop: make one from the line list or the Sections tab')
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (player || reviewing) return // the player and review handle their own keys
      const el = e.target as HTMLElement
      // Shortcuts stand aside only while you're typing text. A focused menu, checkbox or slider doesn't block them.
      const textInput = el.tagName === 'INPUT' && ['text', 'number', 'search', 'url', 'email', ''].includes((el as HTMLInputElement).type)
      const typing = textInput || el.tagName === 'TEXTAREA' || el.isContentEditable
      if (e.key === 'Escape') {
        if (popover) setPopover(null)
        else if (tap) finishTap(tap)
        else if (range) setRange(null)
        else if (editing) setEditing(false)
        else setSelectedId(null)
        return
      }
      if (typing) return
      // so Space doesn't also click the focused button, and a focused menu doesn't jump to the option for K, N...
      if (['BUTTON', 'SELECT', 'INPUT'].includes(el.tagName)) el.blur()
      if (e.code === 'Space') {
        e.preventDefault()
        if (!tap) ws.current?.playPause()
        else if (!ws.current?.isPlaying()) finishTap(tap, 'playback was paused') // a tap needs the song playing
        else setTap({ ...tap, taps: [...tap.taps, ws.current.getCurrentTime() * 1000] })
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        if (!selected || !editing) return
        e.preventDefault()
        nudge((e.shiftKey ? 50 : 10) * (e.key === 'ArrowLeft' ? -1 : 1))
      } else if (e.key === 't' || e.key === 'T') {
        if (!tap) tapLine()
      } else if ((e.key === 'e' || e.key === 'E') && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (selected && !tap) setEditing(true)
        else if (!tap) setNotice('Click a word first, then press E to edit it (or double-click the word)')
      } else if (!tap && ['1', '2', '3'].includes(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey && song) {
        const lineId = lineToRate(song.lines, loop?.id, lineIndexAt(song.lines, (ws.current?.getCurrentTime() ?? 0) * 1000))
        if (lineId) rate(lineId, Number(e.key) - 1)
      } else if (!tap && !e.ctrlKey && !e.metaKey && !e.altKey && 'jklioun'.includes(e.key.toLowerCase())) {
        e.preventDefault()
        lineKey(e.key.toLowerCase())
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // A quick ? opens the keyboard map; holding it shows each button's key.
  useHoldForKeys(() => togglePopover('keys'), !player && !reviewing)

  if (loadError) return <div className="page"><p className="error">Could not open song: {loadError}</p><a className="back-link" href="#/"><Icon name="back" /> Songs</a></div>
  if (!song || !peaks || !vocalPeaks) return <div className="page">Loading…</div>

  const line = song.lines[lineIndexAt(song.lines, timeMs)]
  const tiers: Tier[] = ['lyrics', 'en']
  const rtl = song.song.language === 'he'
  const hebrew = song.song.language === 'he' // the word breakdown is Hebrew-only for now
  const loopIsSection = !!loop && song.sections.some((s) => s.id === loop.id)
  const loopLabel = loop && (song.sections.find((s) => s.id === loop.id)?.label
    ?? `line ${song.lines.findIndex((l) => l.id === loop.id) + 1}`)
  const currentSection = sectionAt(song, lineIndexAt(song.lines, timeMs))
  const linesToCheck = song.lines.filter((l) => l.words.some((w) => w.flags.length)).length
  const wordsToCheck = words.filter((w) => w.flags.length).length
  const tapLineWords = tap ? song.lines.find((l) => l.id === tap.lineId)!.words.length : 0

  return (
    <div className="editor" data-time-ms={Math.round(timeMs)}>
      <header className="topbar">
        <a className="back-link" href="#/" aria-label="Back to songs" title="Back to songs"><Icon name="back" /></a>
        <h1><span dir="auto">{song.song.title || song.song.id}</span>{song.song.artist && <small dir="auto">{song.song.artist}</small>}</h1>
        <span className={`save save-${saveState}`} data-testid="save-state" title={saveError ?? ''}>
          <i />{{ saved: 'Saved', pending: 'Unsaved…', saving: 'Saving…', error: 'Save failed' }[saveState]}
        </span>
        {saveState === 'error' && <button onClick={save}>Retry</button>}
        <span className="tspacer" />
        <button className="quiet" onClick={() => { ws.current?.pause(); setReviewing(true) }}
                title="Go through the lines one at a time: play, then confirm or tap where the singing starts">
          Review lines{linesToCheck ? ` (${linesToCheck})` : ''}
        </button>
        <button className="quiet btn-icon" onClick={() => openPlayer({ kind: 'practice', startMs: timeMs })} title="Full-screen practice (same keys, plus V for the track)"><Icon name="full" /> Practice</button>
      </header>
      {saveError && <p className="error banner" role="alert">{saveError}</p>}

      <div className="main">
        <div className="workspace">
          <div className="preview" data-testid="preview">
            <Captions line={line} timeMs={timeMs} showNiqqud={showNiqqud} tiers={tiers} language={song.song.language} />
          </div>

          <Timeline peaks={peaks} vocalPeaks={vocalPeaks} durationMs={song.song.durationMs} audioUrl={api.audioUrl(id, track)} lines={song.lines}
                    sections={song.sections} selectedId={selectedId} timeMs={timeMs} zoom={zoom} onReady={onReady} onSelect={selectWord}
                    onInteraction={() => echo.current?.cancel()}
                    range={range && rangeWords.length ? { startMs: rangeWords[0].startMs, endMs: rangeWords.at(-1)!.endMs } : null}
                    onRangeDrag={rangeFromDrag}
                    onWordTimes={(wid, a, b, side) => { setSelectedId(wid); setEdge(side); setTimes(wid, a, b, side) }}
                    onSectionEdge={(sid, ms, side) => {
                      const changed = resizeSection(structuredClone(song), sid, ms, side) // try it first, for the message
                      // Always an edit, so the band snaps to its line boundary (or back, when the drag was refused).
                      edit((s) => { resizeSection(s, sid, ms, side) })
                      const sec = song.sections.find((x) => x.id === sid)
                      if (sec) setNotice(changed ? `${sec.label} now covers the nearest whole line` : `${sec.label}: unchanged (sections can't overlap)`)
                    }} />

          {activeRange && rangeWords.length > 0 && (
            <div className="range-bar" data-testid="range-bar">
              <strong>{(() => {
                const n = new Set(rangeWords.map((w) => lineOfWord(w.id).id)).size
                return n > 1 ? `${n} lines` : `${rangeWords.length} word${rangeWords.length > 1 ? 's' : ''}`
              })()}</strong>
              <span className="meta">{rangeWords[0].id}–{rangeWords.at(-1)!.id} · {(rangeWords[0].startMs / 1000).toFixed(2)}–{(rangeWords.at(-1)!.endMs / 1000).toFixed(2)} s</span>
              <select value={sectionKind} aria-label="Section kind" onChange={(e) => setSectionKind(e.target.value as SectionKind)}>
                {SECTION_KINDS.map((k) => <option key={k}>{k}</option>)}
              </select>
              <button onClick={makeSectionFromRange}>Make section</button>
              <button onClick={makeClipFromRange}>Make clip</button>
              <button className="btn-icon" onClick={() => ws.current?.play(rangeWords[0].startMs / 1000, rangeWords.at(-1)!.endMs / 1000)}><Icon name="play" /> Play</button>
              {range && <button className="ghost" onClick={() => setRange(null)}>Clear</button>}
              <span className="hint">Shift-click a word or drag on the waveform to select more</span>
            </div>
          )}

          {selected && editing && (
            <WordInspector word={selected} edge={edge} onEdge={setEdge} lineNumber={song.lines.indexOf(lineOfWord(selected.id)) + 1}
                           wordNumber={lineOfWord(selected.id).words.indexOf(selected) + 1}
                           onTimes={(a, b) => setTimes(selected.id, a, b, b !== selected.endMs ? 'end' : 'start')}
                           onSpelling={(text) => applySpelling(selected.id, text)}
                           onClearFlags={() => edit((s) => { allWords(s).find((w) => w.id === selected.id)!.flags = [] })}
                           onPlay={() => ws.current?.play(selected.startMs / 1000, selected.endMs / 1000)}
                           onTapLine={tapLine}
                           onInsert={(side, text) => changeWords({ action: 'insert', wordId: selected.id, side, text })}
                           onDelete={() => changeWords({ action: 'delete', wordId: selected.id })}
                           lineOps={(() => {
                             const li = song.lines.findIndex((l) => l.words.some((w) => w.id === selected.id))
                             const l = song.lines[li], k = l.words.findIndex((w) => w.id === selected.id), n = li + 1
                             const last = li === song.lines.length - 1, alone = l.words.length === 1
                             return {
                               split: k > 0 ? () => lineOp({ action: 'split', wordId: selected.id }, `Line ${n} split into lines ${n} and ${n + 1}`) : null,
                               prev: k === 0 && li > 0 && !alone
                                 ? () => lineOp({ action: 'move', wordId: selected.id, to: 'prev' }, `Word moved to the end of line ${n - 1}`) : null,
                               next: k === l.words.length - 1 && !last && !alone
                                 ? () => lineOp({ action: 'move', wordId: selected.id, to: 'next' }, `Word moved to the start of line ${n + 1}`) : null,
                               join: !last ? () => lineOp({ action: 'join', lineId: l.id }, `Lines ${n} and ${n + 1} joined`) : null,
                               remove: song.lines.length > 1 ? () => lineOp({ action: 'delete', lineId: l.id }, `Line ${n} deleted`) : null,
                             }
                           })()}
                           onClose={() => { setEditing(false); setRange(null) }} rtl={rtl} />
          )}
          <LineList lines={song.lines} sections={song.sections} activeLineId={line?.id ?? null} activeWordId={activeWordId}
                    selectedId={selectedId} rangeIds={rangeIds} playing={playing} loopingId={loop?.id ?? null} onLoopLine={loopLine}
                    loops={lineLoops} ratings={ratings} onRate={rate} newWordIds={markNew ? newWordIds : undefined}
                    onSplit={(wordId) => {
                      const n = song.lines.findIndex((l) => l.words.some((w) => w.id === wordId)) + 1
                      lineOp({ action: 'split', wordId }, `Line ${n} split into lines ${n} and ${n + 1}`)
                    }}
                    showNiqqud={showNiqqud} rtl={rtl}
                    onWord={clickWord} onEditWord={editWord} onLine={selectLine} onPlayLine={playLine} onBreakdown={hebrew ? openBreakdown : undefined}
                    onEnglish={(lineId, text) => edit((s) => { s.lines.find((l) => l.id === lineId)!.english = text })} />
        </div>
        <aside className="sidebar">
          <nav className="tabs" role="tablist">
            {(['sections', 'words', 'lesson'] as Tab[]).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''}
                      onClick={() => { setTab(t); if (t === 'words' && !breakdownLineId) setBreakdownLineId(selected ? lineOfWord(selected.id).id : line?.id ?? null) }}>
                {t}{t === 'words' && wordsToCheck > 0 && <span className="tab-count">{wordsToCheck}</span>}
              </button>
            ))}
          </nav>
          {tab === 'sections' && <SectionsPanel song={song} edit={edit} timeMs={timeMs} controls={{
            playing, loopingId: loop?.id ?? null, onPlay: playSection, onLoop: loopSection, onPause: () => ws.current?.pause(), onClip: clipSection,
            onGoTo: (s) => { const r = sectionRange(song, s); ws.current?.setTime(r.startMs / 1000); setTimeMs(r.startMs) },
          }} />}
          {tab === 'words' && (
            <div className="panel-stack">
              <FlagsPanel lines={song.lines} selectedId={selectedId} showNiqqud={showNiqqud} onPick={editWord} />
              <SuggestionsBox songId={id} lines={song.lines} wordCount={words.length}
                              onPlay={(a, b) => { setLoop(null); ws.current?.play(a / 1000, b / 1000) }}
                              onSelectWord={(wid) => selectWord(wid)}
                              onAccept={(s) => changeWords(s.type === 'missing'
                                ? { action: 'insert', wordId: s.wordId, side: s.side ?? 'after', text: s.text, startMs: s.startMs, endMs: s.endMs }
                                : { action: 'delete', wordId: s.wordId })} />
              {hebrew && (() => {
                const i = song.lines.findIndex((l) => l.id === breakdownLineId)
                return <BreakdownPanel songId={id} line={i >= 0 ? song.lines[i] : null} lineNumber={i + 1} wordId={selectedId}
                                       nextLineId={i >= 0 ? song.lines[i + 1]?.id ?? null : null}
                                       showNiqqud={showNiqqud} onPickWord={(wid) => selectWord(wid)} />
              })()}
            </div>
          )}
          {tab === 'lesson' && (
            <div className="panel-stack">
              <ClipsPanel song={song} edit={edit} onPlay={(c) => { const r = clipRange(song, c); ws.current?.play(r.startMs / 1000, r.endMs / 1000) }} />
              <DrillsPanel song={song} edit={edit} onPlay={(d) => openPlayer({ kind: 'drill', drill: d })} />
            </div>
          )}
        </aside>
      </div>

      <footer className="transport">
        {/* Hold ? to see the key each button stands for */}
        <div className="seg" role="group" aria-label="Track">
          {(['original', 'vocals', 'instrumental'] as Track[]).map((t) => (
            <button key={t} className={track === t ? 'on' : ''} aria-pressed={track === t} onClick={() => setTrack(t)}>{t}</button>
          ))}
        </div>
        <div className="tcenter" role="group" aria-label="Playback">
          <button onClick={() => lineKey('j')} title={`Back ${jumpSec ? `${jumpSec} s` : 'a line'} (J)`} aria-label="Back"><Icon name="prev" /><kbd>J</kbd></button>
          <button className="play" onClick={() => ws.current?.playPause()} aria-label={playing ? 'Pause' : 'Play'} title="Play / pause (K or Space)">
            <Icon name={playing ? 'pause' : 'play'} size={22} /><kbd>K</kbd>
          </button>
          <button onClick={() => lineKey('l')} title={`Forward ${jumpSec ? `${jumpSec} s` : 'a line'} (L)`} aria-label="Forward"><Icon name="next" /><kbd>L</kbd></button>
          <span className="clock">{fmt(timeMs)} / {fmt(song.song.durationMs)}</span>
          <span className="where" data-testid="where" title="Where the playhead is">
            Line {lineIndexAt(song.lines, timeMs) + 1} of {song.lines.length}{currentSection && <>, {currentSection.label}</>}
            {loop && <b>, looping {loopLabel}</b>}
          </span>
        </div>
        <div className="tgroup" role="group" aria-label="Loop">
          <button className={`btn-icon toggle${loop && !loopIsSection ? ' on' : ''}`} aria-pressed={!!loop && !loopIsSection} onClick={() => lineKey('i')}
                  title="Loop the line at the playhead; again to stop (I)"><Icon name="loop" /> Line<kbd>I</kbd></button>
          <button className={`btn-icon toggle${loop && loopIsSection ? ' on' : ''}`} aria-pressed={!!loop && loopIsSection} onClick={() => lineKey('o')}
                  title="Loop the section at the playhead; again to stop (O)"><Icon name="loop" /> Section<kbd>O</kbd></button>
        </div>
        <div className="tgroup speed" role="group" aria-label="Speed" title="Playback speed (pitch is kept)">
          <button onClick={() => lineKey('u')} disabled={speed <= PLAY_SPEEDS[0]} aria-label="Slower"><Icon name="minus" size={16} /><kbd>U</kbd></button>
          <span className="speed-value" data-testid="speed">{Math.round(speed * 100)}%</span>
          <button onClick={() => lineKey('n')} disabled={speed >= PLAY_SPEEDS.at(-1)!} aria-label="Faster"><Icon name="plus" size={16} /><kbd>N</kbd></button>
        </div>
        <label className="zoom">Zoom <input type="range" min={0} max={1} step={0.01} value={zoom} onChange={(e) => setZoom(+e.target.value)} /></label>
        <span className={`settings-wrap${popoverLeft ? ' pop-left' : ''}`} ref={popoverRef}>
          <button className={popover === 'keys' ? 'on' : ''} aria-expanded={popover === 'keys'} aria-label="Keyboard shortcuts" onClick={() => togglePopover('keys')}
                  title="Keyboard shortcuts (tap ?). Hold ? to see each button's key"><Icon name="keys" /></button>
          <button className={popover === 'settings' ? 'on' : ''} aria-expanded={popover === 'settings'} aria-label="Settings" onClick={() => togglePopover('settings')}
                  title="Loop pause, fade, J/L jump, vowel points"><Icon name="gear" /></button>
          {popover === 'keys' && <ShortcutMap jumpSec={jumpSec} onClose={() => setPopover(null)} />}
          {popover === 'settings' && (
            <div className="settings-pop" role="dialog" aria-label="Playback settings">
              <label>Pause between loops
                <select value={loopPauseMs} aria-label="Pause between loops" onChange={(e) => setLoopPauseMs(+e.target.value)}>
                  {LOOP_PAUSES_MS.map((ms) => <option key={ms} value={ms}>{ms / 1000} s</option>)}
                </select>
              </label>
              <label className="toggle"><input type="checkbox" checked={loopFade} onChange={(e) => setLoopFade(e.target.checked)} /> Echo fade between loops</label>
              <label>J / L jump
                <select value={jumpSec} aria-label="J and L jump" onChange={(e) => setJumpSec(+e.target.value)}>
                  <option value={0}>by line</option>
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((s) => <option key={s} value={s}>{s} s</option>)}
                </select>
              </label>
              <hr />
              {words.some((w) => stripNiqqud(w.plain) !== w.plain.normalize('NFC')) && (
                <label className="toggle" title="This song's lyrics were written with vowel points"><input type="checkbox" checked={showNiqqud} onChange={(e) => setShowNiqqud(e.target.checked)} /> Show vowel points</label>
              )}
              <label className="toggle" title="Words not found in any song you've practised or rated"><input type="checkbox" checked={markNew} onChange={(e) => setMarkNew(e.target.checked)} /> Mark words new to you</label>
              <p className="hint">Remembered in this browser.</p>
            </div>
          )}
        </span>
      </footer>

      {player && <Player song={song} mode={player} showNiqqud={showNiqqud}
                         loopPauseMs={loopPauseMs} loopFade={loopFade} jumpSec={jumpSec} ratings={ratings} onRate={rate}
                         onClose={() => setPlayer(null)} />}
      {reviewing && <Review song={song} edit={edit} showNiqqud={showNiqqud} onClose={() => { setReviewing(false); history.replaceState(null, '', `#/song/${id}`) }} />}

      {tap && (
        <div className="tap-banner" role="status">
          Tap mode: press <kbd>Space</kbd> at the start of each word ({Math.min(tap.taps.length, tapLineWords)}/{tapLineWords}), once more at the end. <kbd>Esc</kbd> to finish.
        </div>
      )}
      {notice && <div className="toast" role="status" onAnimationEnd={() => setNotice(null)}>{notice}</div>}
      {lineBar && (
        <div className="line-bar" role="status" data-testid="line-bar">
          <span>{lineBar.text}{lineBar.note && <span className="meta"> · {lineBar.note}</span>}</span>
          {lineBar.undo && <button className="btn-icon" onClick={() => { const u = lineBar.undo!; setLineBar(null); lineOp(u, 'Undone') }}><Icon name="undo" size={16} /> Undo</button>}
          <button className="ghost" onClick={() => setLineBar(null)} aria-label="Close"><Icon name="close" size={16} /></button>
        </div>
      )}
    </div>
  )
}
