// Song-structure edits (sections, clips, drills) as pure functions on a song copy.
import { MIN_WORD_MS } from '../captions/timing'
import type { Clip, Section, SectionKind, Song } from '../types'

export interface WordRange { fromWord: string; toWord: string }

export const SECTION_KINDS: SectionKind[] = ['verse', 'chorus', 'bridge', 'intro', 'outro', 'transition', 'custom']

export function nextId(prefix: string, ids: string[]): string {
  const n = Math.max(0, ...ids.map((id) => Number(id.slice(prefix.length)) || 0))
  return `${prefix}${n + 1}`
}

const lineOf = (song: Song, wordId: string) => song.lines.findIndex((l) => l.words.some((w) => w.id === wordId))

/** Make a section over the lines the range touches. Overlapped sections are trimmed or split around it,
 *  so sections never overlap; section ids are renumbered in order (nothing else refers to them). */
export function makeSection(song: Song, range: WordRange, kind: SectionKind): Section {
  const a = lineOf(song, range.fromWord), b = lineOf(song, range.toWord)
  const idx = (lineId: string) => song.lines.findIndex((l) => l.id === lineId)
  const id = (i: number) => song.lines[i].id
  const kept: Section[] = []
  for (const s of song.sections) {
    const x = idx(s.fromLine), y = idx(s.toLine)
    if (y < a || x > b) { kept.push(s); continue }
    if (x < a) kept.push({ ...s, toLine: id(a - 1) })
    if (y > b) kept.push({ ...s, fromLine: id(b + 1) })
  }
  const count = song.sections.filter((s) => s.kind === kind).length + 1
  const label = kind === 'custom' ? `Custom ${count}` : `${kind[0].toUpperCase()}${kind.slice(1)} ${count}`
  const made: Section = { id: '', kind, label, fromLine: id(a), toLine: id(b) }
  song.sections = [...kept, made]
    .sort((s, t) => idx(s.fromLine) - idx(t.fromLine))
    .map((s, i) => ({ ...s, id: `S${i + 1}` }))
  return song.sections.find((s) => s.fromLine === made.fromLine && s.kind === kind)!
}

/** How many lines a section covers, as shown on its band and card ("7 lines"). */
export function sectionLineCount(lines: { id: string }[], s: Section): string {
  const n = lines.findIndex((l) => l.id === s.toLine) - lines.findIndex((l) => l.id === s.fromLine) + 1
  return `${n} line${n === 1 ? '' : 's'}`
}

/** A dragged section edge: snap it to the nearest line boundary. The section keeps at least one line and never
 *  runs into its neighbours (they are not touched). Returns false if nothing changed. */
export function resizeSection(song: Song, sectionId: string, ms: number, side: 'start' | 'end'): boolean {
  const lines = song.lines, idx = (id: string) => lines.findIndex((l) => l.id === id)
  const s = song.sections.find((x) => x.id === sectionId)
  if (!s) return false
  const from = idx(s.fromLine), to = idx(s.toLine)
  const others = song.sections.filter((x) => x !== s)
  const prevEnd = Math.max(-1, ...others.map((x) => idx(x.toLine)).filter((t) => t < from))
  const nextStart = Math.min(lines.length, ...others.map((x) => idx(x.fromLine)).filter((f) => f > to))
  const nearest = (lo: number, hi: number, at: (i: number) => number) => {
    let best = lo
    for (let i = lo; i <= hi; i++) if (Math.abs(at(i) - ms) < Math.abs(at(best) - ms)) best = i
    return best
  }
  if (side === 'start') {
    const i = nearest(prevEnd + 1, to, (k) => lines[k].words[0].startMs)
    if (i === from) return false
    s.fromLine = lines[i].id
  } else {
    const i = nearest(from, nextStart - 1, (k) => lines[k].words.at(-1)!.endMs)
    if (i === to) return false
    s.toLine = lines[i].id
  }
  return true
}

/** A section's span: first word of its first line to last word of its last line. */
export function sectionRange(song: Song, s: Section): WordRange & { startMs: number; endMs: number } {
  const from = song.lines.find((l) => l.id === s.fromLine)!, to = song.lines.find((l) => l.id === s.toLine)!
  const first = from.words[0], last = to.words[to.words.length - 1]
  return { fromWord: first.id, toWord: last.id, startMs: first.startMs, endMs: last.endMs }
}

/** Move a whole line by deltaMs, keeping its word rhythm. It stays between its neighbour lines;
 *  if it no longer fits there it is squeezed (never below 40 ms per word). */
export function shiftLine(song: Song, lineIndex: number, deltaMs: number) {
  const line = song.lines[lineIndex], words = line.words
  const lo = lineIndex > 0 ? song.lines[lineIndex - 1].words.at(-1)!.endMs : 0
  const hi = lineIndex < song.lines.length - 1 ? song.lines[lineIndex + 1].words[0].startMs : song.song.durationMs
  const first = words[0].startMs, last = words.at(-1)!.endMs
  const minLen = MIN_WORD_MS * words.length
  let a = Math.max(lo, first + deltaMs)
  const b = Math.min(hi, a + (last - first))
  if (b - a < minLen) a = Math.max(lo, b - minLen)
  const scale = (b - a) / Math.max(1, last - first)
  const at = (t: number) => Math.round(a + (t - first) * scale)
  for (const w of words) { w.startMs = at(w.startMs); w.endMs = Math.max(at(w.endMs), w.startMs + MIN_WORD_MS) }
}

export function makeClip(song: Song, range: WordRange): Clip {
  const id = nextId('C', song.clips.map((c) => c.id))
  const clip: Clip = { id, name: `Clip ${id.slice(1)}`, fromWord: range.fromWord, toWord: range.toWord, padBeforeMs: 300, padAfterMs: 300 }
  song.clips.push(clip)
  return clip
}

/** Drills that use this clip (a used clip can't be deleted). */
export const drillsUsing = (song: Song, clipId: string) =>
  song.drills.filter((d) => d.steps.some((s) => s.type === 'clip' && s.clip === clipId))
