import { wordText } from '../captions/timing'
import type { Line } from '../types'

const FLAG_LABELS: Record<string, string> = {
  'low-confidence': 'timing unsure',
  'timing-adjusted': 'timing adjusted',
  'long-gap': 'long gap before',
}

export const TIMING_FLAGS = ['low-confidence', 'timing-adjusted', 'long-gap']

interface Props {
  lines: Line[]
  selectedId: string | null
  showNiqqud: boolean
  onPick: (id: string) => void
}

export function FlagsPanel({ lines, selectedId, showNiqqud, onPick }: Props) {
  const words = lines.flatMap((l) => l.words)
  const flagged = words.filter((w) => w.flags.length > 0)
  return (
    <div className="flags" data-testid="flags">
      {flagged.length === 0
        ? <p className="done">No flags left. This song is done.</p>
        : <h2>Words to check <span className="count">{flagged.length}</span></h2>}
      {flagged.length > 0 && (
        <ul>
          {flagged.map((w) => (
            <li key={w.id}>
              <button className={w.id === selectedId ? 'flag-item selected' : 'flag-item'} onClick={() => onPick(w.id)} data-word={w.id}>
                <span className="flag-word" dir="auto">{wordText(w, showNiqqud)}</span>
                <span className="flag-id">{w.id}</span>
                <span className="chips">{w.flags.map((f) => <span key={f} className={`chip chip-${f}`}>{FLAG_LABELS[f] ?? f}</span>)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
