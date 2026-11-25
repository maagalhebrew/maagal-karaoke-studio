import { useEffect, useState } from 'react'
import { Icon } from '../icons'
import type { Word } from '../types'

export type Edge = 'start' | 'both' | 'end'

interface Props {
  word: Word
  lineNumber: number
  wordNumber: number
  edge: Edge
  onEdge: (e: Edge) => void
  onTimes: (startMs: number, endMs: number) => void
  onSpelling: (text: string) => Promise<void>
  onClearFlags: () => void
  onPlay: () => void
  onTapLine: () => void
  onInsert: (side: 'before' | 'after', text: string) => Promise<void>
  onDelete: () => Promise<void>
  /** Line-break changes for this word; null where it doesn't apply (only edge words can move). */
  lineOps: { split: (() => void) | null; prev: (() => void) | null; next: (() => void) | null; join: (() => void) | null; remove: (() => void) | null }
  onClose: () => void
  rtl: boolean // the lyrics read right to left (Hebrew), so "before" is to the right
}

/** Why a word is flagged, in plain words (the chips in the Flags list use the short names). */
const FLAG_HELP: Record<string, string> = {
  'low-confidence': "The timing for this word is unsure. Play it and drag its edges if it's off.",
  'timing-adjusted': 'Its timing was moved automatically to fit between its neighbours. Play it to check.',
  'long-gap': 'There is a long pause before this word. Check it really starts that late.',
}

const EDGES: [Edge, string][] = [['start', 'Start edge'], ['both', 'Whole word'], ['end', 'End edge']]

export function WordInspector({ word, lineNumber, wordNumber, edge, onEdge, onTimes, onSpelling, onClearFlags,
                                onPlay, onTapLine, onInsert, onDelete, lineOps, onClose, rtl }: Props) {
  const [spelling, setSpelling] = useState(word.plain)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState<'before' | 'after' | null>(null)
  const [newWord, setNewWord] = useState('')
  useEffect(() => {
    setSpelling(word.plain)
    setError(null)
  }, [word.id, word.plain])
  useEffect(() => { setAdding(null); setNewWord('') }, [word.id])

  const run = (f: () => Promise<void>) => f().then(() => setError(null), (e: Error) => setError(e.message))
  const sure = Math.round(word.confidence * 100)
  const lineMoves = [lineOps.split, lineOps.prev, lineOps.next, lineOps.join, lineOps.remove].some(Boolean)

  return (
    <section className="inspector" data-testid="inspector" data-word={word.id} aria-label="Edit word">
      <header>
        <span className="insp-word" dir="auto">{word.plain}</span>
        <span className="insp-where">Line {lineNumber}, word {wordNumber} · {(word.startMs / 1000).toFixed(2)}–{(word.endMs / 1000).toFixed(2)} s</span>
        <button className="primary btn-icon" onClick={onPlay}><Icon name="play" /> Play word</button>
        <button className="ghost insp-close" onClick={onClose} title="Close (Esc)" aria-label="Close word panel"><Icon name="close" /></button>
      </header>

      {word.flags.length > 0 && (
        <div className="insp-check" role="group" aria-label="Why this word is flagged">
          <ul>{word.flags.map((f) => <li key={f}>{FLAG_HELP[f] ?? f}</li>)}</ul>
          <button className="ok" onClick={onClearFlags} title="Clear the flags on this word">Looks right</button>
        </div>
      )}

      <div className="insp-cards">
        <div className="insp-card" role="group" aria-label="Timing">
          <h4>Timing <span className={`insp-sure${sure < 50 ? ' low' : ''}`} title="How sure the word timing is">{sure}% sure</span></h4>
          <div className="insp-times">
            <label>Starts (ms)
              <input type="number" step={10} value={word.startMs} onChange={(e) => onTimes(+e.target.value, word.endMs)} />
            </label>
            <label>Ends (ms)
              <input type="number" step={10} value={word.endMs} onChange={(e) => onTimes(word.startMs, +e.target.value)} />
            </label>
          </div>
          <div className="insp-field">
            <span className="insp-label">Left and Right arrow keys move</span>
            <div className="seg" role="group" aria-label="Arrow keys move">
              {EDGES.map(([e, label]) => (
                <button key={e} className={edge === e ? 'on' : ''} aria-pressed={edge === e} onClick={() => onEdge(e)}>{label}</button>
              ))}
            </div>
          </div>
          <button className="link" onClick={onTapLine} title="Play the line and press Space at each word start (T)">Re-time the whole line by tapping (T)</button>
        </div>
      </div>

      <details className="insp-more">
        <summary>Spelling <span>punctuation or capitals; the letters stay the same</span></summary>
        <div className="insp-field">
          <label className="insp-label" htmlFor="insp-spelling">The word as shown (same letters)</label>
          <div className="insp-inline">
            <input id="insp-spelling" dir="auto" value={spelling} onChange={(e) => setSpelling(e.target.value)} />
            <button className="primary" disabled={spelling === word.plain} onClick={() => run(() => onSpelling(spelling))}>Save</button>
          </div>
          <p className="insp-hint">To change the letters, add the right word and delete this one below.</p>
        </div>
      </details>

      <details className="insp-more">
        <summary>Words and lines <span>add a missing word, delete one, or change where the line breaks</span></summary>
        {/* The lyrics can miss or add a word: fix the word list here. In Hebrew "before" is to the right. */}
        <div className="insp-field" role="group" aria-label="Add or remove a word">
          <span className="insp-label">This line's words</span>
          <div className="insp-inline">
            <button onClick={() => setAdding('before')} title={`Add a missing word just before this one (to its ${rtl ? 'right' : 'left'})`}>+ Add a word before</button>
            <button onClick={() => setAdding('after')} title={`Add a missing word just after this one (to its ${rtl ? 'left' : 'right'})`}>+ Add a word after</button>
            <button className="danger" onClick={() => {
              if (window.confirm('Delete this word from the lyrics? Its time goes with it.')) run(onDelete)
            }}>Delete this word</button>
          </div>
        </div>
        {adding && (
          <form className="insp-inline" onSubmit={(e) => { e.preventDefault(); if (newWord.trim()) run(() => onInsert(adding, newWord)) }}>
            <input autoFocus dir={rtl ? 'rtl' : 'ltr'} value={newWord} aria-label={`New word ${adding} this one`}
                   placeholder="type the word" onChange={(e) => setNewWord(e.target.value)} />
            <button type="submit" className="primary" disabled={!newWord.trim()}>Add {adding}</button>
            <button type="button" className="ghost" onClick={() => setAdding(null)}>Cancel</button>
          </form>
        )}
        <div className="insp-field" role="group" aria-label="Where the line breaks">
          <span className="insp-label">Line break</span>
          {lineMoves ? (
            <div className="insp-inline">
              {lineOps.split && <button className="btn-icon" onClick={lineOps.split} title="This word and the ones after it become a new line"><Icon name="clip" size={16} /> Start a new line here</button>}
              {lineOps.prev && <button className="btn-icon" onClick={lineOps.prev}><Icon name="up" size={16} /> Move to the line above</button>}
              {lineOps.next && <button className="btn-icon" onClick={lineOps.next}><Icon name="down" size={16} /> Move to the line below</button>}
              {lineOps.join && <button onClick={lineOps.join}>Join with the next line</button>}
              {lineOps.remove && <button className="danger" onClick={lineOps.remove}
                                         title="Remove the whole line, for a stray line like a section name that isn't sung (Undo brings it back)">Delete this line</button>}
            </div>
          ) : <p className="insp-hint">Nothing to change here.</p>}
          <p className="insp-hint">Only a line's first word can move up, and only its last word can move down.</p>
        </div>
      </details>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  )
}
