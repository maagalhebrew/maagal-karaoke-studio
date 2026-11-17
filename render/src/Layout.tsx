// Title-safe layout (inner 90% of the frame), caption box and font loading.
import { useEffect, useState, type ReactNode } from 'react'
import { AbsoluteFill, continueRender, delayRender } from 'remotion'
import '@fontsource-variable/heebo'
import type { CaptionStyle } from './style'

/** Hold the render until Heebo (Hebrew and Latin subsets) is loaded, so no frame uses a fallback font. */
export function useFonts() {
  const [handle] = useState(() => delayRender('Loading Heebo'))
  useEffect(() => {
    Promise.all([
      document.fonts.load('600 64px "Heebo Variable"', 'שלום'),
      document.fonts.load('600 64px "Heebo Variable"', 'shalom'),
    ]).then(() => document.fonts.ready).then(() => continueRender(handle), () => continueRender(handle))
  }, [handle])
}

/** Everything text goes inside the title-safe area: 5% in from every edge. */
export function SafeArea({ children }: { children: ReactNode }) {
  return <AbsoluteFill style={{ inset: '5%', width: '90%', height: '90%' }}>{children}</AbsoluteFill>
}

/** The caption block, placed by verticalPosition (0 top .. 1 bottom), with an optional dark box. */
export function CaptionBlock({ style, children }: { style: CaptionStyle; children: ReactNode }) {
  const p = Math.min(1, Math.max(0, style.verticalPosition))
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, top: `${p * 100}%`, transform: `translateY(-${p * 100}%)`, display: 'flex', justifyContent: 'center' }}>
      <div style={{ background: `rgba(0,0,0,${style.boxOpacity})`, borderRadius: 24, padding: style.boxOpacity > 0 ? '24px 48px' : 0, maxWidth: '100%' }}>
        {children}
      </div>
    </div>
  )
}
