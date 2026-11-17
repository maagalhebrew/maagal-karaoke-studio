// Full-screen player: practice mode (free playback with loop/speed/track keys) and drill playback.
// Owns its own <audio> element; slowed playback keeps pitch (preservesPitch).
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { api } from '../api'
import { Captions } from '../captions/Captions'
import { clipLines, clipRange, jumpTarget, lineIndexAt, loopSpan, sectionAt, stepSpeed, type LoopSpan } from '../captions/timing'
import { debug, type PlayerEvent } from '../debug'
import { useHoldForKeys } from '../holdKeys'
import { RATING_LABELS, lineToRate, nextRating, usePracticeLog } from '../practice'
import type { Drill, Line, Song, Tier, Track } from '../types'
import { EchoOut } from './echoOut'

type PitchAudio = HTMLAudioElement & { preservesPitch: boolean }
type Loop = LoopSpan // a line or a section
export type PlayerMode = { kind: 'practice'; startMs: number } | { kind: 'drill'; drill: Drill }

type View =
  | { kind: 'song' }
  | { kind: 'clip'; lines: Line[]; tiers: Tier[]; yourTurn: boolean; gapMs: number }
  | { kind: 'card'; text: string }
  | { kind: 'done' }

const MIN_SPEED = 0.5, MAX_SPEED = 1
const STAGE_CAPTIONS = { '--cap-size': 'clamp(36px, 6vw, 84px)' } as CSSProperties

class Aborted extends Error {}

function once(el: EventTarget, event: string, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const done = () => { el.removeEventListener(event, done); resolve() }
    el.addEventListener(event, done)
    signal?.addEventListener('abort', () => { el.removeEventListener(event, done); reject(new Aborted()) })
  })
}

function sleep(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => { clearTimeout(t); reject(new Aborted()) })
  })
}

interface PlayerProps {
  song: Song; mode: PlayerMode; showNiqqud: boolean
  loopPauseMs: number; loopFade: boolean; jumpSec: number // the studio editor's settings
  ratings: Record<string, number>; onRate: (lineId: string, rating: number) => void // shared with the studio editor
  onClose: () => void
}

export function Player({ song, mode, showNiqqud, loopPauseMs, loopFade, jumpSec, ratings, onRate, onClose }: PlayerProps) {
  const shown = (tiers: Tier[]) => tiers
  const audio = useMemo(() => {
    const a = new Audio() as PitchAudio
    a.preservesPitch = true
    a.preload = 'auto'
    return a
  }, [])
  const echo = useMemo(() => new EchoOut(audio), [audio]) // the fade between loop passes
  useHoldForKeys()
  const speedRef = useRef(1)
  const root = useRef<HTMLDivElement>(null)
  const log = useRef<PlayerEvent[]>([])
  const [timeMs, setTimeMs] = useState(0)
  const [view, setView] = useState<View>({ kind: 'song' })
  const [status, setStatus] = useState('')
  const [speed, setSpeedState] = useState(1)
  const [track, setTrackState] = useState<Track>('original')
  const [loop, setLoop] = useState<Loop | null>(null)
  const [flash, setFlash] = useState<string | null>(null) // a short message in the HUD
  useEffect(() => { if (!flash) return; const t = window.setTimeout(() => setFlash(null), 2500); return () => window.clearTimeout(t) }, [flash])
  const [playing, setPlaying] = useState(false)
  const [run, setRun] = useState(0)
  const loopRef = useRef(loop)
  loopRef.current = loop
  const gapTimer = useRef<number | undefined>(undefined)
  const countLoop = usePracticeLog(song.song.id, 'practice', playing) // playing time + line-loop passes

  const note = (event: string, detail?: Record<string, unknown>) =>
    log.current.push({ event, t: performance.now(), audioMs: Math.round(audio.currentTime * 1000), detail })

  const setSpeed = (s: number) => {
    const v = Math.round(Math.min(MAX_SPEED, Math.max(MIN_SPEED, s)) * 100) / 100
    audio.defaultPlaybackRate = v
    audio.playbackRate = v
    audio.preservesPitch = true
    speedRef.current = v
    setSpeedState(v)
  }

  /** Switch track keeping the playhead (a new src resets playbackRate, so it is re-applied). */
  const loadTrack = async (t: Track, signal?: AbortSignal) => {
    const url = api.audioUrl(song.song.id, t)
    setTrackState(t)
    if (audio.src.endsWith(url)) return
    const at = audio.currentTime, wasPlaying = !audio.paused, rate = audio.playbackRate
    audio.src = url
    await once(audio, 'loadedmetadata', signal)
    audio.currentTime = at
    setSpeed(rate)
    if (wasPlaying) await audio.play()
  }

  // Lifetime: debug hook, full screen, play/pause state, clean-up.
  useEffect(() => {
    debug.player = { audio, log: log.current }
    root.current?.requestFullscreen?.().catch(() => {})
    const on = () => setPlaying(!audio.paused)
    audio.addEventListener('play', on)
    audio.addEventListener('pause', on)
    return () => {
      audio.pause()
      echo.dispose()
      audio.removeEventListener('play', on)
      audio.removeEventListener('pause', on)
      audio.removeAttribute('src')
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
      delete debug.player
    }
  }, [audio])

  // Clock (and the line loop in practice mode).
  useEffect(() => {
    let raf = 0
    const tick = () => {
      setTimeMs(audio.currentTime * 1000)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    // The loop point runs on a timer, not the screen refresh: browsers stop that in a hidden tab.
    const check = window.setInterval(() => {
      const l = loopRef.current
      if (!l || audio.paused || echo.busy) return
      const t = audio.currentTime * 1000
      if (t < (loopFade ? l.lastMs : l.endMs)) return
      note('loop')
      countLoop(l.id)
      if (loopFade) { echo.run(l.firstMs, loopPauseMs, speedRef.current); return }
      audio.currentTime = l.startMs / 1000
      if (loopPauseMs > 0) { // the pause between passes
        audio.pause()
        gapTimer.current = window.setTimeout(() => { if (loopRef.current === l) audio.play().catch(() => {}) }, loopPauseMs)
      }
    }, 10)
    return () => { cancelAnimationFrame(raf); window.clearInterval(check) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audio, loopFade, loopPauseMs])

  // Loop off: full volume, no pending pass.
  useEffect(() => {
    if (loop) return
    window.clearTimeout(gapTimer.current)
    echo.cancel()
  }, [audio, echo, loop])

  // --- practice ---------------------------------------------------------------------
  useEffect(() => {
    if (mode.kind !== 'practice') return
    loadTrack('original').then(() => { audio.currentTime = mode.startMs / 1000; return audio.play() }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- drill ------------------------------------------------------------------------
  const playRange = async (startMs: number, endMs: number, signal: AbortSignal) => {
    audio.currentTime = startMs / 1000
    await once(audio, 'seeked', signal)
    await audio.play()
    await new Promise<void>((resolve, reject) => {
      const tick = () => {
        if (signal.aborted) { audio.pause(); return reject(new Aborted()) }
        if (audio.currentTime * 1000 >= endMs || audio.ended) { audio.pause(); return resolve() }
        requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    })
  }

  useEffect(() => {
    if (mode.kind !== 'drill') return
    const ctl = new AbortController()
    const { signal } = ctl
    const steps = mode.drill.steps
    log.current.length = 0
    const runDrill = async () => {
      note('drill-start', { steps: steps.length })
      for (const [i, step] of steps.entries()) {
        const where = `Step ${i + 1}/${steps.length}`
        if (step.type === 'card') {
          setStatus(`${where} · card`)
          setView({ kind: 'card', text: step.text })
          note('card-start', { step: i })
          await sleep(step.durationMs, signal)
          note('card-end', { step: i })
          continue
        }
        const clip = song.clips.find((c) => c.id === step.clip)!
        const r = clipRange(song, clip), lines = clipLines(song, clip)
        await loadTrack(step.track, signal)
        setSpeed(step.speed)
        for (let k = 1; k <= step.repeats; k++) {
          setStatus(`${where} · ${clip.name} · ${k}/${step.repeats} · ${Math.round(step.speed * 100)}% · ${step.track}`)
          setView({ kind: 'clip', lines, tiers: step.tiers, yourTurn: false, gapMs: 0 })
          note('clip-start', { step: i, repeat: k, speed: audio.playbackRate, preservesPitch: audio.preservesPitch, track: step.track, clipMs: r.endMs - r.startMs })
          await playRange(r.startMs, r.endMs, signal)
          note('clip-end', { step: i, repeat: k })
          if (step.yourTurn) {
            // Silence as long as the clip took to play, captions held on screen.
            const gapMs = Math.round((r.endMs - r.startMs) / step.speed)
            setView({ kind: 'clip', lines, tiers: step.tiers, yourTurn: true, gapMs })
            note('gap-start', { step: i, repeat: k, gapMs })
            await sleep(gapMs, signal)
            note('gap-end', { step: i, repeat: k })
          }
        }
      }
      note('drill-end')
      setView({ kind: 'done' })
      setStatus('Drill complete')
    }
    runDrill().catch((e) => { if (!(e instanceof Aborted)) setStatus(`Error: ${(e as Error).message}`) })
    return () => { ctl.abort(); audio.pause() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run])

  // --- keys -------------------------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return }
      if (mode.kind !== 'practice') return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      // The studio editor's keys: J back · K/Space play · L forward · I loop line · O loop section · U slower · N faster
      // (plus V: original / instrumental).
      const key = e.code === 'Space' ? 'k' : e.key.toLowerCase()
      const lines = song.lines, t = audio.currentTime * 1000, i = lineIndexAt(lines, t)
      const seek = (ms: number) => { echo.cancel(); audio.currentTime = ms / 1000; setTimeMs(ms) }
      const padded = (id: string, startMs: number, endMs: number) => loopSpan(id, startMs, endMs, song.song.durationMs)
      if (key === 'k') { e.preventDefault(); if (audio.paused) audio.play(); else audio.pause() }
      else if (key === 'j' || key === 'l') seek(jumpTarget(lines, t, key === 'l', jumpSec, song.song.durationMs))
      else if (key === 'u' || key === 'n') setSpeed(stepSpeed(speed, key === 'n'))
      else if (key === 'v') loadTrack(track === 'original' ? 'instrumental' : 'original')
      else if (['1', '2', '3'].includes(key)) { // rate the line: 1 don't know · 2 shaky · 3 know it (again: clear)
        const lineId = lineToRate(lines, loop?.id, i)
        if (!lineId) return
        const next = nextRating(ratings[lineId], Number(key) - 1)
        onRate(lineId, Number(key) - 1)
        setFlash(`line ${lines.findIndex((l) => l.id === lineId) + 1}: ${next === null ? 'rating cleared' : RATING_LABELS[next]}`)
      }
      else if (key === 'i' || key === 'o') {
        const isSection = !!loop && song.sections.some((s) => s.id === loop.id)
        if (loop && isSection === (key === 'o')) { setLoop(null); return } // same key again: stop
        let next: Loop | null = null
        if (key === 'i') next = padded(lines[i].id, lines[i].words[0].startMs, lines[i].words.at(-1)!.endMs)
        else {
          const s = sectionAt(song, i)
          if (s) {
            const from = lines.find((l) => l.id === s.fromLine)!, to = lines.find((l) => l.id === s.toLine)!
            next = padded(s.id, from.words[0].startMs, to.words.at(-1)!.endMs)
          } else setFlash('No section here to loop')
        }
        if (next) { if (loopFade) echo.prepare(); setLoop(next); seek(next.startMs); audio.play().catch(() => {}) }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const loopName = loop && (song.sections.find((s) => s.id === loop.id)?.label
    ?? `line ${song.lines.findIndex((l) => l.id === loop.id) + 1}`)
  const here = song.lines[lineIndexAt(song.lines, timeMs)]
  const hereRating = here && ratings[here.id] !== undefined ? ` · ${RATING_LABELS[ratings[here.id]]}` : ''
  const hud = mode.kind === 'practice'
    ? `${playing ? 'Playing' : 'Paused'} · ${Math.round(speed * 100)}% · ${track}${loop ? ` · looping ${loopName}` : ''}${hereRating}${flash ? ` · ${flash}` : ''}`
    : status

  return (
    <div ref={root} className="player" data-testid="player" data-view={view.kind} role="dialog" aria-label={mode.kind === 'drill' ? mode.drill.name : 'Practice'}>
      <header className="player-hud">
        <strong>{mode.kind === 'drill' ? mode.drill.name : 'Practice'}</strong>
        <span data-testid="player-status">{hud}</span>
        <span className="keys">{mode.kind === 'practice'
          ? <><span className="keys-all">J back · K/Space play · L forward{jumpSec ? ` (${jumpSec} s)` : ' (line)'} · I loop line · O loop section · U slower · N faster · V original/instrumental · 1/2/3 rate the line · Esc exit</span><span className="keys-hint">Hold ? for the keys</span></>
          : 'Esc stop'}</span>
        <button onClick={onClose}>Close</button>
      </header>

      <main className="player-stage">
        {view.kind === 'song' && <Captions line={song.lines[lineIndexAt(song.lines, timeMs)]} timeMs={timeMs} showNiqqud={showNiqqud} language={song.song.language}
                                           tiers={['lyrics', 'en']} style={STAGE_CAPTIONS} />}
        {view.kind === 'clip' && (
          <div className="clip-view" data-held={view.yourTurn}>
            {view.yourTurn
              ? view.lines.map((l) => <Captions key={l.id} line={l} timeMs={-1} showNiqqud={showNiqqud} language={song.song.language} tiers={shown(view.tiers)} style={STAGE_CAPTIONS} />)
              : <Captions line={view.lines[lineIndexAt(view.lines, timeMs)]} timeMs={timeMs} showNiqqud={showNiqqud} language={song.song.language} tiers={shown(view.tiers)} style={STAGE_CAPTIONS} />}
            {view.yourTurn && (
              <div className="your-turn" data-testid="your-turn">
                Your turn
                <div className="gap-bar"><div style={{ animationDuration: `${view.gapMs}ms` }} /></div>
              </div>
            )}
          </div>
        )}
        {view.kind === 'card' && <div className="card-view" data-testid="card">{view.text}</div>}
        {view.kind === 'done' && (
          <div className="done-view">
            <p>Drill complete</p>
            <button onClick={() => { setView({ kind: 'song' }); setRun((n) => n + 1) }}>Replay</button>
            <button onClick={onClose}>Close</button>
          </div>
        )}
      </main>
    </div>
  )
}
