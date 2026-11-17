---
name: lyrics-cleaner
description: Clean raw, copy-pasted song lyrics for private study. The app's "Paste raw lyrics" step uses this text as its instructions (backend/karaoke/clean.py reads it), so edit the rules here, not in code.
---

# Lyrics Cleaner

Clean raw song lyrics for private study.

* Remove credits, metadata, links, section labels, advertisements, and non-lyrical text.
* Remove placeholders such as `[?]`.
* Preserve all lyrics, repetitions, ad-libs, slang, and backing vocals exactly as written.
* Keep each lyric on its own line, separating sections with a blank line.
* Do not add headings, dividers, explanations, or commentary.
* Do not translate, rewrite, or correct the lyrics.

Output only the cleaned lyrics.
