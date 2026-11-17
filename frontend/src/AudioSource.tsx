// Add a song without downloading: choose an audio file, or record the sound the computer is playing.
// Recording uses the browser's screen-share picker (getDisplayMedia) with audio; only the audio track is kept, as
// the raw samples the browser hands over, saved as WAV: nothing is compressed on the way.
// Either way the audio goes to the server once, which returns an upload id, where the sound and silences are (for
// the trim step), and what it measured (for the report).
import { useEffect, useRef, useState } from 'react'
import { api, type UploadAnalysis } from './api'
import { Icon } from './icons'

export interface AudioUpload { upload: string; seconds: number; from: string; quality?: UploadAnalysis['quality'] }
export type StagedUpload = AudioUpload & UploadAnalysis

const ACCEPT = 'audio/*,.m4a,.mp3,.wav,.mp4,.webm,.ogg,.opus,.flac,.aac,.mov,.mkv'
const QUIET_WARN_S = 6 // no sound heard for this long while recording: remind to press play
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

async function send(blob: Blob, name: string, from: string): Promise<StagedUpload> {
  return { ...(await api.uploadAudio(blob, name)), from }
}

export function FilePick({ onReady, onError }: { onReady: (u: StagedUpload, fileName: string) => void; onError: (m: string) => void }) {
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const take = async (file: File | undefined) => {
    if (!file) return
    setBusy(true); onError('')
    try { onReady(await send(file, file.name, file.name), file.name) } catch (e) { onError((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <label className={`dropzone${over ? ' over' : ''}`} data-testid="file-pick"
           onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
           onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files[0]) }}>
      <input type="file" accept={ACCEPT} disabled={busy} onChange={(e) => take(e.target.files?.[0])} />
      <span>{busy ? 'Uploading…' : 'Choose an audio file, or drop it here'}</span>
      <span className="hint">MP3, M4A, WAV, FLAC, OGG, WebM… A video file works too: only its sound is used. A file from the artist or a purchased download beats any recording.</span>
    </label>
  )
}

// Hands each block of samples to the page. Lives in a string because a worklet loads from a URL of its own.
const CAPTURE_WORKLET = `
class Capture extends AudioWorkletProcessor {
  constructor() { super(); this.left = new Float32Array(4096); this.right = new Float32Array(4096); this.n = 0 }
  process(inputs) {
    const input = inputs[0]
    if (!input.length) return true
    const l = input[0], r = input[1] ?? input[0]
    for (let i = 0; i < l.length; i++) {
      this.left[this.n] = l[i]; this.right[this.n] = r[i]
      if (++this.n === this.left.length) {
        this.port.postMessage([this.left, this.right], [this.left.buffer, this.right.buffer])
        this.left = new Float32Array(4096); this.right = new Float32Array(4096); this.n = 0
      }
    }
    return true
  }
}
registerProcessor('capture', Capture)
`

/** Samples as 16-bit stereo, ready for a WAV file. */
function toPcm16(left: Float32Array, right: Float32Array): Int16Array {
  const out = new Int16Array(left.length * 2)
  const s16 = (x: number) => Math.round(Math.max(-1, Math.min(1, x)) * 32767)
  for (let i = 0; i < left.length; i++) { out[i * 2] = s16(left[i]); out[i * 2 + 1] = s16(right[i]) }
  return out
}

function wavFile(chunks: Int16Array[], rate: number): Blob {
  const bytes = chunks.reduce((a, c) => a + c.byteLength, 0)
  const h = new DataView(new ArrayBuffer(44))
  const text = (at: number, s: string) => [...s].forEach((c, i) => h.setUint8(at + i, c.charCodeAt(0)))
  text(0, 'RIFF'); h.setUint32(4, 36 + bytes, true); text(8, 'WAVEfmt ')
  h.setUint32(16, 16, true); h.setUint16(20, 1, true); h.setUint16(22, 2, true) // plain PCM, two channels
  h.setUint32(24, rate, true); h.setUint32(28, rate * 4, true); h.setUint16(32, 4, true); h.setUint16(34, 16, true)
  text(36, 'data'); h.setUint32(40, bytes, true)
  return new Blob([h.buffer, ...(chunks as BlobPart[])], { type: 'audio/wav' })
}

export function Recorder({ onReady, onError }: { onReady: (u: StagedUpload) => void; onError: (m: string) => void }) {
  const [state, setState] = useState<'idle' | 'recording' | 'saving'>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [level, setLevel] = useState(0)
  const [quietFor, setQuietFor] = useState(0)
  const stop = useRef<() => void>(() => {})

  useEffect(() => () => stop.current(), []) // leaving the page ends the capture

  const begin = async () => {
    onError('')
    let stream: MediaStream
    try {
      // Chrome-only options (not in TypeScript's types yet): keep playing the sound to the speakers, offer
      // "share system audio", leave this tab out of the list.
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: true, // Chrome needs video in the request; it is never recorded
        audio: { channelCount: 2, echoCancellation: false, noiseSuppression: false, autoGainControl: false, suppressLocalAudioPlayback: false },
        systemAudio: 'include', selfBrowserSurface: 'exclude',
      } as DisplayMediaStreamOptions)
    } catch {
      return // the picker was cancelled
    }
    const audio = stream.getAudioTracks()
    if (!audio.length) {
      stream.getTracks().forEach((t) => t.stop())
      onError('No sound was shared. Try again and switch on “Also share tab audio” (a tab) or “Also share system audio” (Entire screen).')
      return
    }

    const rate = audio[0].getSettings().sampleRate
    const ctx = new AudioContext({ latencyHint: 'playback', ...(rate ? { sampleRate: rate } : {}) })
    const chunks: Int16Array[] = []
    let capture: AudioWorkletNode
    const source = ctx.createMediaStreamSource(new MediaStream(audio))
    try {
      const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: 'text/javascript' }))
      await ctx.audioWorklet.addModule(url)
      URL.revokeObjectURL(url)
      capture = new AudioWorkletNode(ctx, 'capture', { numberOfOutputs: 0, channelCount: 2, channelCountMode: 'explicit' })
      await ctx.resume()
    } catch (e) {
      stream.getTracks().forEach((t) => t.stop())
      void ctx.close()
      onError(`The recorder couldn't start: ${(e as Error).message}`)
      return
    }
    capture.port.onmessage = (e: MessageEvent<[Float32Array, Float32Array]>) => chunks.push(toPcm16(e.data[0], e.data[1]))
    source.connect(capture)

    // Level meter, so it's obvious whether sound is actually arriving.
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 2048
    source.connect(analyser)
    const buf = new Float32Array(analyser.fftSize)
    const t0 = performance.now()
    let lastSound = t0, raf = 0
    const tick = () => {
      analyser.getFloatTimeDomainData(buf)
      const rms = Math.sqrt(buf.reduce((a, x) => a + x * x, 0) / buf.length)
      const now = performance.now()
      if (rms > 0.003) lastSound = now
      setLevel(Math.min(1, rms * 4))
      setElapsed((now - t0) / 1000)
      setQuietFor((now - lastSound) / 1000)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)

    const save = async () => {
      setState('saving')
      try {
        if (!chunks.length) throw new Error('Nothing was recorded.')
        onReady(await send(wavFile(chunks, ctx.sampleRate), 'recording.wav', 'recording'))
      } catch (e) {
        onError((e as Error).message)
      } finally {
        void ctx.close()
        setState('idle'); setLevel(0); setElapsed(0); setQuietFor(0)
      }
    }
    let ended = false
    const finish = () => {
      if (ended) return
      ended = true
      stop.current = () => {}
      cancelAnimationFrame(raf)
      source.disconnect()
      stream.getTracks().forEach((t) => t.stop())
      void save()
    }
    stop.current = finish
    audio[0].addEventListener('ended', finish) // "Stop sharing" in Chrome's bar
    setState('recording')
  }

  return (
    <div className="recorder" data-testid="recorder" data-state={state}>
      {state === 'idle' && <>
        <div className="rec-before" data-testid="rec-checklist">
          <h3>On YouTube, before you record</h3>
          <ul>
            <li>Volume slider at 100%</li>
            <li>Stable volume off (in the player's settings)</li>
            <li>Quality set to the highest offered</li>
            <li>Right-click the video, then Stats for nerds: the Codecs line should say opus (251) or mp4a (140). 249, 250 or 139 are low-quality streams</li>
            <li>No ad playing when you start</li>
          </ul>
        </div>
        <button className="primary btn-icon" onClick={begin}><Icon name="record" /> Record computer sound</button>
        <ol className="hint recorder-steps">
          <li>Open the song in another tab (or in any app) and set it at the beginning.</li>
          <li>Click <b>Record</b>, choose that tab (for an app: <b>Entire screen</b>), switch on <b>share audio</b>, click Share.</li>
          <li>Press play. Click <b>Stop</b> here when the song ends. Anything else that plays (ads, notification sounds) is recorded too.</li>
        </ol>
      </>}
      {state === 'recording' && <>
        <button className="rec-stop btn-icon" onClick={() => stop.current()}><Icon name="stop" /> Stop</button>
        <span className="rec-dot" aria-hidden><Icon name="record" size={14} /></span>
        <span className="rec-time">{mmss(elapsed)}</span>
        <span className="rec-meter" aria-label="Sound level"><i style={{ width: `${Math.round(level * 100)}%` }} /></span>
        {quietFor > QUIET_WARN_S && <span className="error">No sound coming in: press play on the song (or share audio was left off).</span>}
      </>}
      {state === 'saving' && <span>Saving the recording…</span>}
    </div>
  )
}

// --- what came in ----------------------------------------------------------------------------------------------
const QUIET_LUFS = -17, CLIP_PEAK_DB = -0.1, LOW_STREAM_KHZ = 15.5

/** One verdict per measurement: green unless there is something to act on. */
export function QualityReport({ q, from }: { q: NonNullable<UploadAnalysis['quality']>; from: string }) {
  const recording = from === 'recording'
  const rows: [string, string, string, boolean][] = [
    ['Level', q.lufs === null ? 'unknown' : `${q.lufs.toFixed(1)} LUFS`,
      q.lufs !== null && q.lufs < QUIET_LUFS ? (recording ? 'Quiet: check the slider is at 100% and Stable volume is off' : 'Quiet for a song') : 'Good', q.lufs !== null && q.lufs < QUIET_LUFS],
    ['Peak', q.truePeakDb === null ? 'unknown' : `${q.truePeakDb.toFixed(1)} dB`,
      q.truePeakDb !== null && q.truePeakDb > CLIP_PEAK_DB ? 'Over the limit, in the song itself or on the way here' : 'Good', q.truePeakDb !== null && q.truePeakDb > CLIP_PEAK_DB],
    ['Clipping', q.clipped ? `${q.clipped.toLocaleString()} samples` : 'None', q.clipped ? 'Some peaks were cut off' : 'Good', q.clipped > 0],
    ['Stereo', q.stereo ? 'Yes' : 'No', q.stereo ? 'Good' : 'Came in as mono', !q.stereo],
    ['Treble reaches', `${q.topKHz.toFixed(1)} kHz`, q.topKHz < LOW_STREAM_KHZ ? (recording ? 'Low-quality stream: check the Codecs line' : 'A low-quality source') : 'Good', q.topKHz < LOW_STREAM_KHZ],
  ]
  return (
    <div className="quality" data-testid="quality-report">
      <h3>{recording ? 'What the recording captured' : 'What the file contains'}</h3>
      <dl>{rows.map(([name, value, verdict, bad]) => (
        <div key={name} className={bad ? 'bad' : ''}><dt>{name}</dt><dd><b>{value}</b> {verdict}</dd></div>
      ))}</dl>
    </div>
  )
}
