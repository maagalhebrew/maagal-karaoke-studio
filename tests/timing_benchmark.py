"""Score offline word timing from independently annotated spans and a candidate run.

Run this file with two JSON paths, annotations first, as detailed in score().
The CLI writes its report to stdout. Exit 1 means a measured threshold failed
or could not be evaluated, and exit 2 means the supplied data was invalid.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path


RECORDING_TYPES = ("solo", "choir", "live")
LIMITS_MS = {"median": 250, "p90": 600}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _indexed(rows, location):
    _require(isinstance(rows, list), f"{location} must be a list")
    index = {}
    for row in rows:
        _require(isinstance(row, dict), f"{location} must contain objects")
        row_id = row.get("id")
        _require(isinstance(row_id, str) and bool(row_id.strip()), f"{location} has a missing ID")
        _require(row_id not in index, f"{location} has duplicate ID {row_id}")
        index[row_id] = row
    return index


def _check_span(row, duration, location):
    start, end = row["startMs"], row["endMs"]
    _require(type(start) is int and type(end) is int and 0 <= start < end <= duration,
             f"{location} must have an integer span within the recording")
    return start, end


def _positive_integer(value, location):
    _require(type(value) is int and value > 0, f"{location} must be a positive integer")


def _text(value, location):
    _require(isinstance(value, str) and bool(value.strip()), f"{location} must be a nonempty string")


def _coverage(numerator, denominator):
    return {"count": numerator, "total": denominator, "fraction": numerator / denominator if denominator else None}


def _errors(values):
    if not values:
        return {"median": None, "p90": None}
    return {"median": statistics.median(values), "p90": sorted(values)[math.ceil(.9 * len(values)) - 1]}


def _stats(rows):
    starts = [value for row in rows for value in row["startErrors"]]
    ends = [value for row in rows for value in row["endErrors"]]
    onset = _errors(starts)
    return {
        "recordings": len(rows),
        "highlightedWords": _coverage(len(starts), sum(row["totalWords"] for row in rows)),
        "lineFallback": _coverage(sum(row["fallbackLines"] for row in rows), sum(row["totalLines"] for row in rows)),
        "absoluteWordStartErrorMs": onset,
        "absoluteWordEndErrorMs": _errors(ends),
        "timingThresholdsMet": bool(starts) and all(onset[key] <= limit for key, limit in LIMITS_MS.items()),
    }


def _score_recording(reference, candidate):
    recording_id = reference["id"]
    kind = reference["recordingType"]
    _require(kind in RECORDING_TYPES, f"{recording_id} has an invalid recordingType")
    duration = reference["durationMs"]
    _positive_integer(duration, f"{recording_id} durationMs")
    runtime = candidate["runtimeSeconds"]
    _require(type(runtime) in (int, float) and 0 < runtime < math.inf,
             f"{recording_id} runtimeSeconds must be finite and positive")
    peak = candidate["peakMemoryBytes"]
    _positive_integer(peak, f"{recording_id} peakMemoryBytes")
    expected = _indexed(reference["lines"], f"{recording_id} annotations")
    predicted = _indexed(candidate["lines"], f"{recording_id} predictions")
    _require(expected and expected.keys() == predicted.keys(), f"{recording_id} needs a prediction mode for each annotated line")
    starts, ends, all_word_ids = [], [], set()
    fallback_lines = 0
    for line_id, line in expected.items():
        location = f"{recording_id}/{line_id}"
        gold_words = _indexed(line["words"], f"{location} annotated words")
        _require(gold_words and not all_word_ids.intersection(gold_words),
                 f"{location} needs annotated words with unique IDs across the recording")
        all_word_ids.update(gold_words)
        gold_spans = {word_id: _check_span(word, duration, f"{location}/{word_id} annotation")
                      for word_id, word in gold_words.items()}
        prediction = predicted[line_id]
        mode = prediction["mode"]
        words = _indexed(prediction["words"], f"{location} predicted words")
        _require(mode in ("words", "line", "none") and bool(words) == (mode == "words"),
                 f"{location} needs words for word mode and an empty word list otherwise")
        _require(words.keys() <= gold_words.keys(), f"{location} has unknown predicted word IDs")
        if mode == "line":
            _check_span(prediction, duration, f"{location} fallback")
            fallback_lines += 1
        for word_id, word in words.items():
            predicted_start, predicted_end = _check_span(word, duration, f"{location}/{word_id} prediction")
            gold_start, gold_end = gold_spans[word_id]
            starts.append(abs(predicted_start - gold_start))
            ends.append(abs(predicted_end - gold_end))
    return {
        "id": recording_id,
        "recordingType": kind,
        "durationMs": duration,
        "runtimeSeconds": runtime,
        "realTimeFactor": runtime / (duration / 1000),
        "peakMemoryBytes": peak,
        "startErrors": starts,
        "endErrors": ends,
        "totalWords": len(all_word_ids),
        "totalLines": len(expected),
        "fallbackLines": fallback_lines,
    }


def score(annotations, predictions):
    """Join recordings, lines, and words by stable IDs and score absolute onset error.

    Annotation JSON has datasetKind (annotated or synthetic) and recordings.
    Each recording has id, recordingType, durationMs and lines with id and words.
    All words have id, startMs and endMs. Use independently labeled timestamps.

    Prediction JSON has candidate, hardware (os, cpu, ramBytes, optional gpu),
    modelSizeBytes and recordings. Each recording has id, runtimeSeconds,
    peakMemoryBytes and lines with id, mode (words, line or none) and words.
    For line mode, provide startMs and endMs on the line and use an empty words
    list. None mode uses an empty list and counts only in the denominators.
    Resource measurements describe the candidate run and are supplied by the
    caller. The scorer does not load models, audio, or the network.
    """
    kind = annotations["datasetKind"]
    _require(kind in ("annotated", "synthetic"), "datasetKind must be annotated or synthetic")
    expected = _indexed(annotations["recordings"], "annotated recordings")
    predicted = _indexed(predictions["recordings"], "predicted recordings")
    _require(expected and expected.keys() == predicted.keys(), "predicted recording IDs must match the annotations")
    _text(predictions["candidate"], "candidate")
    hardware = predictions["hardware"]
    _text(hardware["os"], "hardware.os")
    _text(hardware["cpu"], "hardware.cpu")
    _positive_integer(hardware["ramBytes"], "hardware.ramBytes")
    if "gpu" in hardware:
        _text(hardware["gpu"], "hardware.gpu")
    _positive_integer(predictions["modelSizeBytes"], "modelSizeBytes")

    rows = [_score_recording(recording, predicted[recording_id]) for recording_id, recording in expected.items()]
    overall = _stats(rows)
    by_type = {kind: _stats([row for row in rows if row["recordingType"] == kind]) for kind in RECORDING_TYPES}
    missing_types = [kind for kind, stats in by_type.items() if not stats["recordings"]]
    per_recording = [
        {
            **{key: row[key] for key in ("id", "recordingType", "durationMs", "runtimeSeconds", "realTimeFactor", "peakMemoryBytes")},
            **_stats([row]),
        }
        for row in rows
    ]
    return {
        "candidate": predictions["candidate"],
        "datasetKind": kind,
        "hardware": hardware,
        "modelSizeBytes": predictions["modelSizeBytes"],
        "wordStartErrorLimitsMs": LIMITS_MS,
        "overall": overall,
        "byRecordingType": by_type,
        "missingRecordingTypes": missing_types,
        "recordings": per_recording,
        "meetsTimingTargets": overall["timingThresholdsMet"] and not missing_types,
        "measuredTimingTargetsMet": kind == "annotated" and overall["timingThresholdsMet"] and not missing_types,
    }


def _read(path):
    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, f"{path} contains duplicate key {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", type=Path)
    parser.add_argument("predictions", type=Path)
    args = parser.parse_args()
    try:
        result = score(_read(args.annotations), _read(args.predictions))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(2, f"Invalid benchmark input: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0 if result["meetsTimingTargets"] else 1


if __name__ == "__main__":
    sys.exit(main())
