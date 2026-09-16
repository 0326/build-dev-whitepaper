import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_evals import run


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "evals" / "evals.json"
FIXTURE = ROOT / "evals" / "fixtures" / "example-synthetic-run.json"


class RunEvalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def evaluate(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return run(CATALOG, path)

    def test_valid_fixture_passes_gate(self):
        report = self.evaluate(self.fixture)
        self.assertTrue(report["ok"])
        self.assertEqual(report["variants"]["with_skill"]["pass_rate"], 1.0)
        self.assertEqual(report["variants"]["with_skill"]["evidence_coverage"], 1.0)

    def test_failed_expectation_blocks_gate(self):
        data = copy.deepcopy(self.fixture)
        result = data["variants"]["with_skill"]["cases"][0]["expectation_results"][0]
        result.update(status="fail", reason="The automated assertion failed.")
        report = self.evaluate(data)
        self.assertFalse(report["ok"])
        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["variants"]["with_skill"]["cases"][0]["status"], "failed")

    def test_missing_evidence_is_rejected(self):
        data = copy.deepcopy(self.fixture)
        data["variants"]["with_skill"]["cases"][0]["expectation_results"][0]["evidence"] = []
        report = self.evaluate(data)
        self.assertFalse(report["ok"])
        self.assertTrue(any("require at least one evidence" in error for error in report["errors"]))

    def test_catalog_hash_is_checked(self):
        data = copy.deepcopy(self.fixture)
        data["catalog"]["sha256"] = "0" * 64
        report = self.evaluate(data)
        self.assertFalse(report["ok"])
        self.assertTrue(any("does not match" in error for error in report["errors"]))

    def test_baseline_is_comparable_without_gating(self):
        data = copy.deepcopy(self.fixture)
        baseline = copy.deepcopy(data["variants"]["with_skill"])
        baseline.update(label="without skill", gates=False)
        data["variants"]["without_skill"] = baseline
        report = self.evaluate(data)
        self.assertTrue(report["ok"])
        self.assertIn("without_skill", report["comparison"])


if __name__ == "__main__":
    unittest.main()

