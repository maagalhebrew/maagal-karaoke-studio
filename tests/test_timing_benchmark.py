"""Synthetic scorer tests. These fixtures contain no model or recording output."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import timing_benchmark as benchmark


FIXTURE = Path(__file__).with_name("fixtures") / "timing-benchmark-synthetic"


class TimingBenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.annotations = json.loads((FIXTURE / "annotations.json").read_text(encoding="utf-8"))
        self.predictions = json.loads((FIXTURE / "predictions.json").read_text(encoding="utf-8"))

    def test_scores_inclusive_thresholds_and_counts_every_annotated_word_and_line(self):
        result = benchmark.score(self.annotations, self.predictions)
        self.assertEqual(result["overall"]["absoluteWordStartErrorMs"], {"median": 250, "p90": 600})
        self.assertEqual(result["overall"]["absoluteWordEndErrorMs"], {"median": 400, "p90": 700})
        self.assertEqual(result["overall"]["highlightedWords"], {"count": 4, "total": 7, "fraction": 4 / 7})
        self.assertEqual(result["overall"]["lineFallback"], {"count": 2, "total": 6, "fraction": 2 / 6})
        for kind, words, fallback in (("solo", 3, 1), ("choir", 2, 1), ("live", 2, 0)):
            with self.subTest(kind=kind):
                row = result["byRecordingType"][kind]
                self.assertEqual(row["highlightedWords"]["total"], words)
                self.assertEqual(row["lineFallback"], {"count": fallback, "total": 2, "fraction": fallback / 2})
        self.assertEqual([item["realTimeFactor"] for item in result["recordings"]], [0.5, 1.0, 2.0])
        self.assertEqual(result["recordings"][2]["peakMemoryBytes"], 1200000000)
        self.assertEqual(result["modelSizeBytes"], 1600000000)
        self.assertTrue(result["meetsTimingTargets"])
        self.assertFalse(result["measuredTimingTargetsMet"])

    def test_exceeding_threshold_fails(self):
        self.predictions["recordings"][2]["lines"][0]["words"][0]["startMs"] = 1801
        result = benchmark.score(self.annotations, self.predictions)
        self.assertEqual(result["overall"]["absoluteWordStartErrorMs"]["p90"], 601)
        self.assertFalse(result["meetsTimingTargets"])

    def test_missing_type_and_abstention_do_not_report_zero_error(self):
        self.annotations["recordings"].pop()
        self.predictions["recordings"].pop()
        result = benchmark.score(self.annotations, self.predictions)
        self.assertEqual(result["missingRecordingTypes"], ["live"])
        self.assertIsNone(result["byRecordingType"]["live"]["absoluteWordStartErrorMs"]["median"])
        self.assertFalse(result["meetsTimingTargets"])

        for recording in self.predictions["recordings"]:
            for line in recording["lines"]:
                line.update(mode="none", words=[])
        result = benchmark.score(self.annotations, self.predictions)
        self.assertEqual(result["overall"]["highlightedWords"], {"count": 0, "total": 5, "fraction": 0})
        self.assertFalse(result["overall"]["timingThresholdsMet"])

    def test_annotation_rejects_duplicate_word_identity_across_lines(self):
        self.annotations["recordings"][0]["lines"][1]["words"][0]["id"] = "one"
        with self.assertRaisesRegex(ValueError, "unique IDs across the recording"):
            benchmark.score(self.annotations, self.predictions)

    def test_annotation_rejects_span_outside_recording(self):
        self.annotations["recordings"][0]["lines"][0]["words"][0]["endMs"] = 5001
        with self.assertRaisesRegex(ValueError, "integer span within the recording"):
            benchmark.score(self.annotations, self.predictions)

    def test_predictions_reject_unknown_word_and_unreported_line(self):
        lines = self.predictions["recordings"][0]["lines"]
        lines[0]["words"][0]["id"] = "three"
        with self.assertRaisesRegex(ValueError, "unknown predicted word IDs"):
            benchmark.score(self.annotations, self.predictions)
        lines.pop()
        with self.assertRaisesRegex(ValueError, "prediction mode for each annotated line"):
            benchmark.score(self.annotations, self.predictions)

    def test_line_fallback_rejects_empty_span(self):
        line = self.predictions["recordings"][0]["lines"][1]
        line["endMs"] = line["startMs"]
        with self.assertRaisesRegex(ValueError, "fallback must have an integer span"):
            benchmark.score(self.annotations, self.predictions)

    def test_candidate_measurements_reject_invalid_runtime(self):
        self.predictions["recordings"][0]["runtimeSeconds"] = float("nan")
        with self.assertRaisesRegex(ValueError, "runtimeSeconds must be finite and positive"):
            benchmark.score(self.annotations, self.predictions)

    def test_cli_reports_synthetic_status(self):
        result = subprocess.run(
            [sys.executable, str(Path(benchmark.__file__)), str(FIXTURE / "annotations.json"),
             str(FIXTURE / "predictions.json")],
            check=True, capture_output=True, text=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["datasetKind"], "synthetic")
        self.assertFalse(report["measuredTimingTargetsMet"])


if __name__ == "__main__":
    unittest.main()
