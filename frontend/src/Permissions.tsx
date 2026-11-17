import { useEffect, useState } from 'react'
import { api } from './api'
import { Icon } from './icons'
import { PERMISSION_STATUSES, type Permission } from './types'

type Field = 'artist' | 'contact_name' | 'contact_channel' | 'contact_handle' | 'asked_on' | 'follow_up_on' | 'scope' | 'reply_path'
const TEXT_FIELDS: [Field, string][] = [
  ['artist', 'Artist'], ['contact_name', 'Contact name'], ['contact_channel', 'Channel (Instagram, email...)'],
  ['contact_handle', 'Handle / address'], ['scope', 'Scope granted'], ['reply_path', 'Saved reply (file path)'],
]

/** Permissions tracker: one line per song; its fields open on a click. Every change saves straight away. */
export function Permissions() {
  const [rows, setRows] = useState<Permission[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  useEffect(() => { api.permissions().then(setRows, (e: Error) => setError(e.message)) }, [])

  const save = (id: string, changes: Partial<Permission>) =>
    api.savePermission(id, changes).then(
      (saved) => { setError(null); setRows((rs) => rs!.map((r) => (r.song_id === id ? saved : r))) },
      (e: Error) => setError(e.message),
    )

  const copyDraft = async (r: Permission) => {
    await navigator.clipboard.writeText(r.draft)
    setToast(`Request for “${r.title || r.song_id}” copied`)
    setTimeout(() => setToast(null), 3500)
  }

  return (
    <div className="page">
      <p><a className="back-link" href="#/"><Icon name="back" /> Songs</a></p>
      <h1>Permissions</h1>
      <p className="hint">Status “Granted” turns the excerpt guard off for that song. Asking sets a follow-up 10 days later.</p>
      {error && <p className="error">{error}</p>}
      {rows?.map((r) => (
        <section key={r.song_id} className={`perm perm-${r.status.replace(/ /g, '-').toLowerCase()}`} data-testid="perm-row">
          <header>
            <button className="perm-open" aria-expanded={open === r.song_id} onClick={() => setOpen(open === r.song_id ? null : r.song_id)}>
              <Icon name={open === r.song_id ? 'down' : 'right'} size={16} />
              <strong dir="auto">{r.title || r.song_id}</strong>
              {r.artist && <span className="meta" dir="auto">{r.artist}</span>}
            </button>
            {r.follow_up_on && <span className="meta">Follow up {r.follow_up_on}</span>}
            <select value={r.status} aria-label={`Status of ${r.title || r.song_id}`} onChange={(e) => save(r.song_id, { status: e.target.value as Permission['status'] })}>
              {PERMISSION_STATUSES.map((s) => <option key={s}>{s}</option>)}
            </select>
            <button onClick={() => copyDraft(r)} title="Copy the Hebrew request, filled in with this song and contact">Copy request</button>
          </header>
          {open === r.song_id && (
            <div className="perm-grid">
              {TEXT_FIELDS.map(([f, label]) => (
                <label key={f}>{label}
                  <input defaultValue={r[f] ?? ''} key={`${f}-${r.updated_at}`}
                         onBlur={(e) => e.target.value !== (r[f] ?? '') && save(r.song_id, { [f]: e.target.value })} />
                </label>
              ))}
              {(['asked_on', 'follow_up_on'] as const).map((f) => (
                <label key={f}>{f === 'asked_on' ? 'Asked on' : 'Follow up on'}
                  <input type="date" value={r[f] ?? ''} onChange={(e) => save(r.song_id, { [f]: e.target.value || null })} />
                </label>
              ))}
            </div>
          )}
        </section>
      ))}
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}

/** Launch reminder on the song list: requests whose follow-up date has come. */
export function FollowUpsDue() {
  const [due, setDue] = useState<Permission[]>([])
  useEffect(() => { api.permissionsDue().then(setDue, () => setDue([])) }, [])
  if (!due.length) return null
  return (
    <div className="due" role="alert">
      <strong>Follow-up due on {due.length} permission request{due.length > 1 ? 's' : ''}</strong>
      <ul>
        {due.map((r) => (
          <li key={r.song_id}>{r.title || r.song_id}: asked {r.asked_on}, follow up {r.follow_up_on}{r.artist && ` (${r.artist})`}</li>
        ))}
      </ul>
      <a href="#/permissions">Open permissions</a>
    </div>
  )
}
