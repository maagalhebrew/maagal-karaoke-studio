import type { Breakdown, Folder, ImportJob, Language, Line, PracticeLog, SongLearning, Suggestions, LyricsCheck, Peaks, Permission, Section, Song, SongSummary, Track } from './types'

/** Split a line before a word, join a line with the next, move a line's edge word to the neighbouring line,
 *  or delete a line (`restore` is a delete's undo). `english` (an undo) sets the resulting lines' English. */
export type LineEdit = ({ action: 'split'; wordId: string } | { action: 'join'; lineId: string }
  | { action: 'move'; wordId: string; to: 'prev' | 'next' } | { action: 'delete'; lineId: string }
  | { action: 'restore'; index: number; line: Line; sections: Section[] }) & { english?: Record<string, string> }

/** Is each lyric line followed by its English? 'auto' = detect (Hebrew only: Spanish shares English's alphabet). */
export type EnglishLines = 'auto' | 'yes' | 'no'
export const englishLinesBody = (v: EnglishLines) => (v === 'auto' ? 'auto' : v === 'yes')

export interface UploadAnalysis {
  seconds: number; durationMs: number; peaksPerSecond: number; peaks: number[]
  segments: [number, number][]; suggest: [number, number]
  quality?: { lufs: number | null; lra: number | null; truePeakDb: number | null; clipped: number; stereo: boolean; topKHz: number }
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) {
    const body = await r.json().catch(() => null)
    throw new Error(body?.detail ?? `${r.status} ${r.statusText}`)
  }
  return r.json()
}

export const api = {
  songs: () => call<SongSummary[]>('/api/songs'),
  folders: () => call<Folder[]>('/api/folders'),
  practice: (songId: string) => call<PracticeLog>(`/api/songs/${songId}/practice`),
  learning: (songId: string) => call<SongLearning>(`/api/songs/${songId}/learning`),
  rateLine: (songId: string, lineId: string, rating: number | null) =>
    call<{ lineId: string; rating: number | null }>(`/api/songs/${songId}/ratings/${lineId}`, { method: 'PUT', body: JSON.stringify({ rating }) }),
  createFolder: (name: string) => call<Folder>('/api/folders', { method: 'POST', body: JSON.stringify({ name }) }),
  renameFolder: (id: number, name: string) => call<Folder[]>(`/api/folders/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteFolder: (id: number) => call<Folder[]>(`/api/folders/${id}`, { method: 'DELETE' }),
  addToFolder: (id: number, songId: string) => call<Folder[]>(`/api/folders/${id}/songs`, { method: 'POST', body: JSON.stringify({ songId }) }),
  setSongFolders: (songId: string, folders: number[]) =>
    call<{ folders: number[] }>(`/api/songs/${songId}/folders`, { method: 'PUT', body: JSON.stringify({ folders }) }),
  setFavorite: (songId: string, favorite: boolean) =>
    call<{ favorite: boolean }>(`/api/songs/${songId}/favorite`, { method: 'PUT', body: JSON.stringify({ favorite }) }),
  song: (id: string) => call<Song>(`/api/songs/${id}`),
  deleteSong: (id: string) => call<{ deleted: string; movedTo: string }>(`/api/songs/${id}`, { method: 'DELETE' }),
  save: (id: string, song: Song) => call<{ saved: true }>(`/api/songs/${id}`, { method: 'PUT', body: JSON.stringify(song) }),
  peaks: (id: string, track: Track = 'vocals') => call<Peaks>(`/api/songs/${id}/peaks?track=${track}`),
  audioUrl: (id: string, track: Track) => `/api/songs/${id}/audio/${track}`,
  permissions: () => call<Permission[]>('/api/permissions'),
  permissionsDue: () => call<Permission[]>('/api/permissions/due'),
  savePermission: (id: string, changes: Partial<Permission>) =>
    call<Permission>(`/api/permissions/${id}`, { method: 'PUT', body: JSON.stringify(changes) }),
  suggestions: (id: string) => call<Suggestions>(`/api/songs/${id}/suggestions`),
  scanSuggestions: (id: string) => call<Suggestions>(`/api/songs/${id}/suggestions/scan`, { method: 'POST' }),
  dismissSuggestion: (id: string, key: string) =>
    call<Suggestions>(`/api/songs/${id}/suggestions/dismiss`, { method: 'POST', body: JSON.stringify({ key }) }),
  editWords: (id: string, body: { action: 'insert'; wordId: string; side: 'before' | 'after'; text: string; startMs?: number; endMs?: number }
                              | { action: 'delete'; wordId: string }) =>
    call<{ song: Song; wordId: string }>(`/api/songs/${id}/words`, { method: 'POST', body: JSON.stringify(body) }),
  editLines: (id: string, body: LineEdit) =>
    call<{ song: Song; lineIds: string[]; wordId: string; undo: LineEdit }>(`/api/songs/${id}/lines`, { method: 'POST', body: JSON.stringify(body) }),
  translateLines: (id: string, lineIds: string[]) =>
    call<{ english: Record<string, string> }>(`/api/songs/${id}/translate-lines`, { method: 'POST', body: JSON.stringify({ lineIds }) }),
  breakdown: (id: string, lineId: string, refresh = false) =>
    call<Breakdown>(`/api/songs/${id}/breakdown`, { method: 'POST', body: JSON.stringify({ lineId, refresh }) }),
  checkLyrics: (lyrics: string, language: Language, englishLines: EnglishLines) =>
    call<LyricsCheck>('/api/import/check', { method: 'POST', body: JSON.stringify({ lyrics, language, englishLines: englishLinesBody(englishLines) }) }),
  translateModels: () => call<{ default: string; enabled: boolean; ollamaRunning: boolean; models: string[] }>('/api/translate/models'),
  uploadAudio: (blob: Blob, name: string) =>
    call<UploadAnalysis & { upload: string }>(`/api/import/audio?name=${encodeURIComponent(name)}`,
      { method: 'POST', body: blob, headers: { 'Content-Type': 'application/octet-stream' } }),
  uploadUrl: (upload: string) => `/api/import/audio/${upload}`,
  trimAudio: (upload: string, startMs: number, endMs: number) =>
    call<{ upload: string; seconds: number }>(`/api/import/audio/${upload}/trim`, { method: 'POST', body: JSON.stringify({ startMs, endMs }) }),
  startImport: (body: { url: string; lyrics: string; title: string; artist: string; model: string; upload?: string;
                        language: Language; englishLines: boolean | 'auto' }) =>
    call<ImportJob>('/api/import', { method: 'POST', body: JSON.stringify(body) }),
  importStatus: () => call<ImportJob | null>('/api/import'),
}
