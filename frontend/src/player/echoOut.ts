// The transition between loop passes: "echo out". The last moment of the line goes into a delay, the dry sound
// falls away, the song jumps back while silent, and the line eases in under the repeats. All volume changes run on
// the browser's audio thread, so they can't step or stutter.
//
// The audio graph is built only when the first loop starts (always from a click or key press, which browsers
// require), so playback that never loops stays a plain audio element. To try another transition later, this class
// is the only thing to replace.
const ECHO = { delayS: 0.34, feedback: 0.42, toneHz: 3200, sendLevel: 0.85, sendS: 0.2 }
const DRY_OUT_S = 0.24 // the dry sound is gone by then, so the jump back is inaudible
const RESTART_S = 0.45 // the line starts coming back this long after the last word, or after the loop pause if longer
const EASE_IN_S = 0.4
const CURVE_POINTS = 64

const curve = (f: (u: number) => number) => Float32Array.from({ length: CURVE_POINTS }, (_, i) => f(i / (CURVE_POINTS - 1)))
const FALL = curve((u) => Math.cos((u * Math.PI) / 2)) // keeps the level up, then lets go
const RISE = curve((u) => (1 - Math.cos(u * Math.PI)) / 2) // starts from silence with no sudden edge

export class EchoOut {
  private ctx: AudioContext | null = null
  private dry!: GainNode
  private send!: GainNode
  private timers = new Set<number>()
  private cleanups: (() => void)[] = []
  private internal = false // the pause and play below are ours, not the listener's
  /** True from the last word until the line is coming back: the loop check waits. */
  busy = false

  constructor(private el: HTMLMediaElement) {}

  /** Call from the click or key press that starts a loop. */
  prepare() {
    if (this.ctx) { void this.ctx.resume(); return }
    const ctx = this.ctx = new AudioContext({ latencyHint: 'interactive' })
    const source = ctx.createMediaElementSource(this.el)
    this.dry = ctx.createGain()
    this.send = ctx.createGain()
    this.send.gain.value = 0
    const delay = ctx.createDelay(1)
    delay.delayTime.value = ECHO.delayS
    const feedback = ctx.createGain()
    feedback.gain.value = ECHO.feedback
    const tone = ctx.createBiquadFilter()
    tone.type = 'lowpass'
    tone.frequency.value = ECHO.toneHz
    source.connect(this.dry).connect(ctx.destination)
    source.connect(this.send).connect(delay).connect(tone).connect(ctx.destination)
    tone.connect(feedback).connect(delay)
    // A running audio graph must wake with the element, or the element would play in silence. Someone else's pause
    // or play in the middle of a transition cancels it.
    const onPlay = () => { void ctx.resume(); if (!this.internal) this.cancel() }
    const onPause = () => { if (!this.internal) this.cancel() }
    this.el.addEventListener('play', onPlay)
    this.el.addEventListener('pause', onPause)
    this.cleanups.push(() => { this.el.removeEventListener('play', onPlay); this.el.removeEventListener('pause', onPause) })
  }

  /** Run one transition, from the moment the last word ends, back to `restartMs` (where the first word starts).
   *  `pauseMs` is the loop's silence setting, and `speed` keeps the lead-in the same length at any speed. */
  run(restartMs: number, pauseMs: number, speed: number) {
    if (!this.ctx || this.busy) return
    this.busy = true
    const now = this.ctx.currentTime
    const send = this.send.gain, dry = this.dry.gain
    send.cancelScheduledValues(0)
    send.setValueAtTime(0, now)
    send.linearRampToValueAtTime(ECHO.sendLevel, now + 0.03)
    send.setValueAtTime(ECHO.sendLevel, now + ECHO.sendS - 0.04)
    send.linearRampToValueAtTime(0, now + ECHO.sendS)
    dry.cancelScheduledValues(0)
    dry.setValueCurveAtTime(FALL, now + 0.04, DRY_OUT_S - 0.04)

    const waitMs = Math.max(RESTART_S * 1000, pauseMs)
    const leadS = EASE_IN_S * speed
    if (pauseMs > RESTART_S * 1000) { // a long pause: truly stop, so the playhead waits at the start of the line
      this.after(DRY_OUT_S * 1000, () => {
        this.internally(() => this.el.pause())
        this.el.currentTime = Math.max(0, restartMs / 1000 - leadS)
      })
      this.after(waitMs, () => this.comeBack(true))
    } else { // keeps rolling silently from the jump, so that it is already moving when it comes back
      const silentS = RESTART_S - DRY_OUT_S
      this.after(DRY_OUT_S * 1000, () => {
        this.el.currentTime = Math.max(0, restartMs / 1000 - leadS - silentS * speed)
      })
      this.after(waitMs, () => this.comeBack(false))
    }
  }

  private comeBack(startPlaying: boolean) {
    const rise = () => {
      if (!this.ctx) return
      const g = this.dry.gain
      g.cancelScheduledValues(0)
      g.setValueCurveAtTime(RISE, this.ctx.currentTime, EASE_IN_S)
      this.busy = false
    }
    const whenSeeked = () => {
      if (!startPlaying) return rise()
      this.internally(() => { void this.el.play().then(rise, () => { this.busy = false }) })
    }
    if (this.el.seeking) this.el.addEventListener('seeked', whenSeeked, { once: true })
    else whenSeeked()
  }

  private internally(f: () => void) {
    this.internal = true
    f()
    // play and pause events arrive after this call returns
    window.setTimeout(() => { this.internal = false }, 50)
  }

  private after(ms: number, f: () => void) {
    const id = window.setTimeout(() => { this.timers.delete(id); f() }, ms)
    this.timers.add(id)
  }

  /** Back to plain full-volume playback: the loop ended, or the listener paused, played or jumped. */
  cancel() {
    this.timers.forEach(clearTimeout)
    this.timers.clear()
    this.busy = false
    if (!this.ctx) return
    this.send.gain.cancelScheduledValues(0)
    this.send.gain.value = 0
    this.dry.gain.cancelScheduledValues(0)
    this.dry.gain.value = 1
  }

  dispose() {
    this.cancel()
    this.cleanups.forEach((f) => f())
    void this.ctx?.close()
    this.ctx = null
  }
}
