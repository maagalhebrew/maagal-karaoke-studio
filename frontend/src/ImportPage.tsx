// "Add a song": the audio (a recording of the computer's sound, or a file) + pasted Hebrew lyrics -> the pipeline
// stages on a branded "getting it ready" screen, then straight into the Studio editor.
import { useEffect, useRef, useState } from 'react'
import { api, englishLinesBody, type EnglishLines } from './api'
import { type AudioUpload, FilePick, QualityReport, Recorder, type StagedUpload } from './AudioSource'
import { Icon } from './icons'
import { TrimStep } from './TrimStep'
import type { ImportJob, Language, LyricsCheck } from './types'

const STEP_LABELS: Record<string, string> = {
  upload: 'Audio received',
  ingest: 'Read audio and lyrics',
  separate: 'Separate the vocals',
  translate: 'English translation (local model)',
  align: 'Time the words to the singing',
  assemble: 'Save the song',
}
const MODEL_LABELS: Record<string, string> = {
  'gemma4:12b': 'Gemma 4 12B (most accurate, ~5 s a line)',
  dictalm: 'DictaLM 3.0 1.7B (fast, less accurate)',
}
type Source = 'record' | 'file'
const SOURCES: [Source, string][] = [['record', 'Record computer sound'], ['file', 'Audio file']]
const SOURCE_KEY = 'karaoke.importSource'
const LANGUAGE_KEY = 'karaoke.importLanguage'
const LANGUAGES: [Language, string][] = [['he', 'Hebrew'], ['es', 'Spanish']]
const LANGUAGE_NAMES: Record<Language, string> = { he: 'Hebrew', es: 'Spanish' }
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
const STEP_ICONS = { waiting: 'minus', running: 'record', done: 'check', failed: 'close' } as const
const FIXES: Record<string, string> = {
  ingest: 'Check the lyrics have Hebrew lines.',
  separate: 'Close other programs using the graphics card (DaVinci Resolve, games) and try again.',
  translate: 'Start the Ollama app (it lives in the system tray), then add the song again or type the English in the Studio editor.',
  align: 'Make sure the lyrics list every line as it is sung, repeats included.',
}

/** Time since the import started, ticking once a second. */
function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])
  return <p className="meta prep-elapsed">{mmss(Math.max(0, now / 1000 - since))} so far</p>
}

export function ImportPage() {
  const [source, setSourceState] = useState<Source>(() => {
    try { return localStorage.getItem(SOURCE_KEY) === 'file' ? 'file' : 'record' } catch { return 'record' } // an old 'youtube' choice -> record
  })
  const setSource = (s: Source) => { setSourceState(s); setError(null); try { localStorage.setItem(SOURCE_KEY, s) } catch { /* not remembered */ } }
  const [staged, setStaged] = useState<StagedUpload | null>(null) // uploaded, waiting for its ends to be trimmed
  const [audio, setAudio] = useState<AudioUpload | null>(null)
  const [title, setTitle] = useState('')
  const [artist, setArtist] = useState('')
  const [lyrics, setLyrics] = useState('')
  const [language, setLanguageState] = useState<Language>(() => {
    try { return localStorage.getItem(LANGUAGE_KEY) === 'es' ? 'es' : 'he' } catch { return 'he' }
  })
  // Hebrew can tell its English lines apart by alphabet; Spanish can't, so it starts at "lyrics only".
  const [englishLines, setEnglishLines] = useState<EnglishLines>(language === 'he' ? 'auto' : 'no')
  const setLanguage = (l: Language) => {
    setLanguageState(l)
    setEnglishLines((v) => (l === 'es' && v === 'auto' ? 'no' : l === 'he' && v === 'no' ? 'auto' : v))
    try { localStorage.setItem(LANGUAGE_KEY, l) } catch { /* not remembered */ }
  }
  const [check, setCheck] = useState<LyricsCheck | null>(null)
  const [job, setJob] = useState<ImportJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<{ list: string[]; running: boolean; enabled: boolean } | null>(null)
  const [model, setModel] = useState('')
  const timer = useRef<number | undefined>(undefined)

  // A running (or failed) import survives leaving the page: show it on return. A finished one is in the song list.
  useEffect(() => { api.importStatus().then((j) => j && j.state !== 'done' && setJob(j), () => {}) }, [])
  useEffect(() => {
    api.translateModels().then((m) => { setModels({ list: m.models, running: m.ollamaRunning, enabled: m.enabled }); setModel(m.default) }, () => {})
  }, [])

  useEffect(() => {
    window.clearTimeout(timer.current)
    if (!lyrics.trim()) { setCheck(null); return }
    timer.current = window.setTimeout(() => api.checkLyrics(lyrics, language, englishLines).then(setCheck, (e: Error) => setError(e.message)), 400)
  }, [lyrics, language, englishLines])

  useEffect(() => {
    if (job?.state !== 'running') return
    const t = window.setInterval(() => api.importStatus().then((j) => j && setJob(j), () => {}), 1000)
    return () => window.clearInterval(t)
  }, [job?.state])
  // Ready: straight into the Studio editor. Words the timing model was unsure of stay flagged there.
  useEffect(() => { if (job?.state === 'done') window.location.hash = `#/song/${job.slug}` }, [job?.state, job?.slug])

  const start = async () => {
    setError(null)
    const upload = audio?.upload
    try {
      setJob(await api.startImport({ url: '', lyrics, title, artist, model, upload, language, englishLines: englishLinesBody(englishLines) }))
      if (upload) setAudio(null) // the server has taken the file for this song
    } catch (e) { setError((e as Error).message) }
  }
  const gotAudio = (u: StagedUpload, fileName?: string) => {
    setAudio(null)
    setStaged(u)
    if (fileName && !title.trim()) setTitle(fileName.replace(/\.[^.]+$/, ''))
  }

  const running = job?.state === 'running'
  const haveAudio = audio
  const ready = haveAudio && check && !check.problems.length && !running
  // Why the button can't be pressed yet, in the page's own words.
  const missing = running ? '' : [
    !haveAudio && (staged ? 'the trim step finished' : source === 'record' ? 'a recording' : 'an audio file'),
    !lyrics.trim() && `the ${LANGUAGE_NAMES[language]} lyrics`,
  ].filter(Boolean).join(' and ')

  const steps = job && (
    <ol className="steps-list">
      {job.steps.map((s) => (
        <li key={s.name} className={`step-${s.state}`}>
          <Icon name={STEP_ICONS[s.state]} size={16} /> {STEP_LABELS[s.name] ?? s.name}
          {s.seconds != null && <span className="meta"> · {s.seconds.toFixed(0)} s</span>}
        </li>
      ))}
    </ol>
  )

  // While the song is being prepared (and the moment it opens), the page is only this: the brand, a word of
  // encouragement and the steps.
  if (job && job.state !== 'failed') return (
    <div className="page import import-prep" data-testid="import-job" data-state={job.state}>
      <img className="prep-medallion" src="/brand/medallion.png" alt="Maagal Hebrew" width={140} height={140} />
      <h1>Getting your song ready</h1>
      <p className="prep-byline">We're separating the voice, translating each line and timing every word to the singing.
        Give us about 5 minutes. You can leave this page; it keeps going.</p>
      <div className="prep-work">
        <picture className="prep-trace" aria-hidden="true">
          <source srcSet="/brand/watermark-trace-final.png" media="(prefers-reduced-motion: reduce)" />
          <video src="/brand/watermark-trace.webm" autoPlay muted loop playsInline width={120} height={120} />
        </picture>
        <div>
          {steps}
          <Elapsed since={job.startedAt} />
          {job.note && <p className="meta" data-testid="import-note">{job.note}. {FIXES.translate}</p>}
        </div>
      </div>
    </div>
  )

  return (
    <div className="page import">
      <p><a className="back-link" href="#/"><Icon name="back" /> Songs</a></p>
      <h1>Add a song</h1>

      {job && (
        <section className="import-job" data-testid="import-job" data-state={job.state}>
          <h2>Stopped <span className="meta">{job.slug}</span></h2>
          {steps}
          {job.note && <p className="meta" data-testid="import-note">{job.note}. {FIXES.translate}</p>}
          {job.error && (
            <p className="error" role="alert">
              {STEP_LABELS[job.error.step] ?? job.error.step}: {job.error.message}
              {FIXES[job.error.step] && <><br />Likely fix: {FIXES[job.error.step]}</>}
            </p>
          )}
        </section>
      )}

      <div className="import-form">
        <div className="seg import-source" role="group" aria-label="Where the audio comes from">
          {SOURCES.map(([s, label]) => (
            <button key={s} className={source === s ? 'on' : ''} aria-pressed={source === s} onClick={() => setSource(s)}>{label}</button>
          ))}
        </div>
        {staged ? (
          <TrimStep staged={staged} onDone={(u) => { setStaged(null); setAudio(u) }} onCancel={() => setStaged(null)}
                    onError={(m) => setError(m || null)} />
        ) : audio ? (
          <div className="audio-ready" data-testid="audio-ready">
            <span className="ok-text">Audio ready: {mmss(audio.seconds)} {audio.from === 'recording' ? '(recording)' : `(${audio.from})`}</span>
            <audio controls src={api.uploadUrl(audio.upload)} />
            <button className="ghost" onClick={() => setAudio(null)}>Replace</button>
            {audio.quality && <QualityReport q={audio.quality} from={audio.from} />}
          </div>
        ) : source === 'record' ? (
          <Recorder onReady={(u) => gotAudio(u)} onError={(m) => setError(m || null)} />
        ) : (
          <FilePick onReady={gotAudio} onError={(m) => setError(m || null)} />
        )}
        <div className="import-row">
          <label>Title <input value={title} placeholder="Latin letters make a nicer folder name" onChange={(e) => setTitle(e.target.value)} /></label>
          <label>Artist <input value={artist} onChange={(e) => setArtist(e.target.value)} /></label>
        </div>
        <div className="import-row import-lang">
          <div className="seg" role="group" aria-label="The song's language">
            {LANGUAGES.map(([l, label]) => (
              <button key={l} className={language === l ? 'on' : ''} aria-pressed={language === l} onClick={() => setLanguage(l)}>{label}</button>
            ))}
          </div>
          <label className="import-model">English under each lyric line?
            <select value={englishLines} onChange={(e) => setEnglishLines(e.target.value as EnglishLines)} data-testid="english-lines">
              {language === 'he' && <option value="auto">Detect it</option>}
              <option value="no">No, lyrics only</option>
              <option value="yes">Yes: lyric line, then its English</option>
            </select>
          </label>
        </div>
        <label>{LANGUAGE_NAMES[language]} lyrics
          <textarea value={lyrics} dir="auto" rows={14} spellCheck={false} onChange={(e) => setLyrics(e.target.value)}
                    placeholder={`Paste the ${LANGUAGE_NAMES[language]} lyrics: one sung line per line, repeats written out.\nA blank line or a label like [Chorus] starts a new section.\n\nThe English is made for you.\n(Lyrics with each line followed by its English work too: choose "Yes" above.)`} />
        </label>
        {check && (
          <p className={check.problems.length ? 'error' : 'meta'} data-testid="lyrics-check">
            {check.problems.length ? check.problems.join(' ') : (
              <>{check.lines} lines in {check.sections} section{check.sections === 1 ? '' : 's'} · {check.words} words ·
                {check.withEnglish ? ` English given on ${check.withEnglish}/${check.lines}` : ' English will be translated'}
                {check.sections === 1 && check.lines > 8 && ' · no [section] labels found: you can add sections in the Studio editor later'}</>
            )}
          </p>
        )}
        {models?.enabled && check && check.withEnglish < check.lines && (
          <label className="import-model">English by
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {models.list.map((m) => <option key={m} value={m}>{MODEL_LABELS[m] ?? (m.includes('DictaLM') ? MODEL_LABELS.dictalm : m)}</option>)}
            </select>
            {!models.running && <span className="error"> Ollama isn't running: start it from the Start menu, or the English will be left empty.</span>}
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <p>
          <button className="primary" disabled={!ready} onClick={start}>{running ? 'Processing…' : 'Add song'}</button>
          {missing
            ? <span className="hint" data-testid="add-missing"> Still needs {missing}.</span>
            : check?.problems.length
              ? <span className="hint" data-testid="add-missing"> Fix the lyrics problem above first.</span>
              : <span className="hint"> Takes about 3–8 minutes (the English is the slow part). You can leave this page; it keeps going.</span>}
        </p>
      </div>
    </div>
  )
}
