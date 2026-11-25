// Word-by-word breakdown of one line, from the local model (cached per line on the server).
import { useEffect, useState } from 'react'
import { api } from '../api'
import { wordText } from '../captions/timing'
import type { Breakdown, Line } from '../types'

type State = { kind: 'idle' } | { kind: 'loading' } | { kind: 'ok'; data: Breakdown } | { kind: 'error'; message: string }

interface Props {
  songId: string
  line: Line | null
  nextLineId: string | null // broken down quietly in the background, so stepping through a song is quick
  lineNumber: number
  wordId: string | null
  showNiqqud: boolean
  onPickWord: (wordId: string) => void
}

export function BreakdownPanel({ songId, line, nextLineId, lineNumber, wordId, showNiqqud, onPickWord }: Props) {
  const [state, setState] = useState<State>({ kind: 'idle' })
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    if (!line) { setState({ kind: 'idle' }); return }
    let current = true // a newer click wins
    setState({ kind: 'loading' })
    api.breakdown(songId, line.id, refresh > 0)
      .then((data) => {
        if (current) setState({ kind: 'ok', data })
        if (nextLineId) api.breakdown(songId, nextLineId).catch(() => {}) // read-ahead; the server caches it
      }, (e: Error) => current && setState({ kind: 'error', message: e.message }))
    return () => { current = false }
  }, [songId, line?.id, refresh]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!line) return <div className="panel"><p className="hint">Use a line's magnifier button to see it broken down word by word.</p></div>

  return (
    <div className="panel breakdown" data-testid="breakdown">
      <h2>Line {lineNumber}</h2>
      <p className="bd-line" dir="rtl" lang="he">{line.words.map((w) => wordText(w, showNiqqud)).join(' ')}</p>
      {state.kind === 'loading' && <p className="hint">Breaking it down… about half a minute for a new line (up to a minute the first time). Lines already done open instantly.</p>}
      {state.kind === 'error' && <p className="error">{state.message}</p>}
      {state.kind === 'ok' && (
        <>
          <p className="bd-literal"><span className="meta">Word for word:</span> {state.data.literal}</p>
          <ol className="bd-words">
            {state.data.words.map((b, k) => {
              const w = line.words[k]
              return (
                <li key={k} className={w?.id === wordId ? 'selected' : ''}>
                  <button className="bd-word" onClick={() => w && onPickWord(w.id)}>
                    <span className="bd-he" dir="rtl" lang="he">{w ? wordText(w, showNiqqud) : b.word}</span>
                    <span className="bd-en">{b.english}</span>
                  </button>
                  {b.parts.length > 1 && (
                    <div className="bd-parts">
                      {b.parts.map((part, j) => (
                        <span key={j}>{j > 0 && ' + '}<span dir="rtl" lang="he">{part.hebrew}</span> <i>{part.english}</i></span>
                      ))}
                    </div>
                  )}
                  {b.note && <div className="bd-note">{b.note}</div>}
                </li>
              )
            })}
          </ol>
          <p className="hint">Made on this computer. <button className="ghost" onClick={() => setRefresh((n) => n + 1)}>Redo</button></p>
        </>
      )}
    </div>
  )
}
