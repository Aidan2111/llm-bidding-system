import unittest

from llm_bidding.calibration import brier_score, calibration_offset, shrunk_success_rate
from llm_bidding.config import load_config


PARAMS = load_config().calibration


class ShrinkageTests(unittest.TestCase):
    def test_cold_start_is_exactly_neutral(self):
        self.assertEqual(shrunk_success_rate(0, 0, PARAMS), 0.5)

    def test_one_success_moves_above_neutral_but_not_to_one(self):
        rate = shrunk_success_rate(1, 1, PARAMS)
        self.assertGreater(rate, 0.5)
        self.assertLess(rate, 1.0)
        self.assertAlmostEqual(rate, (1 + 4 * 0.5) / (1 + 4))

    def test_many_failures_approach_zero(self):
        rate = shrunk_success_rate(0, 100, PARAMS)
        self.assertLess(rate, 0.05)


class CalibrationOffsetTests(unittest.TestCase):
    def test_no_offset_below_min_samples(self):
        pairs = [(0.9, False), (0.9, False)]
        self.assertEqual(calibration_offset(pairs, PARAMS), 0.0)

    def test_overconfidence_produces_negative_offset(self):
        pairs = [(0.9, False)] * 3
        offset = calibration_offset(pairs, PARAMS)
        self.assertLess(offset, 0.0)

    def test_offset_is_clamped(self):
        pairs = [(1.0, False)] * 10
        self.assertEqual(calibration_offset(pairs, PARAMS), -PARAMS.max_calibration_shift)
        pairs = [(0.0, True)] * 10
        self.assertEqual(calibration_offset(pairs, PARAMS), PARAMS.max_calibration_shift)


class BrierTests(unittest.TestCase):
    def test_none_without_data(self):
        self.assertIsNone(brier_score([]))

    def test_perfect_calibration_is_zero(self):
        self.assertEqual(brier_score([(1.0, True), (0.0, False)]), 0.0)

    def test_worst_case_is_one(self):
        self.assertEqual(brier_score([(1.0, False), (0.0, True)]), 1.0)


if __name__ == "__main__":
    unittest.main()
