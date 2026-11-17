// Style preset (data/presets.json) as the compositions receive it. Sizes are for a 1080-pixel-high frame.
import type { CSSProperties } from 'react'

export interface CaptionStyle {
  heSizePx: number // the lyrics line (named when it was always Hebrew)
  enScale: number // relative to the lyrics (~0.6)
  textColor: string
  highlightColor: string
  boxOpacity: number // 0 = no box behind the captions, 1 = solid black
  verticalPosition: number // 0 = top of the title-safe area, 0.5 = middle, 1 = bottom
  showNiqqud: boolean
}

export type Background =
  | { kind: 'color'; color: string }
  | { kind: 'image'; file: string } // relative to the render's public dir
  | { kind: 'video'; file: string }

export const DEFAULT_STYLE: CaptionStyle = {
  heSizePx: 84, enScale: 0.6, textColor: '#f5f5f4', highlightColor: '#facc15',
  boxOpacity: 0.45, verticalPosition: 0.85, showNiqqud: false,
}

/** In a video an empty tier is dropped (the editor keeps the row so its layout doesn't jump). */
export const shownTiers = <T extends string>(tiers: T[], line: { english: string } | undefined) =>
  tiers.filter((t) => t !== 'en' || !!line?.english.trim())

export const captionVars =(s: CaptionStyle) => ({
  '--cap-size': `${s.heSizePx}px`,
  '--cap-text': s.textColor,
  '--cap-highlight': s.highlightColor,
  '--cap-en-scale': String(s.enScale),
}) as CSSProperties
