// Practice log: how long a song plays (Studio editor or Practice mode) and how many passes each line loop makes.
// Kept in memory and sent every 30 s, and when the page is hidden, closed or left; sendBeacon still delivers
// while the tab closes. A crash loses at most the last 30 s. Ids and numbers only, never lyric text.
import { useCallback, useEffect, useRef } from 'react'

const FLUSH_MS = 30_000
const MAX_BATCH_S = 900 // the server's limit per report; anything above waits for the next one
export const LINE_ID = /^L\d+$/

export function usePracticeLog(songId: string | undefined, source: 'studio' | 'practice', playing: boolean) {
  const ms = useRef(0) // played but not yet sent
  const since = useRef<number | null>(null) // playing since (performance.now), while playing
  const loops = useRef<Record<string, number>>({})
  const id = useRef(songId)

  const flush = useCallback((closing = false) => {
    const song = id.current
    if (!song) return
    if (since.current !== null) { const now = performance.now(); ms.current += now - since.current; since.current = now }
    const seconds = Math.min(MAX_BATCH_S, Math.floor(ms.current / 1000))
    const batch = loops.current
    if (!seconds && !Object.keys(batch).length) return
    ms.current -= seconds * 1000
    loops.current = {}
    const url = `/api/songs/${encodeURIComponent(song)}/practice`
    const body = JSON.stringify({ source, seconds, loops: batch })
    if (closing && navigator.sendBeacon?.(url, new Blob([body], { type: 'application/json' }))) return
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {})
  }, [source])

  // A different song: send what the previous one gathered first.
  useEffect(() => {
    if (id.current !== songId) { flush(true); ms.current = 0; loops.current = {} }
    id.current = songId
  }, [songId, flush])

  // The clock runs only while audio plays (a loop's pause between passes doesn't count).
  useEffect(() => {
    if (playing) { since.current = performance.now(); return }
    if (since.current !== null) { ms.current += performance.now() - since.current; since.current = null }
  }, [playing])

  useEffect(() => {
    const t = window.setInterval(() => flush(), FLUSH_MS)
    const hidden = () => { if (document.visibilityState === 'hidden') flush(true) }
    const leaving = () => flush(true)
    document.addEventListener('visibilitychange', hidden)
    window.addEventListener('pagehide', leaving)
    return () => {
      window.clearInterval(t)
      document.removeEventListener('visibilitychange', hidden)
      window.removeEventListener('pagehide', leaving)
      flush(true) // closing the player / leaving the Studio editor
    }
  }, [flush])

  /** One completed pass of a loop; only line loops are counted. */
  return useCallback((loopId: string) => {
    if (LINE_ID.test(loopId)) loops.current[loopId] = (loops.current[loopId] ?? 0) + 1
  }, [])
}

/** "today", "yesterday", "3 days ago" for a local yyyy-mm-dd. */
export function daysAgo(day: string): string {
  const today = new Date().toLocaleDateString('en-CA') // yyyy-mm-dd, local
  const n = Math.round((Date.parse(today) - Date.parse(day)) / 86_400_000)
  return n <= 0 ? 'today' : n === 1 ? 'yesterday' : n < 14 ? `${n} days ago` : n < 60 ? `${Math.round(n / 7)} weeks ago` : day
}

/** 45 s, 12 min, 1 h 05 min. */
export function playedFor(seconds: number): string {
  if (seconds < 60) return `${seconds} s`
  const m = Math.round(seconds / 60)
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`
}

// --- line ratings (self-assessment): keys 1 / 2 / 3 in the Studio editor and Practice mode ----------------
export const RATING_LABELS = ["don't know", 'shaky', 'know it'] as const
export const RATING_ICONS = ['✗', '~', '✓'] as const

/** The rating a key press sets: the same rating again clears it. */
export const nextRating = (current: number | undefined, pressed: number): number | null => (current === pressed ? null : pressed)

/** Which line a rating key means: the looped line while a line loop runs (the playhead may sit in its lead-in),
 *  otherwise the line at the playhead. */
export function lineToRate(lines: { id: string }[], loopId: string | null | undefined, playheadIndex: number): string | undefined {
  if (loopId && LINE_ID.test(loopId) && lines.some((l) => l.id === loopId)) return loopId
  return lines[playheadIndex]?.id
}

/** "review today", "review in 3 days", "overdue 2 days" for a local yyyy-mm-dd due date. */
export function dueText(day: string): string {
  const n = Math.round((Date.parse(day) - Date.parse(today())) / 86_400_000)
  return n < 0 ? `overdue ${-n} day${n === -1 ? '' : 's'}` : n === 0 ? 'review today' : n === 1 ? 'review tomorrow' : `review in ${n} days`
}
export const today = () => new Date().toLocaleDateString('en-CA') // yyyy-mm-dd, local
