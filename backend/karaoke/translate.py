"""English for lyric lines from a local model served by Ollama (localhost only: lyrics never leave the machine).

One request per line, so each English line belongs to exactly one Hebrew line (asking for a list let small
models merge several lines into one entry and pad the rest). Context is only the neighbouring lines: given the
whole song in Hebrew, DictaLM 1.7B copied the Hebrew back on 2 lines in 3; with neighbours only, 1 in 30.
Answers that copy the lyrics back are rejected (for Hebrew: any Hebrew letter). Spanish songs get the same prompt
with the language named. Settings live in data/translate.json (model name, on/off).
"""
import json
import os
import re
import urllib.error
import urllib.request

from . import paths
from .text import LANGUAGES

DEFAULTS = {"enabled": True, "model": "gemma4:12b", "url": "http://127.0.0.1:11434",
            "timeoutSeconds": 120}  # per line (the first one includes loading the model)

PROMPT = """You write English subtitles for Hebrew song lyrics. The reader is learning Hebrew and reads your English
under each Hebrew line to understand exactly what that line says.

You get a few nearby lines of the song for context, and you translate ONE requested line into English.
- Translate only the requested line. Its English covers exactly that line's words: nothing from the lines
  before or after it, nothing added, nothing left out.
- Translate directly and closely. Keep the Hebrew's own words, images and, where English allows, its word order,
  so the reader can match English words to Hebrew words. Use an idiom only when the literal wording would make
  no sense in English.
- Be faithful to the artist. Keep swearing, insults, sexual content, drugs, violence and religious language
  exactly as strong as the Hebrew. Never soften, censor, euphemize, or add judgment.
- Keep names and culture-specific words as they are (Hashem, Breslov, Tel Aviv).
- Answer with English only: no Hebrew, no transliteration, no quotation marks, no notes.
Reply as JSON: {"english_translation": "<the English for the requested line>"}"""

# Same instructions for each language; examples of names to keep as they are.
NAME_EXAMPLES = {"he": "(Hashem, Breslov, Tel Aviv)", "es": "(Dios, Sevilla, Buenos Aires)"}


def prompt_for(language: str = "he") -> str:
    """The system prompt for a song's language (the Hebrew one is PROMPT exactly)."""
    if language == "he":
        return PROMPT
    return PROMPT.replace("Hebrew", LANGUAGES[language]).replace(NAME_EXAMPLES["he"], NAME_EXAMPLES[language])


KEY = "english_translation"
FORMAT = {"type": "object", "required": [KEY], "properties": {KEY: {"type": "string", "minLength": 1, "maxLength": 200}}}
CONTEXT_BEFORE, CONTEXT_AFTER = 2, 1
HEBREW = re.compile(r"[֐-׿]")


class TranslateError(RuntimeError):
    pass


def load_settings() -> dict:
    """data/translate.json over the defaults; KARAOKE_TRANSLATE_MODEL (set by the import page) picks the model."""
    path = paths.DATA / "translate.json"
    s = dict(DEFAULTS)
    if path.exists():
        s.update({k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")})
    if os.environ.get("KARAOKE_TRANSLATE_MODEL"):
        s["model"] = os.environ["KARAOKE_TRANSLATE_MODEL"]
    return s


def installed_models(settings: dict | None = None) -> list[str]:
    """Chat models Ollama has downloaded ([] if Ollama isn't running)."""
    s = settings or load_settings()
    try:
        with urllib.request.urlopen(s["url"].rstrip("/") + "/api/tags", timeout=3) as r:
            return sorted(m["name"] for m in json.loads(r.read().decode("utf-8"))["models"])
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, KeyError):
        return []


def _post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise TranslateError(f"Ollama answered {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise TranslateError(f"Ollama is not reachable at {url.rsplit('/api', 1)[0]} ({e}); is the Ollama app running?") from None


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _length_ok(source: str, english: str) -> bool:
    """Not empty and not far longer than the lyric line (a line that picked up its neighbours)."""
    return 0 < len(english.split()) <= 3 * len(source.split()) + 4


def _copied(source: str, english: str, language: str) -> bool:
    """The answer repeats the lyric line instead of translating it. Hebrew: any Hebrew letter. Spanish shares the
    alphabet with English, so: (almost) every word of the answer is a word of the Spanish line."""
    if language == "he":
        return bool(HEBREW.search(english))
    mine, theirs = _tokens(english), set(_tokens(source))
    return bool(mine) and sum(t in theirs for t in mine) / len(mine) >= 0.8


def plausible(source: str, english: str, language: str = "he") -> bool:
    """Usable English: not far longer than the lyric line, and not the line copied back."""
    return _length_ok(source, english) and not _copied(source, english, language)


def _line(nearby: str, line: str, s: dict, language: str = "he") -> str:
    """English for one line, or "" if the model twice gave an unusable answer.
    Spanish only: when both tries give back the line's own words, the line is kept as it is. It is then names,
    sounds ("oh", "eh") or a phrase already sung in English, so the same words are its English. (For Hebrew an
    answer in Hebrew letters is always wrong.)"""
    name = LANGUAGES[language]
    request = f"Nearby lines ({name}, for context):\n{nearby}\n\n{name} line: {line}\nEnglish translation:"
    copies = []
    for temperature in (0.2, 0.6):  # one retry, a little looser
        body = {"model": s["model"], "stream": False, "think": False, "keep_alive": "2m", "format": FORMAT,
                "options": {"temperature": temperature, "seed": 7, "num_predict": 120},
                "messages": [{"role": "system", "content": prompt_for(language)}, {"role": "user", "content": request}]}
        reply = _post(s["url"].rstrip("/") + "/api/chat", body, s["timeoutSeconds"])
        try:
            english = json.loads(reply["message"]["content"])[KEY].strip().strip('"“”')
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if plausible(line, english, language):
            return english
        if language != "he" and _length_ok(line, english) and _copied(line, english, language):
            copies.append(english)
    return copies[-1] if len(copies) == 2 else ""


def _unload(s: dict):
    """Free the GPU now: Demucs / Whisper need it next (rule 4)."""
    try:
        _post(s["url"].rstrip("/") + "/api/generate", {"model": s["model"], "keep_alive": 0}, 30)
    except TranslateError:
        pass


def translate_lines(hebrew: list[str], settings: dict | None = None, language: str = "he") -> list[str]:
    """One English line per lyric line ("" where the model failed). Identical lines are translated once.
    Raises TranslateError if Ollama can't be reached or nothing could be translated."""
    s = settings or load_settings()
    unique = list(dict.fromkeys(hebrew))
    done: dict[str, str] = {}
    try:
        for i, line in enumerate(unique):
            nearby = "\n".join(unique[max(0, i - CONTEXT_BEFORE):i + 1 + CONTEXT_AFTER])
            done[line] = _line(nearby, line, s, language)
    finally:
        _unload(s)
    if not any(done.values()):
        raise TranslateError(f"model {s['model']} gave no usable English")
    return [done[h] for h in hebrew]


def translate_in_song(hebrew: list[str], targets: list[int], settings: dict | None = None,
                      language: str = "he") -> dict[int, str]:
    """English for some lines of a song, each with its real neighbours as context (after a line split or join).
    Returns {index: english} ("" where the model failed). Raises TranslateError if Ollama can't be reached."""
    s = settings or load_settings()
    if not s["enabled"]:
        raise TranslateError("translation is switched off in data/translate.json")
    try:
        return {i: _line("\n".join(hebrew[max(0, i - CONTEXT_BEFORE):i + 1 + CONTEXT_AFTER]), hebrew[i], s, language)
                for i in targets}
    finally:
        _unload(s)


# --- word-by-word breakdown (editor's Breakdown tab) ------------------------------------------------------------
BREAKDOWN_PROMPT = """You explain Hebrew song lyrics word by word to an English speaker who is learning Hebrew.
For the requested line, go through its words in order, one entry per word, exactly as the words are written.
For each word:
- "parts": split it into its pieces: prefixes (ו and, ה the, ב in, ל to/for, מ from, ש that, כ like), the base word,
  and suffixes (ending pronouns such as ־י my, ־ך your, ־נו our, ־ים plural). Each piece: its Hebrew letters and a
  literal English meaning. A word with no prefix or suffix has one part.
- "english": the literal meaning of the whole word in context, in a few English words.
- "note": optional, very short: the root or dictionary form, slang meaning, or grammar (tense, person). "" if none.
Then "literal": the whole line translated word for word, keeping the Hebrew order.
Be direct and faithful: keep swearing, sexual content, drugs and violence as strong as the Hebrew; never soften.
English text must contain no Hebrew letters except inside "parts" -> "hebrew"."""


def _breakdown_format(n: int) -> dict:
    part = {"type": "object", "required": ["hebrew", "english"],
            "properties": {"hebrew": {"type": "string", "maxLength": 30}, "english": {"type": "string", "maxLength": 60}}}
    word = {"type": "object", "required": ["word", "parts", "english", "note"],
            "properties": {"word": {"type": "string", "maxLength": 40},
                           "parts": {"type": "array", "minItems": 1, "maxItems": 5, "items": part},
                           "english": {"type": "string", "minLength": 1, "maxLength": 80},
                           "note": {"type": "string", "maxLength": 120}}}
    return {"type": "object", "required": ["words", "literal"],
            "properties": {"words": {"type": "array", "minItems": n, "maxItems": n, "items": word},
                           "literal": {"type": "string", "minLength": 1, "maxLength": 300}}}


def breakdown_line(words: list[str], nearby: str = "", settings: dict | None = None, unload: bool = False) -> dict:
    """{"words": [{"word", "parts": [{"hebrew", "english"}], "english", "note"}], "literal"} for one lyric line.
    The model stays loaded briefly so the next click is quick. Raises TranslateError."""
    s = settings or load_settings()
    line = " ".join(words)
    numbered = "\n".join(f"{i}. {w}" for i, w in enumerate(words, 1))
    request = (f"Nearby lines (context):\n{nearby}\n\n" if nearby else "") + \
        f"Line: {line}\nIts words, in order:\n{numbered}\nBreak down each of these {len(words)} words."
    body = {"model": s["model"], "stream": False, "think": False, "keep_alive": 0 if unload else "1m",
            "format": _breakdown_format(len(words)),
            "options": {"temperature": 0.2, "seed": 7, "num_predict": 120 * len(words) + 120},
            "messages": [{"role": "system", "content": BREAKDOWN_PROMPT}, {"role": "user", "content": request}]}
    for _ in range(2):
        reply = _post(s["url"].rstrip("/") + "/api/chat", body, s["timeoutSeconds"] * 2)
        try:
            out = json.loads(reply["message"]["content"])
            got = out["words"]
        except (KeyError, TypeError, ValueError):
            continue
        english_ok = all(not HEBREW.search(w["english"]) for w in got) and not HEBREW.search(out["literal"])
        if len(got) == len(words) and english_ok:
            for w, original in zip(got, words):
                w["word"] = original  # the lyric's own spelling, whatever the model echoed
            return {"words": got, "literal": out["literal"].strip(), "model": s["model"]}
    raise TranslateError(f"model {s['model']} gave no usable breakdown")
