// Top of the Flags tab: words Whisper heard that the lyrics don't have, and lyric words it heard nothing for.
// Suggestions only: Add / Delete apply one, Dismiss hides it for good.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../icons'
import type { Line, Suggestion, Suggestions } from '../types'

const clock = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, '0')}`

interface Props {
  songId: string
  lines: Line[]
  wordCount: number // refetch after a word is added or removed
  onPlay: (startMs: number, endMs: number) => void
  onAccept: (s: Suggestion) => Promise<void>
  onSelectWord: (wordId: string) => void
}

export function SuggestionsBox({ songId, lines, wordCount, onPlay, onAccept, onSelectWord }: Props) {
  const [data, setData] = useState<Suggestions | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { api.suggestions(songId).then(setData, (e: Error) => setError(e.message)) }, [songId, wordCount])

  const run = async (label: string, f: () => Promise<Suggestions | void>) => {
    setBusy(label)
    setError(null)
    try {
      const r = await f()
      if (r) setData(r)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (!data) return error ? <p className="error suggest-box">{error}</p> : null
  const lineNo = (id: string) => lines.findIndex((l) => l.id === id) + 1

  return (
    <section className="suggest-box" data-testid="suggestions">
      {!(data.available && data.suggestions.length === 0) && <h2>Lyrics check {data.available && <span className="count">{data.suggestions.length}</span>}</h2>}
      {!data.available ? (
        <>
          <p className="hint">The check listens to the vocals and points out words the lyrics are missing, or lyric words it can't hear.</p>
          <button disabled={!!busy} onClick={() => run('scan', () => api.scanSuggestions(songId))}>
            {busy === 'scan' ? 'Listening… (about a minute)' : 'Check lyrics against the audio'}
          </button>
        </>
      ) : data.suggestions.length === 0 ? (
        <p className="done">Lyrics check: no missing or extra words found.</p>
      ) : (
        <ul className="suggest-list">
          {data.suggestions.map((s) => (
            <li key={s.key} className={`suggest-${s.type}`}>
              <button className="suggest-what" onClick={() => onSelectWord(s.wordId)} title="Show this place in the lyrics">
                <span className="meta">{s.type === 'missing' ? 'Possibly missing' : 'Not heard'} · line {lineNo(s.lineId)} · {clock(s.startMs)}</span>
                <span className="suggest-text" dir="auto">{s.text}</span>
              </button>
              <span className="suggest-actions">
                <button onClick={() => onPlay(Math.max(0, s.startMs - 800), s.endMs + 800)} title="Listen to this spot" aria-label="Listen to this spot"><Icon name="play" size={16} /></button>
                <button className={s.type === 'missing' ? 'ok' : 'danger'} disabled={!!busy}
                        title={s.type === 'missing' ? 'Add this word to the lyrics where it was heard' : 'Remove this word from the lyrics'}
                        onClick={() => {
                          if (s.type === 'unheard' && !window.confirm('Delete this word from the lyrics?')) return
                          run(s.key, () => onAccept(s))
                        }}>
                  {s.type === 'missing' ? 'Add' : 'Delete'}
                </button>
                <button className="ghost" disabled={!!busy} onClick={() => run(s.key, () => api.dismissSuggestion(songId, s.key))}>Dismiss</button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  )
}
