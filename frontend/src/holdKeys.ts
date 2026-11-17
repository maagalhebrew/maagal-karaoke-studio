// Holding ? shows the keys: every button's letter in the Studio editor, the key list in Practice. A quick tap can
// do something else (the keyboard map in the Studio editor).
import { useEffect, useRef } from 'react'

const HOLD_MS = 250

export function useHoldForKeys(onTap?: () => void, enabled = true) {
  const tap = useRef(onTap)
  tap.current = onTap
  useEffect(() => {
    if (!enabled) return
    let timer: number | undefined, down = false
    const typing = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      return el.tagName === 'TEXTAREA' || el.isContentEditable
        || (el.tagName === 'INPUT' && !['checkbox', 'radio', 'range'].includes((el as HTMLInputElement).type))
    }
    const press = (e: KeyboardEvent) => {
      if (e.key !== '?' || e.repeat || typing(e)) return
      down = true
      timer = window.setTimeout(() => { timer = undefined; document.body.classList.add('show-keys') }, HOLD_MS)
    }
    const release = (e: KeyboardEvent) => {
      if (!down || !['?', '/', 'Shift'].includes(e.key)) return
      down = false
      if (timer !== undefined) { window.clearTimeout(timer); timer = undefined; tap.current?.() }
      document.body.classList.remove('show-keys')
    }
    window.addEventListener('keydown', press)
    window.addEventListener('keyup', release)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('keydown', press)
      window.removeEventListener('keyup', release)
      document.body.classList.remove('show-keys')
    }
  }, [enabled])
}
