// A drill laid out on a timeline: what the lesson video shows, in order. Shared by the Remotion
// renderer (M4) and the excerpt guard (M5). Mirrors the drill player: each clip repeat is followed by
// a "your turn" gap as long as the clip took to play.
import type { Clip, Drill, Song, Tier, Track } from '../types'
import { clipRange } from './timing'

interface Base { startMs: number; durationMs: number; step: number }
export type Segment =
  | (Base & { kind: 'card'; text: string })
  | (Base & { kind: 'clip'; repeat: number; clip: Clip; songFromMs: number; songToMs: number; speed: number; track: Track; tiers: Tier[] })
  | (Base & { kind: 'gap'; repeat: number; clip: Clip; songFromMs: number; songToMs: number; tiers: Tier[] })

export function lessonTimeline(song: Song, drill: Drill): Segment[] {
  const out: Segment[] = []
  let t = 0
  drill.steps.forEach((step, i) => {
    if (step.type === 'card') {
      out.push({ kind: 'card', startMs: t, durationMs: step.durationMs, step: i, text: step.text })
      t += step.durationMs
      return
    }
    const clip = song.clips.find((c) => c.id === step.clip)!
    const r = clipRange(song, clip)
    const played = Math.round((r.endMs - r.startMs) / step.speed)
    for (let k = 1; k <= step.repeats; k++) {
      out.push({ kind: 'clip', startMs: t, durationMs: played, step: i, repeat: k, clip, songFromMs: r.startMs, songToMs: r.endMs,
                 speed: step.speed, track: step.track, tiers: step.tiers })
      t += played
      if (step.yourTurn) {
        out.push({ kind: 'gap', startMs: t, durationMs: played, step: i, repeat: k, clip, songFromMs: r.startMs, songToMs: r.endMs, tiers: step.tiers })
        t += played
      }
    }
  })
  return out
}

export const timelineDurationMs = (segments: Segment[]) =>
  segments.reduce((end, s) => Math.max(end, s.startMs + s.durationMs), 0)
