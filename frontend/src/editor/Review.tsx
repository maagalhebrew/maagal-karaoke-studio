// Review mode: one line at a time. Play it with a lead-in, then either confirm it or tap when the singing
// really starts (the whole line moves). Owns its own <audio> element, like the practice player.
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { api } from '../api'
import { Captions } from '../captions/Captions'
import { Icon } from '../icons'
import type { Song, Tier, Track } from '../types'
import { TIMING_FLAGS } from './FlagsPanel'
import { shiftLine } from './structure'

type PitchAudio = HTMLAudioElement & { preservesPitch: boolean }
type Edit = (mutate: (s: Song) => void) => void

const LEAD_MS = 1500 // play this much before the line, so an early start is audible
const TAIL_MS = 600
const NUDGE_MS = 100
const CAPTIONS = { '--cap-size': 'clamp(36px, 6vw, 84px)' } as CSSProperties

const needsCheck = (song: Song, i: number) => song.lines[i].words.some((w) => w.flags.length > 0)
const clearTiming = (song: Song, i: number) => {
  for (const w of song.lines[i].words) w.flags = w.flags.filter((f) => !TIMING_FLAGS.includes(f))
}

interface Props { song: Song; edit: Edit; showNiqqud: boolean; onClose: () => void }

export function Review({ song, edit, showNiqqud, onClose }: Props) {
  // The lines to go through are fixed when review opens, so a confirmed line doesn't vanish from under you.
  const [queue] = useState(() => {
    const flagged = song.lines.map((_, i) => i).filter((i) => needsCheck(song, i))
    return flagged.length ? flagged : song.lines.map((_, i) => i)
  })
  const [pos, setPos] = useState(0)
  const [done, setDone] = useState(false)
  const [timeMs, setTimeMs] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [track, setTrack] = useState<Track>('original')
  const [slow, setSlow] = useState(false)
  const [undo, setUndo] = useState<{ index: number; words: { startMs: number; endMs: number; flags: string[] }[] } | null>(null)
  const audio = useMemo(() => { const a = new Audio() as PitchAudio; a.preload = 'auto'; a.preservesPitch = true; return a }, [])

  const index = queue[pos]
  const line = song.lines[index]
  const startMs = line.words[0].startMs
  const span = { from: Math.max(0, startMs - LEAD_MS), to: Math.min(song.song.durationMs, line.words.at(-1)!.endMs + TAIL_MS) }
  const spanRef = useRef(span)
  spanRef.current = span
  const left = queue.filter((i) => needsCheck(song, i)).length
  const tiers: Tier[] = ['lyrics', 'en']

  useEffect(() => {
    const on = () => setPlaying(!audio.paused)
    audio.addEventListener('play', on)
    audio.addEventListener('pause', on)
    return () => { audio.pause(); audio.removeEventListener('play', on); audio.removeEventListener('pause', on); audio.removeAttribute('src') }
  }, [audio])

  useEffect(() => {
    const at = audio.currentTime
    audio.src = api.audioUrl(song.song.id, track)
    audio.currentTime = at
  }, [audio, song.song.id, track])

  useEffect(() => {
    const rate = slow ? 0.75 : 1
    audio.defaultPlaybackRate = rate
    audio.playbackRate = rate
    audio.preservesPitch = true
  }, [audio, slow, track])

  // Clock; playback stops at the end of the line.
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const t = audio.currentTime * 1000
      if (!audio.paused && t >= spanRef.current.to) audio.pause()
      setTimeMs(t)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [audio])

  const play = () => { audio.currentTime = spanRef.current.from / 1000; audio.play().catch(() => {}) }
  useEffect(play, [pos]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Change this line's timing (undoable); a fixed line counts as checked. */
  const change = (deltaMs: number) => {
    setUndo({ index, words: line.words.map((w) => ({ startMs: w.startMs, endMs: w.endMs, flags: [...w.flags] })) })
    edit((s) => { shiftLine(s, index, deltaMs); clearTiming(s, index) })
  }
  const startsNow = () => { if (!audio.paused) change(Math.round(audio.currentTime * 1000 - startMs)) }
  const goTo = (p: number) => {
    if (p >= queue.length) { audio.pause(); setDone(true); return }
    setUndo(null)
    setPos(Math.max(0, p))
  }
  const confirm = () => { edit((s) => clearTiming(s, index)); goTo(pos + 1) }
  const undoLast = () => {
    if (!undo) return
    edit((s) => { s.lines[undo.index].words.forEach((w, k) => Object.assign(w, undo.words[k])) })
    setUndo(null)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'BUTTON') (e.target as HTMLElement).blur()
      if (e.key === 'Escape') onClose()
      else if (done) return
      else if (e.code === 'Space') { e.preventDefault(); if (audio.paused) play(); else audio.pause() }
      else if (e.key === 's' || e.key === 'S') startsNow()
      else if (e.key === 'Enter') { e.preventDefault(); confirm() }
      else if (e.key === 'ArrowRight') goTo(pos + 1)
      else if (e.key === 'ArrowLeft') goTo(pos - 1)
      else if ((e.key === 'z' || e.key === 'Z') && (e.ctrlKey || e.metaKey)) undoLast()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const pct = (t: number) => `${Math.min(100, Math.max(0, ((t - span.from) / (span.to - span.from)) * 100))}%`

  return (
    <div className="player review" data-testid="review">
      <header className="player-hud">
        <strong>Review</strong>
        <span data-testid="review-progress">Line {pos + 1} of {queue.length} · {left} left to check</span>
        <span className="keys">Space play · S singing starts now · Enter looks right · Left and Right arrows skip · Ctrl+Z undo · Esc close</span>
        <button onClick={onClose}>Close</button>
      </header>

      {done ? (
        <main className="player-stage">
          <div className="review-done">
            <p>{left === 0 ? 'All lines checked.' : `Reached the end · ${left} line(s) still unchecked.`}</p>
            <button onClick={onClose}>Back to the Studio editor</button>
          </div>
        </main>
      ) : (
        <>
          <main className="player-stage">
            <Captions line={line} timeMs={timeMs} showNiqqud={showNiqqud} language={song.song.language} tiers={tiers} style={CAPTIONS} />
          </main>
          <div className="review-bar" title="Grey: lead-in before the line. The marker is where the line starts now.">
            <div className="review-lead" style={{ width: pct(startMs) }} />
            <div className="review-mark" style={{ left: pct(startMs) }} />
            <div className="review-head" style={{ left: pct(timeMs) }} />
          </div>
          <footer className="review-controls">
            <button className="btn-icon" onClick={() => (playing ? audio.pause() : play())}><Icon name={playing ? 'pause' : 'play'} /> {playing ? 'Pause' : 'Play line'}</button>
            <button className="primary" onClick={startsNow} disabled={!playing} title="Press when you hear the singing start">
              Singing starts now (S)
            </button>
            <button className="btn-icon" onClick={() => change(-NUDGE_MS)}><Icon name="left" /> 0.1 s earlier</button>
            <button className="btn-icon" onClick={() => change(NUDGE_MS)}>0.1 s later <Icon name="right" /></button>
            <button onClick={undoLast} disabled={!undo}>Undo</button>
            <button className="ok btn-icon" onClick={confirm}><Icon name="check" /> Looks right (Enter)</button>
            <span className="review-opts">
              <label><input type="checkbox" checked={slow} onChange={(e) => setSlow(e.target.checked)} /> 75% speed</label>
              <label><input type="checkbox" checked={track === 'vocals'} onChange={(e) => setTrack(e.target.checked ? 'vocals' : 'original')} /> vocals only</label>
            </span>
          </footer>
        </>
      )}
    </div>
  )
}
