// Read-only hooks for in-browser acceptance tests (local app only).
export interface PlayerEvent { event: string; t: number; audioMs: number; detail?: Record<string, unknown> }

export interface KaraokeDebug {
  audioTimeMs?: () => number
  player?: { audio: HTMLAudioElement; log: PlayerEvent[] }
}

declare global {
  interface Window { karaokeDebug: KaraokeDebug }
}

window.karaokeDebug ??= {}
export const debug = window.karaokeDebug
