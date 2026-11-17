// The Songs page: a library with views (all, favourites, by status, by artist) and folders in a sidebar, search,
// and per song its workflow status, permission status, favourite star and folders. A song can be in several
// folders; drag a row onto a folder to add it, or use the row's "Folders" menu.
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { Icon } from './icons'
import { FollowUpsDue } from './Permissions'
import { daysAgo, dueText, playedFor, today } from './practice'
import type { Folder, SongSummary, Stage } from './types'

const STAGE_LABELS: Record<Stage, string> = {
  'add-english': 'Add English', 'make-drills': 'Make drills',
  export: 'Ready to export', exported: 'Exported',
}
const STAGES = Object.keys(STAGE_LABELS) as Stage[]
const VIEW_KEY = 'karaoke.libraryView'
const DRAG_TYPE = 'application/x-karaoke-song'

const length = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.round((ms % 60000) / 1000)).padStart(2, '0')}`

const isDue = (s: SongSummary) => !!s.learning.dueDay && s.learning.dueDay <= today()
const notStarted = (s: SongSummary) => !s.learning.lastStudied
const difficultyTitle = (s: SongSummary) => `Difficulty ${s.learning.difficulty} of 5: ${s.learning.newToYou} of ${s.learning.forms} word forms are new to you`
  + ` (${s.learning.inOtherSongs} also appear in other songs) · ${Math.round(s.learning.wpm)} words a minute · ${s.words} words in all`

/** The one thing to do next with a song: a review that's due first, then the song's next stage of work. */
function nextStep(s: SongSummary): { label: string; href: string; urgent?: boolean } {
  const song = `#/song/${s.id}`
  if (isDue(s)) return { label: dueText(s.learning.dueDay!), href: song, urgent: true }
  switch (s.status.stage) {
    case 'add-english': return { label: `Add English (${s.status.englishLines} of ${s.status.lines})`, href: song }
    case 'make-drills': return { label: 'Make a drill', href: song }
    case 'export': return s.permission === 'Granted' ? { label: 'Ready to export', href: song } : { label: 'Ask permission', href: '#/permissions' }
    default: return { label: 'Practise', href: song }
  }
}

/** How much of the song you know, as a ring. The lines you've rated decide it; hover for the counts. */
function MasteryRing({ s }: { s: SongSummary }) {
  const R = 14, around = 2 * Math.PI * R, share = s.learning.rated ? s.learning.mastery : 0
  const title = `${s.learning.know} know it, ${s.learning.shaky} shaky, ${s.learning.dontKnow} don't know, ${s.learning.lines - s.learning.rated} not rated (rate lines with 1 / 2 / 3 while they play)`
  return (
    <svg className="ring" viewBox="0 0 34 34" role="img" aria-label={`${Math.round(share * 100)}% learned`}>
      <title>{title}</title>
      <circle cx="17" cy="17" r={R} fill="none" stroke="var(--line)" strokeWidth="3" />
      {share > 0 && <circle cx="17" cy="17" r={R} fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round"
                            strokeDasharray={`${around * share} ${around}`} transform="rotate(-90 17 17)" />}
      {s.learning.rated > 0 && <text x="17" y="21" textAnchor="middle">{Math.round(share * 100)}</text>}
    </svg>
  )
}

/** Which songs a view shows. Views: all, fav, recent, due, next, stage:<stage>, artist:<name>, folder:<id>. */
function inView(view: string, s: SongSummary): boolean {
  if (view === 'fav') return s.favorite
  if (view === 'recent') return !!s.practice.lastDay
  if (view === 'due') return isDue(s)
  if (view === 'next') return notStarted(s)
  if (view.startsWith('stage:')) return s.status.stage === view.slice(6)
  if (view.startsWith('artist:')) return s.artist === view.slice(7)
  if (view.startsWith('folder:')) return s.folders.includes(Number(view.slice(7)))
  return true
}

export function SongList() {
  const [songs, setSongs] = useState<SongSummary[] | null>(null)
  const [folders, setFolders] = useState<Folder[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [view, setViewState] = useState(() => { try { return localStorage.getItem(VIEW_KEY) || 'all' } catch { return 'all' } })
  const [query, setQuery] = useState('')
  const [picker, setPicker] = useState<string | null>(null) // song whose folder menu is open
  const [newFolder, setNewFolder] = useState<string | null>(null) // name being typed, or null when closed
  const [dropOn, setDropOn] = useState<number | null>(null)

  const setView = (v: string) => { setViewState(v); try { localStorage.setItem(VIEW_KEY, v) } catch { /* not remembered */ } }
  const load = () => Promise.all([api.songs(), api.folders()]).then(([s, f]) => { setSongs(s); setFolders(f) }, (e: Error) => setError(e.message))
  useEffect(() => { load() }, [])
  const act = async (f: () => Promise<unknown>, done?: string) => {
    try { await f(); setError(null); if (done) setNotice(done); await load() } catch (e) { setError((e as Error).message) }
  }

  // A view whose folder or artist no longer exists falls back to all songs.
  useEffect(() => {
    if (!songs) return
    const gone = (view.startsWith('folder:') && !folders.some((f) => `folder:${f.id}` === view))
      || (view.startsWith('artist:') && !songs.some((s) => `artist:${s.artist}` === view))
    if (gone) setView('all')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [songs, folders])

  const artists = useMemo(() => {
    const n = new Map<string, number>()
    for (const s of songs ?? []) if (s.artist) n.set(s.artist, (n.get(s.artist) ?? 0) + 1)
    return [...n].sort((a, b) => a[0].localeCompare(b[0]))
  }, [songs])
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = (songs ?? []).filter((s) => inView(view, s)
      && (!q || [s.title, s.artist, s.id].some((t) => t.toLowerCase().includes(q))))
    // Recently practised: latest first · due: most overdue first · start next: easiest first (then slowest).
    if (view === 'recent') return list.sort((a, b) => (b.practice.lastDay ?? '').localeCompare(a.practice.lastDay ?? ''))
    if (view === 'due') return list.sort((a, b) => a.learning.dueDay!.localeCompare(b.learning.dueDay!))
    if (view === 'next') return list.sort((a, b) => a.learning.difficulty - b.learning.difficulty || a.learning.wpm - b.learning.wpm)
    return list
  }, [songs, view, query])

  const remove = (s: SongSummary) => {
    const name = s.title || s.id
    if (!window.confirm(`Delete "${name}"?\n\nIt disappears from the app. Its folder moves to songs\\_deleted, so it can be restored by moving the folder back.`)) return
    act(async () => { const r = await api.deleteSong(s.id); setNotice(`"${name}" deleted (kept in ${r.movedTo}).`) })
  }
  const createFolder = () => {
    const name = newFolder?.trim()
    if (!name) { setNewFolder(null); return }
    act(async () => { const f = await api.createFolder(name); setNewFolder(null); setView(`folder:${f.id}`) })
  }
  const renameFolder = (f: Folder) => {
    const name = window.prompt('Rename the folder', f.name)
    if (name && name.trim() !== f.name) act(() => api.renameFolder(f.id, name))
  }
  const deleteFolder = (f: Folder) => {
    if (window.confirm(`Delete the folder "${f.name}"?\n\nIts ${f.count} song(s) stay in your library.`))
      act(() => api.deleteFolder(f.id), `Folder "${f.name}" deleted; its songs are still in All songs.`)
  }
  const toggleFolder = (s: SongSummary, id: number) =>
    act(() => api.setSongFolders(s.id, s.folders.includes(id) ? s.folders.filter((x) => x !== id) : [...s.folders, id]))
  const drop = (f: Folder, e: React.DragEvent) => {
    e.preventDefault()
    setDropOn(null)
    const id = e.dataTransfer.getData(DRAG_TYPE)
    const song = songs?.find((s) => s.id === id)
    if (!song) return
    if (song.folders.includes(f.id)) { setNotice(`"${song.title || song.id}" is already in ${f.name}.`); return }
    act(() => api.addToFolder(f.id, id), `"${song.title || song.id}" added to ${f.name}.`)
  }

  const count = (pred: (s: SongSummary) => boolean) => (songs ?? []).filter(pred).length
  const side = (v: string, label: React.ReactNode, n: number, extra?: Partial<React.ButtonHTMLAttributes<HTMLButtonElement>>) => (
    <button className={`lib-view${view === v ? ' on' : ''}`} aria-pressed={view === v} onClick={() => setView(v)} {...extra}>
      <span className="lib-view-name">{label}</span><span className="lib-count">{n}</span>
    </button>
  )
  const viewName = view === 'all' ? 'All songs' : view === 'fav' ? 'Favourites' : view === 'recent' ? 'Recently practised' : view === 'due' ? 'Due for review'
    : view === 'next' ? 'Start next: easiest first'
    : view.startsWith('stage:') ? STAGE_LABELS[view.slice(6) as Stage]
      : view.startsWith('artist:') ? view.slice(7)
        : folders.find((f) => `folder:${f.id}` === view)?.name ?? ''

  return (
    <div className="page library">
      <FollowUpsDue />
      <h1>Songs</h1>
      <p className="import-actions"><a className="button primary" href="#/import">+ Add a song</a> <a href="#/permissions">Permissions</a></p>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="meta" role="status">{notice}</p>}
      {songs?.length === 0 && <p>No songs yet. Click “+ Add a song”.</p>}
      {songs && songs.length > 0 && (
        <div className="library-body">
          <aside className="lib-side" aria-label="Library views">
            {side('all', 'All songs', songs.length)}
            {side('fav', 'Favourites', count((s) => s.favorite))}
            {side('recent', 'Recently practised', count((s) => !!s.practice.lastDay))}
            {side('due', 'Due for review', count(isDue))}
            {side('next', 'Start next (easiest first)', count(notStarted))}

            <h3>Status</h3>
            {STAGES.map((st) => { const n = count((s) => s.status.stage === st); return n ? <span key={st}>{side(`stage:${st}`, <><i className={`dot stage-${st}`} />{STAGE_LABELS[st]}</>, n)}</span> : null })}

            {artists.length > 0 && <><h3>Artists</h3>{artists.map(([a, n]) => <span key={a}>{side(`artist:${a}`, a, n)}</span>)}</>}

            <h3>Folders</h3>
            {folders.map((f) => (
              <div key={f.id} className={`lib-folder${dropOn === f.id ? ' drop' : ''}`}
                   onDragOver={(e) => { if (e.dataTransfer.types.includes(DRAG_TYPE)) { e.preventDefault(); setDropOn(f.id) } }}
                   onDragLeave={() => setDropOn(null)} onDrop={(e) => drop(f, e)}>
                {side(`folder:${f.id}`, <><Icon name="folder" size={16} /> {f.name}</>, f.count)}
                <button className="ghost lib-icon" onClick={() => renameFolder(f)} aria-label={`Rename ${f.name}`} title="Rename"><Icon name="edit" size={14} /></button>
                <button className="ghost lib-icon" onClick={() => deleteFolder(f)} aria-label={`Delete folder ${f.name}`} title="Delete folder (songs stay)"><Icon name="close" size={14} /></button>
              </div>
            ))}
            {newFolder === null
              ? <button className="ghost lib-new" onClick={() => setNewFolder('')}>+ New folder</button>
              : <input className="lib-new-input" autoFocus value={newFolder} placeholder="Folder name, then Enter" maxLength={60}
                       onChange={(e) => setNewFolder(e.target.value)} onBlur={createFolder}
                       onKeyDown={(e) => { if (e.key === 'Enter') createFolder(); if (e.key === 'Escape') setNewFolder(null) }} />}
            {folders.length > 0 && <p className="hint">Drag a song onto a folder to add it.</p>}
          </aside>

          <section className="lib-main">
            <div className="lib-toolbar">
              <h2>{viewName} <span className="meta">{shown.length} song{shown.length === 1 ? '' : 's'}</span></h2>
              <input type="search" value={query} placeholder="Search title or artist" aria-label="Search songs" onChange={(e) => setQuery(e.target.value)} />
            </div>
            {shown.length === 0 ? (
              <p className="meta">{query ? 'No songs match that search.' : view.startsWith('folder:')
                ? 'No songs in this folder yet: drag songs here from All songs, or use “Folders” on a song.' : 'No songs here.'}</p>
            ) : (
              <ul className="song-rows">
                {shown.map((s) => {
                  const next = nextStep(s)
                  return (
                    <li key={s.id} className={`song-row${picker === s.id ? ' menu-open' : ''}`} data-song={s.id} draggable
                        onDragStart={(e) => { e.dataTransfer.setData(DRAG_TYPE, s.id); e.dataTransfer.effectAllowed = 'copy' }}>
                      <MasteryRing s={s} />
                      <div className="song-who">
                        <a className="song-title" href={`#/song/${s.id}`} dir="auto">{s.title || s.id}</a>
                        <div className="meta" dir="auto">{s.artist || 'Artist not set'}
                          {s.folders.map((id) => folders.find((f) => f.id === id)).filter(Boolean).map((f) => <span key={f!.id} className="chip">{f!.name}</span>)}
                        </div>
                      </div>
                      <div className="song-stats meta" title={`${difficultyTitle(s)}. ${s.practice.seconds
                        ? `${playedFor(s.practice.seconds)} in all (${playedFor(s.practice.practiceSeconds)} in Practice mode) on ${s.practice.days} day${s.practice.days === 1 ? '' : 's'}`
                        : 'Not played yet'}. Permission: ${s.permission}`}>
                        <span>{s.practice.lastDay ? `${playedFor(s.practice.seconds)}, ${daysAgo(s.practice.lastDay)}` : 'Not practised yet'}</span>
                        <span>{length(s.durationMs)}, {s.learning.newToYou} new words, difficulty {s.learning.difficulty} of 5</span>
                      </div>
                      <a className={`song-next${next.urgent ? ' urgent' : ''}`} href={next.href} title={`${STAGE_LABELS[s.status.stage]}. Permission: ${s.permission}`}>{next.label}</a>
                      <div className="song-tools">
                        <button className={`ghost star${s.favorite ? ' on' : ''}`} aria-pressed={s.favorite}
                                aria-label={s.favorite ? `Unfavourite ${s.title || s.id}` : `Favourite ${s.title || s.id}`}
                                onClick={() => act(() => api.setFavorite(s.id, !s.favorite))}><Icon name={s.favorite ? 'star' : 'starOutline'} /></button>
                        <span className="song-more">
                          <FolderPicker open={picker === s.id} onOpen={(o) => setPicker(o ? s.id : null)} folders={folders} song={s}
                                        onToggle={(id) => toggleFolder(s, id)} />
                          <button className="ghost danger" onClick={() => remove(s)} aria-label={`Delete ${s.title || s.id}`} title="Delete this song"><Icon name="close" size={16} /></button>
                        </span>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  )
}

function FolderPicker({ open, onOpen, folders, song, onToggle }: {
  open: boolean; onOpen: (o: boolean) => void; folders: Folder[]; song: SongSummary; onToggle: (id: number) => void
}) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open, onOpen])
  return (
    <span className="folder-picker" ref={ref}>
      <button className="ghost" aria-expanded={open} aria-label={`Folders for ${song.title || song.id}`} title="Folders" onClick={() => onOpen(!open)}><Icon name="folder" size={16} /></button>
      {open && (
        <span className="folder-pop" role="group" aria-label="Folders">
          {folders.length === 0 && <span className="hint">No folders yet: make one with “+ New folder” on the left.</span>}
          {folders.map((f) => (
            <label key={f.id}><input type="checkbox" checked={song.folders.includes(f.id)} onChange={() => onToggle(f.id)} /> {f.name}</label>
          ))}
        </span>
      )}
    </span>
  )
}
