// Lesson video: a drill rendered as cards, clips (song audio at the step's speed, pitch kept) and
// "your turn" gaps with the captions held. Never shows artwork or footage from the song itself.
import { Audio, Video } from '@remotion/media'
import { AbsoluteFill, Img, Sequence, staticFile, useCurrentFrame, useVideoConfig } from 'remotion'
import { Captions } from '../../frontend/src/captions/Captions'
import { lessonTimeline, timelineDurationMs, type Segment } from '../../frontend/src/captions/lesson'
import { clipLines, lineIndexAt } from '../../frontend/src/captions/timing'
import type { Song } from '../../frontend/src/types'
import { CaptionBlock, SafeArea, useFonts } from './Layout'
import { captionVars, shownTiers, type Background, type CaptionStyle } from './style'

export const FPS = 30
export const toFrames = (ms: number) => Math.round((ms * FPS) / 1000)

export type LessonProps = { song: Song; drillId: string; style: CaptionStyle; background: Background }

export const lessonFrames = (p: LessonProps) => {
  const drill = p.song.drills.find((d) => d.id === p.drillId)
  return drill ? Math.max(1, toFrames(timelineDurationMs(lessonTimeline(p.song, drill)))) : 1
}

export function Lesson({ song, drillId, style, background }: LessonProps) {
  useFonts()
  const drill = song.drills.find((d) => d.id === drillId)
  if (!drill) throw new Error(`drill ${drillId} not found`)
  return (
    <AbsoluteFill style={{ fontFamily: '"Heebo Variable", Heebo, sans-serif' }}>
      <BackgroundLayer background={background} />
      {lessonTimeline(song, drill).map((seg, i) => {
        const from = toFrames(seg.startMs), to = toFrames(seg.startMs + seg.durationMs)
        return (
          <Sequence key={i} from={from} durationInFrames={Math.max(1, to - from)} name={`${seg.kind} ${seg.step + 1}`}>
            <SegmentView seg={seg} song={song} style={style} steps={drill.steps.length} />
          </Sequence>
        )
      })}
    </AbsoluteFill>
  )
}

function BackgroundLayer({ background }: { background: Background }) {
  if (background.kind === 'color') return <AbsoluteFill style={{ background: background.color }} />
  if (background.kind === 'image') return <AbsoluteFill><Img src={staticFile(background.file)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /></AbsoluteFill>
  return <AbsoluteFill><Video src={staticFile(background.file)} muted loop style={{ width: '100%', height: '100%', objectFit: 'cover' }} /></AbsoluteFill>
}

function Chip({ children, style }: { children: string; style: CaptionStyle }) {
  return (
    <div style={{ position: 'absolute', top: 0, right: 0, fontSize: 30, fontWeight: 600, color: style.textColor, opacity: 0.85,
                  background: 'rgba(0,0,0,0.35)', padding: '8px 18px', borderRadius: 999 }}>
      {children}
    </div>
  )
}

function SegmentView({ seg, song, style, steps }: { seg: Segment; song: Song; style: CaptionStyle; steps: number }) {
  const frame = useCurrentFrame()
  const { fps, durationInFrames } = useVideoConfig()
  const ms = (frame / fps) * 1000

  if (seg.kind === 'card') {
    return (
      <SafeArea>
        <AbsoluteFill style={{ display: 'grid', placeItems: 'center' }}>
          <div style={{ fontSize: 76, fontWeight: 700, color: style.textColor, textAlign: 'center', lineHeight: 1.25, maxWidth: '85%',
                        background: `rgba(0,0,0,${style.boxOpacity})`, padding: '48px 64px', borderRadius: 32 }}>
            {seg.text}
          </div>
        </AbsoluteFill>
      </SafeArea>
    )
  }

  const lines = clipLines(song, seg.clip)
  const vars = captionVars(style)
  const step = `Step ${seg.step + 1}/${steps}`
  if (seg.kind === 'clip') {
    const songMs = seg.songFromMs + ms * seg.speed
    const line = lines[lineIndexAt(lines, songMs)]
    return (
      <>
        {/* preservePitch must be explicit: without it the render measured a 25% pitch drop at 75% speed. */}
        <Audio src={staticFile(`audio/${seg.track}.wav`)} trimBefore={Math.round((seg.songFromMs / 1000) * fps)} playbackRate={seg.speed}
               preservePitch />
        <SafeArea>
          <Chip style={style}>{`${step} · listen ${seg.repeat} · ${Math.round(seg.speed * 100)}%`}</Chip>
          <CaptionBlock style={style}>
            <Captions line={line} timeMs={songMs} tiers={shownTiers(seg.tiers, line)} showNiqqud={style.showNiqqud} language={song.song.language} style={vars} />
          </CaptionBlock>
        </SafeArea>
      </>
    )
  }

  // "Your turn": silence, the clip's captions held, a progress bar for the gap.
  const progress = Math.min(1, frame / Math.max(1, durationInFrames - 1))
  return (
    <SafeArea>
      <Chip style={style}>{`${step} · your turn ${seg.repeat}`}</Chip>
      <CaptionBlock style={style}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 28 }}>
          <div style={{ fontSize: 48, fontWeight: 800, color: style.highlightColor, letterSpacing: '0.04em' }}>Your turn</div>
          {lines.map((l) => <Captions key={l.id} line={l} timeMs={-1} tiers={shownTiers(seg.tiers, l)} showNiqqud={style.showNiqqud} language={song.song.language} style={vars} />)}
          <div style={{ width: 520, height: 10, borderRadius: 99, background: 'rgba(255,255,255,0.2)', overflow: 'hidden' }}>
            <div style={{ width: `${progress * 100}%`, height: '100%', background: style.highlightColor }} />
          </div>
        </div>
      </CaptionBlock>
    </SafeArea>
  )
}
