// The lyrics as a vertical list: one row per sung line, its English on the left and the lyrics on the right,
// section headers between groups. Click a line's number to select it, Shift-click another to select every line
// between. Words stay clickable (select a word; double-click to edit it).
import { memo, useEffect, useRef } from 'react'
import { Icon, type IconName } from '../icons'
import { RATING_LABELS } from '../practice'
import { wordText } from '../captions/timing'
import type { Line, Section } from '../types'
import { sectionColor } from './Timeline'

interface Props {
  lines: Line[]
  sections: Section[]
  activeLineId: string | null
  activeWordId: string | null
  selectedId: string | null
  rangeIds: Set<string>
  loopingId: string | null
  playing: boolean
  showNiqqud: boolean
  rtl: boolean // the lyrics read right to left (Hebrew)
  onWord: (wordId: string, shift: boolean) => void
  onEditWord?: (wordId: string) => void // double-click: open the word panel
  onLine: (lineId: string, shift: boolean) => void
  onEnglish: (lineId: string, text: string) => void
  onPlayLine: (lineId: string) => void
  onLoopLine: (lineId: string) => void
  onBreakdown?: (lineId: string) => void // absent: no breakdown for this song's language
  loops?: Record<string, number> // completed passes of each line's loop (practice log)
  ratings?: Record<string, number> // 0 don't know, 1 shaky, 2 know it
  onRate?: (lineId: string, rating: number) => void
  newWordIds?: Set<string> // set when "Mark words new to you" is on
  onSplit?: (wordId: string) => void // scissors between two words: the second starts a new line
}
const RATING_CLASS = ['dont', 'shaky', 'know']
const RATING_ICONS: IconName[] = ['close', 'minus', 'check']
const HARDEST = 3 // the most-looped lines get a stronger badge

const clock = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, '0')}`

export const LineList = memo(function LineList(p: Props) {
  const box = useRef<HTMLDivElement>(null)

  // Follow playback: keep the sung line in view (inside the list only, the page doesn't jump).
  useEffect(() => {
    if (!p.playing || !p.activeLineId || !box.current) return
    const row = box.current.querySelector<HTMLElement>(`[data-line-row="${p.activeLineId}"]`)
    if (!row) return
    const b = box.current
    if (row.offsetTop < b.scrollTop + 30 || row.offsetTop + row.offsetHeight > b.scrollTop + b.clientHeight)
      b.scrollTo({ top: row.offsetTop - b.clientHeight / 3, behavior: 'smooth' })
  }, [p.activeLineId, p.playing])

  const loops = p.loops ?? {}
  const hardest = Object.values(loops).sort((a, b) => b - a)[Math.min(HARDEST, Object.keys(loops).length) - 1] ?? Infinity

  const sectionOf = (lineIndex: number) => {
    const idx = (id: string) => p.lines.findIndex((l) => l.id === id)
    return p.sections.find((s) => idx(s.fromLine) <= lineIndex && lineIndex <= idx(s.toLine))
  }

  return (
    <div className="line-list" ref={box} data-testid="line-list">
      {p.lines.map((line, i) => {
        const section = sectionOf(i)
        const startsSection = section?.fromLine === line.id
        const inRange = line.words.some((w) => p.rangeIds.has(w.id))
        const flagged = line.words.some((w) => w.flags.length)
        const looping = p.loopingId === line.id
        const r = p.ratings?.[line.id]
        const cls = ['ll-row', line.id === p.activeLineId && 'active', inRange && 'in-range', looping && 'looping'].filter(Boolean).join(' ')
        return (
          <div key={line.id}>
            {startsSection && section && (
              <div className="ll-section"><i style={{ background: sectionColor(section) }} />{section.label}</div>
            )}
            <div className={cls} data-line-row={line.id}>
              <button className="ll-num" onClick={(e) => p.onLine(line.id, e.shiftKey)}
                      title={`Starts at ${clock(line.words[0].startMs)}. Select this line; Shift-click another line to select every line between`}>
                <b>{i + 1}</b>{flagged && <i className="ll-flag" title="timing to check" />}
                {loops[line.id] > 0 && <span className={`ll-loops${loops[line.id] >= hardest ? ' hard' : ''}`}
                                             title={`Looped ${loops[line.id]} time${loops[line.id] === 1 ? '' : 's'}`}><Icon name="loop" size={10} />{loops[line.id]}</span>}
              </button>
              <div className="ll-actions">
                <button onClick={() => p.onPlayLine(line.id)} title="Play this line" aria-label={`Play line ${i + 1}`}><Icon name="play" size={16} /></button>
                <button className={looping ? 'on' : ''} aria-pressed={looping}
                        onClick={() => p.onLoopLine(line.id)} title="Loop this line until you click again (pause and fade: in the settings)"
                        aria-label={`Loop line ${i + 1}`}><Icon name="loop" size={16} /></button>
                {p.onBreakdown && <button onClick={() => p.onBreakdown!(line.id)} title="Word-by-word breakdown" aria-label={`Break down line ${i + 1}`}><Icon name="search" size={16} /></button>}
                {p.onRate && (() => {
                  // Click cycles: not rated → don't know → shaky → know it → not rated (pressing "know it" again clears).
                  const pressed = r === undefined ? 0 : Math.min(2, r + 1)
                  return <button className={`ll-rate${r !== undefined ? ` ${RATING_CLASS[r]}` : ''}`}
                                 onClick={() => p.onRate!(line.id, pressed)}
                                 aria-label={`Line ${i + 1}: ${r === undefined ? 'not rated' : RATING_LABELS[r]}`}
                                 title={`${r === undefined ? 'Not rated' : RATING_LABELS[r]}. Click to change, or press 1 don't know, 2 shaky, 3 know it while it plays`}>
                    {r === undefined ? <span className="ll-unrated" /> : <Icon name={RATING_ICONS[r]} size={16} />}</button>
                })()}
              </div>
              <div className="ll-read">
                <input className="ll-en" value={line.english} dir="ltr" placeholder="Add English" data-line={line.id} aria-label={`English for line ${i + 1}`}
                       onChange={(e) => p.onEnglish(line.id, e.target.value)} />
              </div>
              <div className="ll-he" dir={p.rtl ? 'rtl' : 'ltr'}>
                {line.words.map((w, k) => (
                  <span key={w.id} className="ll-wrap">
                    {k > 0 && p.onSplit && <button className="ll-split" onClick={() => p.onSplit!(w.id)}
                                                   title="Split the line here: this word starts a new line" aria-label={`Split line ${i + 1} before word ${k + 1}`}><Icon name="clip" size={12} /></button>}
                    <button data-word={w.id}
                            className={['ll-word', w.id === p.activeWordId && 'active', w.id === p.selectedId && 'selected',
                              w.flags.length > 0 && 'flagged', p.newWordIds?.has(w.id) && 'new'].filter(Boolean).join(' ')}
                            onClick={(e) => p.onWord(w.id, e.shiftKey)} onDoubleClick={() => p.onEditWord?.(w.id)}
                            title="Click to select, double-click (or E) to edit this word">
                      {wordText(w, p.showNiqqud)}
                    </button>
                  </span>
                ))}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
})
