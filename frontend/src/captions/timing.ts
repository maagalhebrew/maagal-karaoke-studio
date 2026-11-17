// Pure timing helpers shared by the editor and (M4) the Remotion renderer.
import type { Clip, Line, Section, Song, Word } from '../types'

export const MIN_WORD_MS = 40

export interface Span { startMs: number; endMs: number }

/** 0 before the span, 1 after it, linear in between. */
export function progress(span: Span, t: number): number {
  if (t <= span.startMs) return 0
  if (t >= span.endMs) return 1
  return (t - span.startMs) / (span.endMs - span.startMs)
}

/** Index of the line to show at time t: the last line that has started (or the first line before the song). */
export function lineIndexAt(lines: Line[], t: number): number {
  let idx = 0
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].words[0].startMs <= t) idx = i
    else break
  }
  return idx
}

// Loops: a little room around a looped line (the transition between passes is in player/echoOut.ts).
export const LOOP_PAD_BEFORE_MS = 200, LOOP_PAD_AFTER_MS = 300
export const LOOP_PAUSES_MS = [0, 500, 1000, 1500, 2000, 2500, 3000]

/** A looped stretch. startMs and endMs include the padding; firstMs and lastMs are where its singing starts and ends. */
export interface LoopSpan extends Span { id: string; firstMs: number; lastMs: number }
export function loopSpan(id: string, firstMs: number, lastMs: number, durationMs: number): LoopSpan {
  return { id, firstMs, lastMs, startMs: Math.max(0, firstMs - LOOP_PAD_BEFORE_MS), endMs: Math.min(durationMs, lastMs + LOOP_PAD_AFTER_MS) }
}

// Keys shared by the studio editor and Practice: J/L jumps, U/N speed steps, O's section.
export const PLAY_SPEEDS = [0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1]

/** U (slower) / N (faster): the next speed in PLAY_SPEEDS. */
export function stepSpeed(speed: number, faster: boolean): number {
  const i = PLAY_SPEEDS.findIndex((s) => s >= speed - 0.001)
  const k = (i < 0 ? PLAY_SPEEDS.length - 1 : i) + (faster ? 1 : -1)
  return PLAY_SPEEDS[Math.max(0, Math.min(PLAY_SPEEDS.length - 1, k))]
}

/** Where J (back) / L (forward) go from t: jumpSec seconds, or by line when jumpSec is 0
 *  (J: this line's start, or the previous line's if already within its first second). */
export function jumpTarget(lines: Line[], t: number, forward: boolean, jumpSec: number, durationMs: number): number {
  if (jumpSec > 0) return Math.max(0, Math.min(durationMs, t + (forward ? 1 : -1) * jumpSec * 1000))
  const i = lineIndexAt(lines, t), start = (k: number) => lines[k].words[0].startMs
  if (forward) return t < start(0) ? start(0) : i < lines.length - 1 ? start(i + 1) : t
  return t - start(i) > 1000 || i === 0 ? start(i) : start(i - 1)
}

/** The section the line at lineIndex belongs to. */
export function sectionAt(song: Song, lineIndex: number): Section | undefined {
  const idx = (id: string) => song.lines.findIndex((l) => l.id === id)
  return song.sections.find((s) => idx(s.fromLine) <= lineIndex && lineIndex <= idx(s.toLine))
}

export function wordAt(words: Word[], t: number): Word | undefined {
  return words.find((w) => w.startMs <= t && t < w.endMs)
}

/** A clip's audio span: first word start - padBefore .. last word end + padAfter, inside the song. */
export function clipRange(song: Song, clip: Clip): Span {
  const words = song.lines.flatMap((l) => l.words)
  const from = words.find((w) => w.id === clip.fromWord)!, to = words.find((w) => w.id === clip.toWord)!
  return {
    startMs: Math.max(0, from.startMs - clip.padBeforeMs),
    endMs: Math.min(song.song.durationMs, to.endMs + clip.padAfterMs),
  }
}

/** The clip's words, still grouped by line (so captions can show only what the clip covers). */
export function clipLines(song: Song, clip: Clip): Line[] {
  const words = song.lines.flatMap((l) => l.words.map((w) => ({ w, line: l })))
  const a = words.findIndex((x) => x.w.id === clip.fromWord), b = words.findIndex((x) => x.w.id === clip.toWord)
  const out: Line[] = []
  for (const { w, line } of words.slice(a, b + 1)) {
    if (out.at(-1)?.id !== line.id) out.push({ ...line, words: [] })
    out.at(-1)!.words.push(w)
  }
  return out
}

const NIQQUD =/[֑-ׇֽֿׁׂׅׄ]/g
export const stripNiqqud = (s: string) => s.normalize('NFC').replace(NIQQUD, '')
/** A word as written, or without its vowel points. */
export const wordText = (w: Word, showNiqqud: boolean) => (showNiqqud ? w.plain : stripNiqqud(w.plain))

/** Port of the pipeline's stage-5 repair: monotonic, every word >= 40 ms, inside the song.
 *  Returns the indexes it changed. */
export function repairTiming(words: Word[], durationMs: number): number[] {
  const times: [number, number][] = []
  let prevEnd = 0
  for (const w of words) {
    const start = Math.max(w.startMs, prevEnd)
    const end = Math.max(w.endMs, start + MIN_WORD_MS)
    times.push([start, end])
    prevEnd = end
  }
  let limit = durationMs
  for (let i = times.length - 1; i >= 0; i--) {
    times[i][1] = Math.min(times[i][1], limit)
    times[i][0] = Math.min(times[i][0], times[i][1] - MIN_WORD_MS)
    limit = times[i][0]
  }
  const changed: number[] = []
  words.forEach((w, i) => {
    const [s, e] = times[i].map(Math.round)
    if (s !== w.startMs || e !== w.endMs) changed.push(i)
    w.startMs = s
    w.endMs = e
  })
  return changed
}
