// Mirrors backend/karaoke/song.schema.json. Times are integer milliseconds.
export interface Word {
  id: string
  plain: string // as written (vowel points kept if the lyrics had them)
  startMs: number
  endMs: number
  confidence: number
  flags: string[]
}

export interface Line { id: string; english: string; words: Word[] }

/** Lyrics compared with what Whisper heard: words possibly missing from the lyrics, or not sung. */
export interface Suggestion {
  key: string
  type: 'missing' | 'unheard'
  lineId: string
  wordId: string
  side?: 'before' | 'after'
  text: string
  startMs: number
  endMs: number
}
export interface Suggestions { available: boolean; suggestions: Suggestion[] }

/** Word-by-word breakdown of one line (local model, cached per line). */
export interface Breakdown {
  literal: string
  model: string
  words: { word: string; parts: { hebrew: string; english: string }[]; english: string; note: string }[]
}

export type SectionKind = 'verse' | 'chorus' | 'bridge' | 'intro' | 'outro' | 'transition' | 'custom'
export interface Section { id: string; kind: SectionKind; label: string; fromLine: string; toLine: string; color?: string }

export interface Clip { id: string; name: string; fromWord: string; toWord: string; padBeforeMs: number; padAfterMs: number }

export type Tier = 'lyrics' | 'en'
export interface ClipStep {
  type: 'clip'
  clip: string
  repeats: number // 1-10
  speed: number // 0.5-1
  track: Track
  yourTurn: boolean
  tiers: Tier[]
}
export interface CardStep { type: 'card'; text: string; durationMs: number }
export type DrillStep = ClipStep | CardStep
export interface Drill { id: string; name: string; steps: DrillStep[] }

export type Language = 'he' | 'es'

export interface Song {
  schema: 2
  song: {
    id: string
    title: string
    artist: string
    language: Language
    permissionId: number | null
    audio: { original: string; vocals: string; instrumental: string }
    durationMs: number
  }
  lines: Line[]
  sections: Section[]
  clips: Clip[]
  drills: Drill[]
}

export type Stage = 'add-english' | 'make-drills' | 'export' | 'exported'
export interface SongStatus { stage: Stage; englishLines: number; lines: number; drills: number; sections: number; exported: boolean }
export interface SongSummary {
  id: string; title: string; artist: string; durationMs: number; words: number; flaggedWords: number
  status: SongStatus; permission: string; favorite: boolean; folders: number[]; addedAt: string
  practice: PracticeSummary
  learning: LearningStats
}
export interface LearningStats {
  forms: number; newToYou: number; inOtherSongs: number; wpm: number; difficulty: number
  mastery: number; rated: number; lines: number; know: number; shaky: number; dontKnow: number
  lastStudied: string | null; dueDay: string | null
}
export interface SongLearning extends LearningStats { ratings: Record<string, number>; newWordIds: string[] }
export interface PracticeSummary { seconds: number; practiceSeconds: number; lastDay: string | null; days: number }
export interface PracticeLog { seconds: number; days: { day: string; seconds: number }[]; lineLoops: Record<string, number> }
export interface Folder { id: number; name: string; count: number }
export interface Peaks { peaksPerSecond: number; duration: number; peaks: number[] }
export type Track = 'original' | 'vocals' | 'instrumental'

export const PERMISSION_STATUSES = ['Not asked', 'Asked', 'Follow-up due', 'Granted', 'Declined', 'No answer'] as const
export type PermissionStatus = (typeof PERMISSION_STATUSES)[number]

/** One row of the permissions tracker (data/karaoke.db), with the song title and the filled-in request draft. */
export interface Permission {
  song_id: string
  title: string
  artist: string
  contact_name: string
  contact_channel: string
  contact_handle: string
  asked_on: string | null
  follow_up_on: string | null
  status: PermissionStatus
  scope: string
  reply_path: string
  updated_at: string | null
  draft: string
}


export interface LyricsCheck {
  sections: number
  lines: number
  lyricLines: number
  language: Language
  words: number
  withEnglish: number
  sectionLabels: string[]
  problems: string[]
}

export type StepState = 'waiting' | 'running' | 'done' | 'failed'
export interface ImportJob {
  slug: string
  state: 'running' | 'done' | 'failed'
  error: { step: string; message: string } | null
  note: string | null
  startedAt: number
  lyrics: LyricsCheck
  steps: { name: string; state: StepState; seconds: number | null }[]
}
