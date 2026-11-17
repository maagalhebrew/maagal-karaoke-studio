// Settings remembered per browser (view toggles, loop options). Storage can be unavailable (private window,
// blocked site data), so every read and write falls back to the default.
import { useState } from 'react'

const KEY = (k: string) => `karaoke.${k}`

function read(key: string): string | null {
  try { return localStorage.getItem(KEY(key)) } catch { return null }
}
function write(key: string, value: string) {
  try { localStorage.setItem(KEY(key), value) } catch { /* not remembered */ }
}

export function usePref(key: string, initial: boolean) {
  const [value, setValue] = useState(() => { const v = read(key); return v === null ? initial : v === '1' })
  const set = (v: boolean) => { setValue(v); write(key, v ? '1' : '0') }
  return [value, set] as const
}

export function useNumberPref(key: string, initial: number) {
  const [value, setValue] = useState(() => { const v = Number(read(key) ?? NaN); return Number.isFinite(v) ? v : initial })
  const set = (v: number) => { setValue(v); write(key, String(v)) }
  return [value, set] as const
}
