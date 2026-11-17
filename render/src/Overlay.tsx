// Caption overlay for DaVinci Resolve: captions only, on the song's own timeline, transparent background.
import { useCurrentFrame, useVideoConfig } from 'remotion'
import { Captions, type Tier } from '../../frontend/src/captions/Captions'
import type { Line, Song } from '../../frontend/src/types'
import { CaptionBlock, SafeArea, useFonts } from './Layout'
import { captionVars, shownTiers, type CaptionStyle } from './style'

export const LEAD_MS = 300 // a line appears this long before its first word...
export const TAIL_MS = 500 // ...and stays this long after its last word (same windows as the SRT cues)

export type OverlayProps = { song: Song; fromMs: number; toMs: number; style: CaptionStyle; tiers: Tier[] }

/** The line on screen at song time t: the last line whose display window contains t. */
export function visibleLine(lines: Line[], t: number): Line | null {
  let found: Line | null = null
  for (const l of lines) {
    if (l.words[0].startMs - LEAD_MS <= t && t <= l.words.at(-1)!.endMs + TAIL_MS) found = l
  }
  return found
}

export function Overlay({ song, fromMs, style, tiers }: OverlayProps) {
  useFonts()
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const t = fromMs + (frame / fps) * 1000
  const line = visibleLine(song.lines, t)
  // No background anywhere: the frame stays transparent except for the captions.
  if (!line) return null
  return (
    <SafeArea>
      <CaptionBlock style={style}>
        <Captions line={line} timeMs={t} tiers={shownTiers(tiers, line)} showNiqqud={style.showNiqqud} language={song.song.language} style={captionVars(style)} />
      </CaptionBlock>
    </SafeArea>
  )
}
