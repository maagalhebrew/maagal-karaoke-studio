// Trim step for an uploaded file or recording: cut the silence (or the neighbouring songs a recording caught) off
// both ends before the song is processed. The green band is what's kept; the server suggests it and marks every
// stretch of sound it found, so a different one can be picked with one click.
import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/plugins/regions'
import TimelinePlugin from 'wavesurfer.js/plugins/timeline'
import { api } from './api'
import { QualityReport, type AudioUpload, type StagedUpload } from './AudioSource'
import { Icon } from './icons'

const KEEP_COLOR = 'rgba(255,197,61,0.22)'
const SOUND_COLOR = 'rgba(164,166,200,0.12)'
const LISTEN_MS = 4000 // "play the start / end" length
const PAD_BEFORE_MS = 300, PAD_AFTER_MS = 1000 // when a stretch of sound is picked
const clock = (ms: number) => { const s = ms / 1000; return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}` }

interface Props { staged: StagedUpload; onDone: (u: AudioUpload) => void; onCancel: () => void; onError: (m: string) => void }

export function TrimStep({ staged, onDone, onCancel, onError }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const ws = useRef<WaveSurfer | null>(null)
  const keepRegion = useRef<{ setOptions: (o: { start: number; end: number }) => void } | null>(null)
  const [keep, setKeepState] = useState<[number, number]>(staged.suggest)
  const [busy, setBusy] = useState(false)
  const total = staged.durationMs

  const setKeep = (k: [number, number]) => {
    const r: [number, number] = [Math.max(0, Math.round(k[0])), Math.min(total, Math.round(k[1]))]
    setKeepState(r)
    keepRegion.current?.setOptions({ start: r[0] / 1000, end: r[1] / 1000 })
  }

  useEffect(() => {
    const regions = RegionsPlugin.create()
    const w = WaveSurfer.create({
      container: box.current!, height: 110, url: api.uploadUrl(staged.upload), peaks: [staged.peaks], duration: total / 1000,
      waveColor: '#6B72B8', progressColor: '#FFC53D', cursorColor: '#F4EFDD', cursorWidth: 1, normalize: true,
      plugins: [regions, TimelinePlugin.create({ height: 16, style: { color: '#A4A6C8', fontSize: '11px' } })],
    })
    ws.current = w
    w.once('ready', () => {
      staged.segments.forEach(([s, e], i) => {
        const r = regions.addRegion({ start: s / 1000, end: e / 1000, color: SOUND_COLOR, drag: false, resize: false, content: String(i + 1) })
        if (r.element) r.element.style.pointerEvents = 'none'
      })
      const k = regions.addRegion({ id: 'keep', start: staged.suggest[0] / 1000, end: staged.suggest[1] / 1000, color: KEEP_COLOR,
                                    drag: true, resize: true, minLength: 1 })
      keepRegion.current = k
      k.on('update-end', () => setKeepState([Math.round(k.start * 1000), Math.round(k.end * 1000)]))
    })
    return () => w.destroy()
  }, [staged, total])

  const listen = (from: number, to: number) => ws.current?.play(Math.max(0, from) / 1000, Math.min(total, to) / 1000)
  const pick = ([s, e]: [number, number]) => setKeep([s - PAD_BEFORE_MS, e + PAD_AFTER_MS])
  const finish = async (trim: boolean) => {
    ws.current?.pause()
    if (!trim) return onDone({ upload: staged.upload, seconds: staged.seconds, from: staged.from, quality: staged.quality })
    setBusy(true); onError('')
    try {
      const r = await api.trimAudio(staged.upload, keep[0], keep[1])
      onDone({ ...r, from: staged.from, quality: staged.quality })
    } catch (e) { onError((e as Error).message) } finally { setBusy(false) }
  }

  const cutStart = keep[0], cutEnd = total - keep[1]
  return (
    <div className="trim-step" data-testid="trim-step">
      {staged.quality && <QualityReport q={staged.quality} from={staged.from} />}
      <p className="trim-head"><b>Trim the ends</b>
        <span className="hint"> Drag the bright band's edges (or the band) so it holds just the song. Faint stretches are where sound was found.</span>
      </p>
      <div ref={box} className="trim-wave" />
      <p className="trim-readout" data-testid="trim-readout">
        Keep <b>{clock(keep[0])} – {clock(keep[1])}</b> ({clock(keep[1] - keep[0])}) · cut {(cutStart / 1000).toFixed(1)} s at the start,
        {' '}{(cutEnd / 1000).toFixed(1)} s at the end
      </p>
      {staged.segments.length > 1 && (
        <p className="trim-segments">Sounds found:{' '}
          {staged.segments.map((g, i) => (
            <button key={i} className="ghost" onClick={() => pick(g)} title="Keep this stretch">
              {i + 1} · {clock(g[0])}–{clock(g[1])} ({Math.round((g[1] - g[0]) / 1000)} s)
            </button>
          ))}
        </p>
      )}
      <p className="trim-actions">
        <button className="btn-icon" onClick={() => listen(keep[0], keep[0] + LISTEN_MS)}><Icon name="play" /> Play the start</button>
        <button className="btn-icon" onClick={() => listen(keep[1] - LISTEN_MS, keep[1])}><Icon name="play" /> Play the end</button>
        <button className="ghost" onClick={() => setKeep(staged.suggest)}>Reset</button>
        <span className="spacer" />
        <button className="ghost" onClick={onCancel} disabled={busy}>Choose other audio</button>
        <button onClick={() => finish(false)} disabled={busy}>Keep it all</button>
        <button className="primary btn-icon" onClick={() => finish(true)} disabled={busy}>{busy ? 'Cutting…' : <><Icon name="clip" /> Trim and use</>}</button>
      </p>
    </div>
  )
}
