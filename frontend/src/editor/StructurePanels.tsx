// Sidebar panels: sections, clips, drills (the drill builder).
import { useState, type CSSProperties } from 'react'
import { clipRange } from '../captions/timing'
import { Icon } from '../icons'
import { tracksIn, type Clip, ClipStep, Drill, DrillStep, Section, SectionKind, Song, Tier, Track } from '../types'
import { SECTION_PALETTE, sectionColor } from './Timeline'
import { SECTION_KINDS, drillsUsing, nextId, sectionLineCount, sectionRange } from './structure'

type Edit = (mutate: (s: Song) => void) => void
const secs = (ms: number) => (ms / 1000).toFixed(2)

interface SectionControls {
  playing: boolean
  loopingId: string | null
  onPlay: (s: Section) => void
  onLoop: (s: Section) => void // on: loop from the section start; off: keep playing, stop looping
  onPause: () => void
  onClip: (s: Section) => void
  onGoTo: (s: Section) => void
}

/** One quiet row per section, filling as it plays. Its buttons show on hover; its settings open from the pencil. */
export function SectionsPanel({ song, edit, timeMs, controls: c }: { song: Song; edit: Edit; timeMs: number; controls: SectionControls }) {
  const [editing, setEditing] = useState<string | null>(null) // section whose settings are open
  const [picking, setPicking] = useState<string | null>(null) // section whose colour picker is open
  const setColor = (id: string, color: string | undefined) => {
    edit((x) => { const sec = x.sections.find((y) => y.id === id)!; if (color) sec.color = color; else delete sec.color })
    setPicking(null)
  }
  return (
    <div className="panel rail" data-testid="sections-panel">
      <ul className="items">
        {song.sections.map((s) => {
          const r = sectionRange(song, s)
          const playingHere = c.playing && timeMs >= r.startMs && timeMs < r.endMs
          const here = timeMs >= r.startMs && timeMs < r.endMs
          const done = Math.max(0, Math.min(1, (timeMs - r.startMs) / Math.max(1, r.endMs - r.startMs)))
          return (
            <li key={s.id} className="item section" data-section={s.id}>
              <div className={`rail-row${here ? ' here' : ''}`} style={{ '--c': sectionColor(s) } as CSSProperties}>
                {here && <i className="rail-fill" style={{ width: `${done * 100}%` }} />}
                <i className="rail-bar" />
                <button className="rail-name" onClick={() => c.onGoTo(s)} title="Go to this section">
                  <span className="rail-label" dir="auto">{s.label}</span>
                  <span className="meta">{sectionLineCount(song.lines, s)}</span>
                </button>
                <span className="meta rail-length">{Math.round((r.endMs - r.startMs) / 1000)} s</span>
                <span className="rail-actions" role="group" aria-label={`${s.label} playback`}>
                  {playingHere
                    ? <button onClick={c.onPause} aria-label={`Pause ${s.label}`} title="Pause"><Icon name="pause" size={16} /></button>
                    : <button onClick={() => c.onPlay(s)} aria-label={`Play ${s.label}`} title="Play this section once"><Icon name="play" size={16} /></button>}
                  <button className={c.loopingId === s.id ? 'on' : ''} aria-pressed={c.loopingId === s.id} aria-label={`Loop ${s.label}`}
                          onClick={() => c.onLoop(s)} title="Loop this section until you turn it off"><Icon name="loop" size={16} /></button>
                  <button aria-expanded={editing === s.id} aria-label={`Edit ${s.label}`} title="Name, kind, colour, clip, delete"
                          onClick={() => setEditing(editing === s.id ? null : s.id)}><Icon name="edit" size={16} /></button>
                </span>
              </div>
              {editing === s.id && (
                <div className="rail-edit">
                  <div className="rail-edit-row">
                    <input value={s.label} aria-label="Section label"
                           onChange={(e) => edit((x) => { x.sections.find((y) => y.id === s.id)!.label = e.target.value })} />
                    <select value={s.kind} aria-label="Section kind"
                            onChange={(e) => edit((x) => { x.sections.find((y) => y.id === s.id)!.kind = e.target.value as SectionKind })}>
                      {SECTION_KINDS.map((k) => <option key={k}>{k}</option>)}
                    </select>
                  </div>
                  <span className="meta">Lines {s.fromLine} to {s.toLine}, {secs(r.endMs - r.startMs)} s</span>
                  <div className="rail-edit-row">
                    <button className="btn-icon" aria-expanded={picking === s.id} onClick={() => setPicking(picking === s.id ? null : s.id)}>
                      <i className="swatch" style={{ background: sectionColor(s) }} /> Colour
                    </button>
                    <button className="btn-icon" onClick={() => c.onClip(s)} title="Make a clip of this section (for drills)"><Icon name="clip" size={16} /> Make clip</button>
                    <span className="tspacer" />
                    <button className="danger" aria-label={`Delete ${s.label}`} title="Delete this section (the lyrics stay)"
                            onClick={() => { if (window.confirm(`Delete the section "${s.label}"? The lyrics and timing stay.`))
                              edit((x) => { x.sections = x.sections.filter((y) => y.id !== s.id) }) }}>Delete</button>
                  </div>
                  {picking === s.id && (
                    <div className="color-picker" role="group" aria-label={`Colours for ${s.label}`}>
                      {SECTION_PALETTE.map((hue) => (
                        <span key={hue.name} className="color-row">
                          {hue.shades.map((hex) => (
                            <button key={hex} className={`color-chip${s.color === hex ? ' on' : ''}`} style={{ background: hex }}
                                    aria-label={`${hue.name} ${hex}`} onClick={() => setColor(s.id, hex)} />
                          ))}
                        </span>
                      ))}
                      <button className="ghost" onClick={() => setColor(s.id, undefined)} title="Back to the colour for its kind">by kind</button>
                    </div>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      <p className="hint rail-hint">To add a section, select lines (click a line number, Shift-click another) or drag on the timeline, then choose Make section.</p>
    </div>
  )
}

export function ClipsPanel({ song, edit, onPlay }: { song: Song; edit: Edit; onPlay: (c: Clip) => void }) {
  const update = (id: string, patch: Partial<Clip>) => edit((x) => { Object.assign(x.clips.find((c) => c.id === id)!, patch) })
  return (
    <div className="panel" data-testid="clips-panel">
      <h2>Clips</h2>
      <p className="hint">Select words, then “Make clip”. A clip can be a single word.</p>
      <ul className="items">
        {song.clips.map((c) => {
          const r = clipRange(song, c)
          const used = drillsUsing(song, c.id)
          return (
            <li key={c.id} className="item clip" data-clip={c.id}>
              <input value={c.name} aria-label="Clip name" onChange={(e) => update(c.id, { name: e.target.value })} />
              <span className="meta">{c.id} · {c.fromWord}–{c.toWord} · {secs(r.endMs - r.startMs)} s</span>
              <label className="meta">pad <input type="number" min={0} step={50} value={c.padBeforeMs} aria-label="Pad before ms"
                       onChange={(e) => update(c.id, { padBeforeMs: Math.max(0, +e.target.value) })} />
                /<input type="number" min={0} step={50} value={c.padAfterMs} aria-label="Pad after ms"
                        onChange={(e) => update(c.id, { padAfterMs: Math.max(0, +e.target.value) })} /> ms</label>
              <button onClick={() => onPlay(c)} aria-label={`Play ${c.name || c.id}`}><Icon name="play" size={16} /></button>
              <button className="ghost" disabled={used.length > 0} title={used.length ? `Used in ${used.map((d) => d.name).join(', ')}` : 'Delete'}
                      aria-label={`Delete ${c.name || c.id}`}
                      onClick={() => edit((x) => { x.clips = x.clips.filter((y) => y.id !== c.id) })}><Icon name="close" size={16} /></button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

const TIERS: Tier[] = ['lyrics', 'en']
const TIER_LABELS: Record<Tier, string> = { lyrics: 'lyrics', en: 'English' }
const SPEEDS = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1]

export function DrillsPanel({ song, edit, onPlay }: { song: Song; edit: Edit; onPlay: (d: Drill) => void }) {
  const updateDrill = (id: string, f: (d: Drill) => void) => edit((x) => f(x.drills.find((d) => d.id === id)!))
  const updateStep = (id: string, i: number, patch: Partial<DrillStep>) =>
    updateDrill(id, (d) => { Object.assign(d.steps[i], patch) })
  const lastClip = song.clips.at(-1)?.id

  return (
    <div className="panel" data-testid="drills-panel">
      <h2>Drills</h2>
      <button onClick={() => edit((x) => { const id = nextId('D', x.drills.map((d) => d.id)); x.drills.push({ id, name: `Drill ${id.slice(1)}`, steps: [] }) })}>
        + New drill
      </button>
      {song.drills.map((d) => (
        <section key={d.id} className="drill" data-drill={d.id}>
          <header>
            <input value={d.name} aria-label="Drill name" onChange={(e) => updateDrill(d.id, (x) => { x.name = e.target.value })} />
            <button className="primary btn-icon" disabled={!d.steps.length} onClick={() => onPlay(d)}><Icon name="play" size={16} /> Play</button>
            <button className="ghost" aria-label={`Delete ${d.name}`} onClick={() => edit((x) => { x.drills = x.drills.filter((y) => y.id !== d.id) })}><Icon name="close" size={16} /></button>
          </header>
          <ol className="steps">
            {d.steps.map((s, i) => (
              <li key={i} className="step" data-step={i}>
                <div className="step-head">
                  <strong>{s.type === 'clip' ? 'Clip' : 'Card'}</strong>
                  <button className="ghost" disabled={i === 0} aria-label="Move up"
                          onClick={() => updateDrill(d.id, (x) => { [x.steps[i - 1], x.steps[i]] = [x.steps[i], x.steps[i - 1]] })}><Icon name="up" size={16} /></button>
                  <button className="ghost" disabled={i === d.steps.length - 1} aria-label="Move down"
                          onClick={() => updateDrill(d.id, (x) => { [x.steps[i + 1], x.steps[i]] = [x.steps[i], x.steps[i + 1]] })}><Icon name="down" size={16} /></button>
                  <button className="ghost" aria-label="Delete step" onClick={() => updateDrill(d.id, (x) => { x.steps.splice(i, 1) })}><Icon name="close" size={16} /></button>
                </div>
                {s.type === 'clip' ? <ClipStepFields song={song} step={s} onChange={(p) => updateStep(d.id, i, p)} /> : (
                  <div className="fields">
                    <input value={s.text} placeholder="Teaching point…" aria-label="Card text"
                           onChange={(e) => updateStep(d.id, i, { text: e.target.value })} />
                    <label>seconds <input type="number" min={1} max={30} value={s.durationMs / 1000} aria-label="Card seconds"
                                          onChange={(e) => updateStep(d.id, i, { durationMs: Math.max(1, +e.target.value) * 1000 })} /></label>
                  </div>
                )}
              </li>
            ))}
          </ol>
          <div className="add-step">
            <button disabled={!lastClip} title={lastClip ? '' : 'Make a clip first'}
                    onClick={() => updateDrill(d.id, (x) => {
                      x.steps.push({ type: 'clip', clip: lastClip!, repeats: 3, speed: 0.75, track: 'original', yourTurn: true, tiers: [...TIERS] })
                    })}>+ Clip step</button>
            <button onClick={() => updateDrill(d.id, (x) => { x.steps.push({ type: 'card', text: '', durationMs: 4000 }) })}>+ Card</button>
          </div>
        </section>
      ))}
    </div>
  )
}

function ClipStepFields({ song, step, onChange }: { song: Song; step: ClipStep; onChange: (p: Partial<ClipStep>) => void }) {
  return (
    <div className="fields">
      <select value={step.clip} aria-label="Clip" onChange={(e) => onChange({ clip: e.target.value })}>
        {song.clips.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.id})</option>)}
      </select>
      <label>×<input type="number" min={1} max={10} value={step.repeats} aria-label="Repeats"
                     onChange={(e) => onChange({ repeats: Math.min(10, Math.max(1, Math.round(+e.target.value))) })} /></label>
      <select value={step.speed} aria-label="Speed" onChange={(e) => onChange({ speed: +e.target.value })}>
        {SPEEDS.map((v) => <option key={v} value={v}>{Math.round(v * 100)}%</option>)}
      </select>
      <select value={step.track} aria-label="Track" onChange={(e) => onChange({ track: e.target.value as Track })}>
        {tracksIn(song).map((t) => <option key={t}>{t}</option>)}
      </select>
      <span className="tiers" role="group" aria-label="Tiers shown">
        {TIERS.map((t) => (
          <label key={t}><input type="checkbox" checked={step.tiers.includes(t)}
                                onChange={(e) => onChange({ tiers: e.target.checked ? TIERS.filter((x) => x === t || step.tiers.includes(x)) : step.tiers.filter((x) => x !== t) })} />{TIER_LABELS[t]}</label>
        ))}
      </span>
      <label><input type="checkbox" checked={step.yourTurn} aria-label="Your turn gap" onChange={(e) => onChange({ yourTurn: e.target.checked })} />your turn</label>
    </div>
  )
}
