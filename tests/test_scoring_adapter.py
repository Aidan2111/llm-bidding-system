import re
import unittest
from pathlib import Path
from unittest import mock

from llm_bidding import scoring
from llm_bidding.scoring import (
    BANDS,
    EFFORT_BY_BAND,
    RECOMMENDED_MODES,
    ScoringCompatibilityError,
    band_rank,
    detect_scope_drift,
    ensure_compatible,
    score_result_diff,
    score_task_intent,
    scoring_version,
)


SMALL_DIFF = (
    "--- a/views/profile.css\n"
    "+++ b/views/profile.css\n"
    "@@ -1,1 +1,1 @@\n"
    "-old\n"
    "+new\n"
)


class CompatibilityTests(unittest.TestCase):
    def test_real_dependency_is_compatible(self):
        ensure_compatible(force=True)  # must not raise

    def test_missing_attribute_is_detected(self):
        with mock.patch.object(scoring.autonomy_score, "combine_intent_and_diff"):
            del scoring.autonomy_score.combine_intent_and_diff
            try:
                with self.assertRaises(ScoringCompatibilityError) as ctx:
                    ensure_compatible(force=True)
            finally:
                pass
        self.assertIn("combine_intent_and_diff", str(ctx.exception))
        ensure_compatible(force=True)  # restored by patch exit

    def test_unknown_band_from_probe_is_detected(self):
        fake = mock.Mock()
        fake.score = 2
        fake.band = "Mystery Risk"
        with mock.patch.object(
            scoring.autonomy_score, "score_intent", return_value=fake
        ):
            with self.assertRaises(ScoringCompatibilityError) as ctx:
                ensure_compatible(force=True)
        self.assertIn("Mystery Risk", str(ctx.exception))
        ensure_compatible(force=True)

    def test_probe_exception_is_wrapped(self):
        with mock.patch.object(
            scoring.autonomy_score, "score_intent", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(ScoringCompatibilityError):
                ensure_compatible(force=True)
        ensure_compatible(force=True)

    def test_version_is_reported(self):
        self.assertNotEqual(scoring_version(), "")

    def test_band_rank(self):
        self.assertEqual([band_rank(b) for b in BANDS], [0, 1, 2])
        with self.assertRaises(ScoringCompatibilityError):
            band_rank("Mystery Risk")

    def test_constants_are_consistent(self):
        self.assertEqual(set(EFFORT_BY_BAND), set(BANDS))
        self.assertEqual(len(RECOMMENDED_MODES), len(BANDS))


class WrapperTests(unittest.TestCase):
    def test_score_task_intent(self):
        result = score_task_intent("Update the button label text.")
        self.assertIn(result.band, BANDS)
        self.assertIn(result.recommended_mode, RECOMMENDED_MODES)

    def test_score_result_diff(self):
        result = score_result_diff(SMALL_DIFF)
        self.assertIn(result.band, BANDS)
        self.assertGreaterEqual(result.score, 1)


class ScopeDriftTests(unittest.TestCase):
    def test_score_jump_triggers_drift(self):
        self.assertTrue(detect_scope_drift(2, "Low Risk", 5, "Medium Risk"))

    def test_band_escalation_triggers_drift_even_with_small_jump(self):
        self.assertTrue(detect_scope_drift(3, "Low Risk", 4, "Medium Risk"))

    def test_no_drift_within_band_and_below_threshold(self):
        self.assertFalse(detect_scope_drift(4, "Medium Risk", 6, "Medium Risk"))

    def test_no_drift_when_diff_is_safer(self):
        self.assertFalse(detect_scope_drift(8, "High Risk", 2, "Low Risk"))

    def test_threshold_boundary(self):
        self.assertTrue(detect_scope_drift(4, "Medium Risk", 7, "Medium Risk"))
        self.assertFalse(detect_scope_drift(4, "Medium Risk", 6, "Medium Risk"))


class ImportGuardTests(unittest.TestCase):
    """Only scoring.py may import autonomy_score."""

    def test_no_other_module_imports_autonomy_score(self):
        package_dir = Path(__file__).resolve().parent.parent / "src" / "llm_bidding"
        pattern = re.compile(r"^\s*(from|import)\s+autonomy_score", re.MULTILINE)
        offenders = [
            str(path.relative_to(package_dir))
            for path in package_dir.rglob("*.py")
            if path.name != "scoring.py"
            and pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
