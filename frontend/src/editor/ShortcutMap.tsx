// Full-screen keyboard map: a drawn keyboard with the shortcut keys coloured by group and callout lines to what
// each one does. Opened from the bar's keyboard button or a tap of ?. One SVG, so the lines always meet their keys.

type Group = 'playback' | 'loops' | 'speed' | 'editing' | 'learning' | 'general' | 'practice'
const COLORS: Record<Group, string> = {
  playback: '#0ea5e9', loops: '#f97316', speed: '#22c55e', editing: '#a855f7', learning: '#ec4899', general: '#94a3b8', practice: '#eab308',
}
const GROUP_NAMES: Record<Group, string> = {
  playback: 'Playback', loops: 'Loops', speed: 'Speed', editing: 'Editing', learning: 'Learning', general: 'General', practice: 'Practice only',
}

// --- keyboard geometry (US layout), in key units -------------------------------------------------------------
const U = 58, GAP = 6, KX = 84, KY = 196
type Key = { id: string; label: string; x: number; y: number; w: number }

function layout(): Key[] {
  const keys: Key[] = []
  const row = (y: number, x0: number, defs: [string, string, number?][]) => {
    let x = x0
    for (const [id, label, w = 1] of defs) { keys.push({ id, label, x, y, w }); x += w }
  }
  const chars = (s: string) => [...s].map((c) => [c.toLowerCase(), c] as [string, string])
  row(0, 0, [['esc', 'Esc']])
  row(1.25, 0, [...chars('`1234567890-='), ['backspace', 'Backspace', 2]])
  row(2.25, 0, [['tab', 'Tab', 1.5], ...chars('QWERTYUIOP[]'), ['\\', '\\', 1.5]])
  row(3.25, 0, [['caps', 'Caps', 1.75], ...chars("ASDFGHJKL;'"), ['enter', 'Enter', 2.25]])
  row(4.25, 0, [['shift', 'Shift', 2.25], ...chars('ZXCVBNM,./'), ['rshift', 'Shift', 2.75]])
  row(5.25, 0, [['ctrl', 'Ctrl', 1.25], ['win', 'Win', 1.25], ['alt', 'Alt', 1.25], ['space', 'Space', 6.25],
    ['ralt', 'Alt', 1.25], ['fn', 'Fn', 1.25], ['rctrl', 'Ctrl', 1.25]])
  row(4.25, 16.5, [['up', '↑']])
  row(5.25, 15.5, [['left', '←'], ['down', '↓'], ['right', '→']])
  return keys
}

const px = (k: Key) => ({ x: KX + k.x * U, y: KY + k.y * U, w: k.w * U - GAP, h: U - GAP })
/** The middle of a key's top edge (callout from above) or bottom edge (from below). */
const edge = (k: Key, top: boolean) => { const p = px(k); return { x: p.x + p.w / 2, y: top ? p.y : p.y + p.h } }

interface Callout { keys: string[]; group: Group; name: string; text: string[] }

export function ShortcutMap({ jumpSec, onClose }: { jumpSec: number; onClose: () => void }) {
  const jump = jumpSec ? `${jumpSec} s` : 'one line'
  // Above the keyboard / below it, each listed left to right in key order so the lines don't cross.
  const top: Callout[] = [
    { keys: ['esc'], group: 'general', name: 'Esc', text: ['Close this map, a panel,', 'or clear the selection'] },
    { keys: ['1', '2', '3'], group: 'learning', name: '1 · 2 · 3', text: ["Rate the line: don't know,", 'shaky, know it (again: clear)'] },
    { keys: ['e'], group: 'editing', name: 'E', text: ['Edit the selected word', '(or double-click it)'] },
    { keys: ['t'], group: 'editing', name: 'T', text: ['Tap-time the line:', 'Space at each word start'] },
    { keys: ['u'], group: 'speed', name: 'U', text: ['Slower', '(pitch is kept)'] },
    { keys: ['i'], group: 'loops', name: 'I', text: ['Loop this line', 'again: stop'] },
    { keys: ['o'], group: 'loops', name: 'O', text: ['Loop this section', 'again: stop'] },
  ]
  const bottom: Callout[] = [
    { keys: ['v'], group: 'practice', name: 'V', text: ['Original /', 'instrumental'] },
    { keys: ['space'], group: 'playback', name: 'Space', text: ['Play / pause'] },
    { keys: ['n'], group: 'speed', name: 'N', text: ['Faster'] },
    { keys: ['j'], group: 'playback', name: 'J', text: [`Back ${jump}`] },
    { keys: ['k'], group: 'playback', name: 'K', text: ['Play / pause'] },
    { keys: ['l'], group: 'playback', name: 'L', text: [`Forward ${jump}`] },
    { keys: ['/'], group: 'general', name: '?  (Shift + /)', text: ['Tap: this map', 'Hold: keys on buttons'] },
    { keys: ['left', 'right'], group: 'editing', name: '← →', text: ['Nudge the word you', 'are editing 10 ms', '(Shift: 50 ms)'] },
  ]
  const keys = layout()
  const byId = new Map(keys.map((k) => [k.id, k]))
  const keyGroup = new Map<string, Group>()
  for (const c of [...top, ...bottom]) for (const id of c.keys) keyGroup.set(id, c.group)

  const W = 1240, H = 790
  const labelW = (n: number) => (W - 40) / n
  const label = (c: Callout, i: number, n: number, y: number, above: boolean) => {
    const w = labelW(n), x = 20 + i * w, cx = x + w / 2
    const boxH = 30 + c.text.length * 18, boxY = above ? y - boxH : y
    const anchorY = above ? boxY + boxH : boxY
    return (
      <g key={c.name}>
        {c.keys.map((id) => {
          const k = edge(byId.get(id)!, above) // meet the key at its edge, so its letter stays readable
          return <g key={id}>
            <line x1={cx} y1={anchorY} x2={k.x} y2={k.y} stroke={COLORS[c.group]} strokeWidth={2} strokeOpacity={0.9} />
            <circle cx={k.x} cy={k.y} r={3.5} fill={COLORS[c.group]} stroke="#fff" strokeWidth={1.5} />
          </g>
        })}
        <rect x={x + 6} y={boxY} width={w - 12} height={boxH} rx={8} fill="#0f172a" stroke={COLORS[c.group]} strokeWidth={2} />
        <text x={cx} y={boxY + 22} textAnchor="middle" fontSize={17} fontWeight={700} fill={COLORS[c.group]}>{c.name}</text>
        {c.text.map((t, j) => <text key={j} x={cx} y={boxY + 42 + j * 18} textAnchor="middle" fontSize={14} fill="#e5e7eb">{t}</text>)}
      </g>
    )
  }

  return (
    <div className="keymap-overlay" role="dialog" aria-label="Keyboard shortcuts" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="keymap">
        <header>
          <h2>Keyboard shortcuts: Studio editor</h2>
          <button className="ghost" onClick={onClose} aria-label="Close keyboard map">Close <kbd>Esc</kbd></button>
        </header>
        <svg viewBox={`0 0 ${W} ${H}`} className="keymap-svg" role="img" aria-label="Keyboard with the shortcut keys marked">
          {keys.map((k) => {
            const p = px(k), g = keyGroup.get(k.id)
            return (
              <g key={k.id}>
                <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={7}
                      fill={g ? COLORS[g] : '#1e293b'} fillOpacity={g ? 0.9 : 1} stroke={g ? '#fff' : '#334155'} strokeWidth={g ? 1.5 : 1} />
                <text x={p.x + p.w / 2} y={p.y + p.h / 2 + 6} textAnchor="middle" fontSize={k.label.length > 2 ? 13 : 18}
                      fontWeight={g ? 800 : 500} fill={g ? '#0b1020' : '#94a3b8'}>{k.label}</text>
              </g>
            )
          })}
          {top.map((c, i) => label(c, i, top.length, 168, true))}
          {bottom.map((c, i) => label(c, i, bottom.length, 600, false))}
        </svg>
        <div className="keymap-foot">
          <span className="keymap-legend">
            {(Object.keys(COLORS) as Group[]).map((g) => <span key={g}><i style={{ background: COLORS[g] }} />{GROUP_NAMES[g]}</span>)}
          </span>
          <span><b>Mouse:</b> click a line number to select it · Shift-click another for every line between · Shift-click a word for the words between</span>
          <span><b>Lines:</b> the magnifier breaks a line down word by word · 1 / 2 / 3 rate it · T tap-times it</span>
          <span className="meta">Practice uses the same playback keys, plus V. Shortcuts pause while you type in a text box. J / L jump: change it in the settings.</span>
        </div>
      </div>
    </div>
  )
}
