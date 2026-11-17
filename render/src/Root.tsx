import { Composition } from 'remotion'
import type { Song } from '../../frontend/src/types'
import { FPS, Lesson, lessonFrames, toFrames, type LessonProps } from './Lesson'
import { Overlay, type OverlayProps } from './Overlay'
import { DEFAULT_STYLE } from './style'

// Only used when previewing in Remotion Studio; `karaoke export` always passes real props.
const SAMPLE: Song = {
  schema: 2,
  song: { id: 'sample', title: 'Sample', artist: '', language: 'he', permissionId: null, durationMs: 4000,
          audio: { original: 'audio/original.wav', vocals: 'audio/vocals.wav', instrumental: 'audio/instrumental.wav' } },
  lines: [{ id: 'L1', english: 'hello', words: [{ id: 'L1W1', plain: 'שָׁלוֹם', startMs: 500, endMs: 1500, confidence: 1, flags: [] }] }],
  sections: [], clips: [{ id: 'C1', name: 'sample', fromWord: 'L1W1', toWord: 'L1W1', padBeforeMs: 300, padAfterMs: 300 }],
  drills: [{ id: 'D1', name: 'sample', steps: [{ type: 'card', text: 'Shalom means hello', durationMs: 2000 }] }],
}

export function Root() {
  return (
    <>
      <Composition id="Lesson" component={Lesson} fps={FPS} width={1920} height={1080} durationInFrames={1}
                   defaultProps={{ song: SAMPLE, drillId: 'D1', style: DEFAULT_STYLE, background: { kind: 'color', color: '#0b1020' } } satisfies LessonProps}
                   calculateMetadata={({ props }) => ({ durationInFrames: lessonFrames(props) })} />
      <Composition id="Overlay" component={Overlay} fps={FPS} width={1920} height={1080} durationInFrames={1}
                   defaultProps={{ song: SAMPLE, fromMs: 0, toMs: 4000, style: DEFAULT_STYLE, tiers: ['lyrics', 'en'] } satisfies OverlayProps}
                   calculateMetadata={({ props }) => ({ durationInFrames: Math.max(1, toFrames(props.toMs - props.fromMs)) })} />
    </>
  )
}
