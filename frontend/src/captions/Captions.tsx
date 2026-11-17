// Two-line caption block (lyrics, English). Used by the editor preview and the Remotion renderer,
// so it takes everything as props and reads no app state.
import type { CSSProperties } from 'react'
import type { Language, Line, Tier } from '../types'
import { progress, wordText } from './timing'
import './captions.css'

export type { Tier }

export interface CaptionsProps {
  line: Line | null
  timeMs: number
  showNiqqud?: boolean
  tiers?: Tier[]
  language?: Language
  style?: CSSProperties
}

/** Wipe: highlighted up to p (0..1), in the reading direction. */
function wipe(p: number, rtl: boolean): CSSProperties | undefined {
  if (p <= 0) return undefined
  if (p >= 1) return { color: 'var(--cap-highlight)' }
  const pct = `${(p * 100).toFixed(1)}%`
  return {
    backgroundImage: `linear-gradient(to ${rtl ? 'left' : 'right'}, var(--cap-highlight) ${pct}, var(--cap-text) ${pct})`,
    WebkitBackgroundClip: 'text',
    backgroundClip: 'text',
    color: 'transparent',
  }
}

export function Captions({ line, timeMs, showNiqqud = true, tiers = ['lyrics', 'en'], language = 'he', style }: CaptionsProps) {
  if (!line) return <div className="captions" style={style} />
  const active = line.words.find((w) => w.startMs <= timeMs && timeMs < w.endMs)
  const rtl = language === 'he'
  return (
    <div className="captions" style={style} data-line={line.id} data-active-word={active?.id ?? ''}>
      {tiers.includes('lyrics') && (
        <div className="cap-tier cap-lyrics" dir={rtl ? 'rtl' : 'ltr'} lang={language}>
          {line.words.map((w) => (
            <span key={w.id} className="cap-word" style={wipe(progress(w, timeMs), rtl)}>
              {wordText(w, showNiqqud)}
            </span>
          ))}
        </div>
      )}
      {tiers.includes('en') && (
        <div className="cap-tier cap-en" dir="ltr">
          {line.english || ' '}
        </div>
      )}
    </div>
  )
}
