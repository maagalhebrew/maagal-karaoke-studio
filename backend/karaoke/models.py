"""The AI models the pipeline uses, in one place (stages.py, tests/m0_check.py; the model manager in M11).

Timing (Whisper, CTranslate2 builds run by faster-whisper) is per language: the ivrit.ai model is tuned on Hebrew
and weaker in other languages, so Spanish uses the original multilingual turbo model. The Spanish id is the one
faster-whisper 1.2 itself maps "large-v3-turbo" to.
"""
from .text import check_language

DEMUCS = "htdemucs"
WHISPER = {
    "he": "ivrit-ai/whisper-large-v3-turbo-ct2",
    "es": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


def whisper_for(language: str) -> str:
    return WHISPER[check_language(language)]
