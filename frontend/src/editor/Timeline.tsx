// The timeline: one bead per sung word, sized by how loudly it is sung, over a faint waveform of the track playing,
// with section bands above. Word edges appear only when zoomed in or on the selected word; those are what you drag.
import { useEffect, useMemo, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/plugins/regions'
import TimelinePlugin from 'wavesurfer.js/plugins/timeline'
import type { Line, Peaks, Section, SectionKind, Word } from '../types'
import { sectionLineCount } from './structure'

export const SECTION_COLORS: Record<SectionKind, string> = {
  verse: '#7C8CFF', chorus: '#FF8FB4', bridge: '#C39BFF',
  intro: '#5FD6C4', outro: '#5FD6C4', transition: '#A4A6C8',
  custom: '#FFB27A',
}

/** Colours a section can be given (light, mid, dark of blue, orange, green). */
export const SECTION_PALETTE = [
  { name: 'blue', shades: ['#93c5fd', '#3b82f6', '#1e40af'] },
  { name: 'orange', shades: ['#fdba74', '#f97316', '#c2410c'] },
  { name: 'green', shades: ['#86efac', '#22c55e', '#15803d'] },
]

/** A section's colour: the one picked for it, or its kind's. */
export function sectionColor(s: Pick<Section, 'kind' | 'color'>): string {
  return s.color || SECTION_COLORS[s.kind]
}

const WAVE_HEIGHT = 104, BAND_PX = 18, BEAD_MIN = 5, BEAD_MAX = 48
const SHOW_EDGES_AT_PX_PER_S = 60 // zoomed in enough to aim at a word's edge
const BEAD = { upcoming: '#6B72B8', played: '#FFC53D', active: '#F4EFDD', selected: '#F4EFDD', flagged: '#FF7A7A' }
const RANGE_COLOR = 'rgba(255,197,61,0.2)'
const DRAG_ID = 'range-select' // temporary region while drag-selecting
const RANGE_ID = 'range-highlight'
const isWordId = (id: string) => /^L\d+W\d+$/.test(id)

export interface View { pxPerSec: number; scrollLeft: number }

interface Props {
  peaks: Peaks // the track playing, for the waveform
  vocalPeaks: Peaks // always the singing, for the beads
  durationMs: number
  audioUrl: string
  lines: Line[]
  sections: Section[]
  selectedId: string | null
  timeMs: number
  range: { startMs: number; endMs: number } | null
  zoom: number // 0 = whole song, 1 = 2-second window
  onReady: (ws: WaveSurfer) => void
  onInteraction?: () => void // the listener moved the playhead
  onSelect: (wordId: string, shift: boolean) => void
  onRangeDrag: (startMs: number, endMs: number) => void
  onWordTimes: (wordId: string, startMs: number, endMs: number, side: 'start' | 'end') => void
  onSectionEdge: (sectionId: string, ms: number, side: 'start' | 'end') => void // a dragged band edge
  onView?: (v: View) => void
}

export function Timeline(p: Props) {
  const box = useRef<HTMLDivElement>(null)
  const ws = useRef<WaveSurfer | null>(null)
  // wavesurfer 8 plugins come from definePlugin(): the instance type is what create() returns.
  const regions = useRef<ReturnType<typeof RegionsPlugin.create> | null>(null)
  const ready = useRef(false)
  const [loaded, setLoaded] = useState(0) // bumps on every (re)load so regions are (re)built after it
  const cb = useRef(p)
  cb.current = p

  const pxPerSec = () => {
    const width = box.current?.clientWidth ?? 0, fit = width / (p.durationMs / 1000)
    return fit * Math.pow(width / 2 / Math.max(fit, 1e-6), p.zoom)
  }

  // Zoom: logarithmic from "whole song fits" to "2 seconds fill the view". Only valid once audio is loaded.
  const applyZoom = () => {
    const w = ws.current
    if (!w || !box.current || !ready.current) return
    const width = box.current.clientWidth
    const fit = width / (cb.current.durationMs / 1000)
    const max = width / 2
    w.zoom(fit * Math.pow(max / fit, cb.current.zoom))
  }

  // Create once: the Editor is keyed by song. A track change is a load, below.
  useEffect(() => {
    const plugin = RegionsPlugin.create()
    // Seconds ruler under the waveform; tick spacing follows the zoom.
    const ruler = TimelinePlugin.create({ height: 18, secondaryLabelOpacity: 0.6, style: { color: '#A4A6C8', fontSize: '11px' } })
    const w = WaveSurfer.create({
      container: box.current!,
      height: WAVE_HEIGHT,
      url: p.audioUrl,
      peaks: [p.peaks.peaks],
      duration: p.durationMs / 1000,
      waveColor: 'rgba(107,114,184,0.42)',
      progressColor: 'rgba(164,166,200,0.42)',
      cursorColor: '#F4EFDD',
      cursorWidth: 2,
      barWidth: 1,
      barGap: 1,
      normalize: true,
      autoScroll: true,
      autoCenter: true,
      plugins: [plugin, ruler],
    })
    ws.current = w
    regions.current = plugin
    const view = () => {
      const width = w.getWrapper().scrollWidth
      cb.current.onView?.({ pxPerSec: width / (cb.current.durationMs / 1000), scrollLeft: w.getScroll() })
    }
    w.on('redrawcomplete', view)
    w.on('zoom', view)
    w.on('scroll', view)
    w.on('interaction', () => cb.current.onInteraction?.())
    w.on('ready', () => {
      ready.current = true
      applyZoom()
      view()
      setLoaded((n) => n + 1)
      cb.current.onReady(w)
    })
    // Word bodies are click-through, so a click lands on the waveform: select the word under it.
    let shift = false, dragEndedAt = 0
    box.current!.addEventListener('pointerdown', (e) => { shift = e.shiftKey }, true)
    w.on('click', (relX) => {
      if (performance.now() - dragEndedAt < 300) return // the click that ends a drag-selection
      const t = relX * cb.current.durationMs
      const word = cb.current.lines.flatMap((l) => l.words).find((x) => x.startMs <= t && t < x.endMs)
      if (word) cb.current.onSelect(word.id, shift)
    })
    plugin.on('region-updated', (r, side) => {
      if (isWordId(r.id))
        cb.current.onWordTimes(r.id, Math.round(r.start * 1000), Math.round(r.end * 1000), side === 'start' ? 'start' : 'end')
      else if (r.id.startsWith('sec-'))
        cb.current.onSectionEdge(r.id.slice(4), Math.round((side === 'start' ? r.start : r.end) * 1000), side === 'start' ? 'start' : 'end')
    })
    // Drag on the waveform to select a range of words; the temporary region is replaced by the range highlight.
    plugin.enableDragSelection({ id: DRAG_ID, color: RANGE_COLOR })
    plugin.on('region-created', (r) => {
      if (r.id !== DRAG_ID) return
      const start = Math.round(r.start * 1000), end = Math.round(r.end * 1000)
      dragEndedAt = performance.now()
      r.remove()
      cb.current.onRangeDrag(start, end)
    })
    return () => {
      ready.current = false
      w.destroy()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Switch the playing track without moving the playhead; the waveform shows the track you are hearing.
  useEffect(() => {
    const w = ws.current
    if (!w || !ready.current || w.getMediaElement()?.src.endsWith(p.audioUrl)) return
    const t = w.getCurrentTime()
    const wasPlaying = w.isPlaying()
    w.load(p.audioUrl, [p.peaks.peaks], p.durationMs / 1000).then(() => {
      w.setTime(t)
      if (wasPlaying) w.play()
    })
  }, [p.audioUrl, p.peaks, p.durationMs])

  // How loudly each word is sung, as a bead height: the same whichever track is playing.
  const beadOf = useMemo(() => {
    const { peaks, peaksPerSecond } = p.vocalPeaks
    const words = p.lines.flatMap((l) => l.words)
    let top = 1e-6
    const raw = new Map<string, number>()
    for (const w of words) {
      let m = 0
      const end = Math.min(peaks.length, Math.ceil((w.endMs / 1000) * peaksPerSecond))
      for (let i = Math.floor((w.startMs / 1000) * peaksPerSecond); i < end; i++) if (peaks[i] > m) m = peaks[i]
      raw.set(w.id, m)
      if (m > top) top = m
    }
    return new Map([...raw].map(([id, m]) => [id, BEAD_MIN + (m / top) * (BEAD_MAX - BEAD_MIN)]))
  }, [p.lines, p.vocalPeaks])

  const beadColor = (w: Word, t: number) =>
    w.id === p.selectedId ? BEAD.selected
      : w.flags.length ? BEAD.flagged
        : t >= w.startMs && t < w.endMs ? BEAD.active
          : t >= w.endMs ? BEAD.played : BEAD.upcoming

  // Keep regions in step with the song (song state is the source of truth).
  useEffect(() => {
    const plugin = regions.current
    if (!plugin || !loaded) return
    const existing = new Map(plugin.getRegions().map((r) => [r.id, r]))
    const wanted = new Set<string>()
    const lineIndex = new Map(p.lines.map((l, i) => [l.id, i]))

    for (const s of p.sections) {
      const from = p.lines[lineIndex.get(s.fromLine)!], to = p.lines[lineIndex.get(s.toLine)!]
      if (!from || !to) continue
      const id = `sec-${s.id}`
      wanted.add(id)
      const start = from.words[0].startMs / 1000, end = to.words[to.words.length - 1].endMs / 1000
      const r = existing.get(id)
      const text = `${s.label}`
      const label = () => {
        const el = document.createElement('span')
        el.textContent = text
        el.title = `${s.label}: ${sectionLineCount(p.lines, s)}`
        Object.assign(el.style, { font: "11px 'Heebo Variable', Heebo, sans-serif", color: '#A4A6C8', padding: '0 3px', whiteSpace: 'nowrap', lineHeight: '14px', display: 'block', overflow: 'hidden' })
        return el
      }
      const band = (node: HTMLElement) => { node.style.borderBottom = `3px solid ${sectionColor(s)}` }
      if (r) {
        // Always re-set the times: a dragged edge snaps to a line boundary (or back, if the drag was refused).
        r.setOptions({ start, end })
        if (r.element) band(r.element)
        // Section ids are renumbered in song order, so this band may now be a different section: refresh its label.
        if (r.content?.textContent !== text) r.setOptions({ content: label() })
      } else {
        const nr = plugin.addRegion({ id, start, end, color: 'transparent', drag: false, resize: true, minLength: 0.2, content: label() })
        if (nr.element) {
          // The band itself is click-through; only its edge handles can be grabbed (drag to grow / shrink the section).
          Object.assign(nr.element.style, { height: `${BAND_PX}px`, top: '0', pointerEvents: 'none', overflow: 'hidden' })
          band(nr.element)
          nr.element.querySelectorAll<HTMLElement>('[part~="region-handle"]').forEach((h) => {
            Object.assign(h.style, { pointerEvents: 'auto', width: '6px', border: 'none', background: 'transparent', cursor: 'ew-resize' })
          })
          nr.element.setAttribute('data-section', s.id)
        }
      }
    }
    const zoomedIn = pxPerSec() >= SHOW_EDGES_AT_PX_PER_S
    const middle = BAND_PX + (WAVE_HEIGHT - BAND_PX) / 2
    for (const line of p.lines) {
      for (const w of line.words) {
        wanted.add(w.id)
        const start = w.startMs / 1000, end = w.endMs / 1000
        let r = existing.get(w.id)
        if (r) {
          if (r.start !== start || r.end !== end) r.setOptions({ start, end })
        } else {
          r = plugin.addRegion({ id: w.id, start, end, color: BEAD.upcoming, drag: false, resize: true, minLength: 0.04 })
          if (r.element) {
            // Body is click-through (so a drag anywhere selects a range); only the edge handles are grabbable.
            Object.assign(r.element.style, { pointerEvents: 'none', borderRadius: '3px', minWidth: '2px' })
            r.element.querySelectorAll<HTMLElement>('[part~="region-handle"]').forEach((h) => { h.style.pointerEvents = 'auto' })
            r.element.setAttribute('data-word', w.id)
          }
        }
        if (r.element) {
          const height = beadOf.get(w.id) ?? BEAD_MIN
          r.element.style.top = `${middle - height / 2}px`
          r.element.style.height = `${height}px`
          const showEdges = zoomedIn || w.id === p.selectedId
          r.element.querySelectorAll<HTMLElement>('[part~="region-handle"]').forEach((h) => {
            Object.assign(h.style, { display: showEdges ? '' : 'none', borderColor: BEAD.active, borderWidth: '1px', cursor: 'ew-resize' })
          })
        }
      }
    }
    if (p.range) {
      wanted.add(RANGE_ID)
      const start = p.range.startMs / 1000, end = p.range.endMs / 1000
      const r = existing.get(RANGE_ID)
      if (r) r.setOptions({ start, end })
      else {
        const nr = plugin.addRegion({ id: RANGE_ID, start, end, color: RANGE_COLOR, drag: false, resize: false })
        if (nr.element) Object.assign(nr.element.style, { pointerEvents: 'none', top: `${BAND_PX + 2}px`, height: `calc(100% - ${BAND_PX + 2}px)` })
      }
    }
    for (const [id, r] of existing) if (!wanted.has(id) && id !== DRAG_ID) r.remove()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.lines, p.sections, p.selectedId, p.vocalPeaks, p.range, p.zoom, beadOf, loaded])

  // Bead colours follow the playhead; only the beads that change are touched.
  const words = useMemo(() => p.lines.flatMap((l) => l.words), [p.lines])
  let reached = 0
  for (const w of words) { if (w.startMs <= p.timeMs) reached++; else break }
  const inWord = reached > 0 && p.timeMs < words[reached - 1].endMs
  useEffect(() => {
    const plugin = regions.current
    if (!plugin || !loaded) return
    const byId = new Map(plugin.getRegions().map((r) => [r.id, r]))
    for (const w of words) {
      const r = byId.get(w.id), color = beadColor(w, p.timeMs)
      if (r && r.color !== color) r.setOptions({ color })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reached, inWord, words, p.selectedId, loaded])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(applyZoom, [p.zoom, p.durationMs])

  return <div ref={box} className="timeline" data-testid="timeline" />
}
