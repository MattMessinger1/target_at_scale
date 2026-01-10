import os
import sys
import unittest


HERE = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from src.pipeline.schemas import ValidationFailure, ValidationResult  # noqa: E402
from src.pipeline.stages.repair import (  # noqa: E402
    failure_codes,
    failures_to_instructions,
    is_regression,
    same_failures,
    should_stop_repair,
)


class TestPipelineRepair(unittest.TestCase):
    def test_failure_signature_stable(self):
        v = ValidationResult(
            passed=False,
            failures=[
                ValidationFailure(code="b", message=""),
                ValidationFailure(code="a", message=""),
                ValidationFailure(code="a", message="dup"),
            ],
            word_count=0,
            bullet_count=0,
            bullet_word_counts=[],
        )
        self.assertEqual(failure_codes(v), ["a", "b"])

    def test_same_failures(self):
        v1 = ValidationResult(passed=False, failures=[ValidationFailure(code="x", message="")], word_count=0, bullet_count=0, bullet_word_counts=[])
        v2 = ValidationResult(passed=False, failures=[ValidationFailure(code="x", message="")], word_count=0, bullet_count=0, bullet_word_counts=[])
        self.assertTrue(same_failures(v1, v2))

    def test_regression_detected(self):
        prev = ValidationResult(passed=False, failures=[ValidationFailure(code="x", message="")], word_count=0, bullet_count=0, bullet_word_counts=[])
        nxt = ValidationResult(
            passed=False,
            failures=[ValidationFailure(code="x", message=""), ValidationFailure(code="y", message="new")],
            word_count=0,
            bullet_count=0,
            bullet_word_counts=[],
        )
        self.assertTrue(is_regression(prev, nxt))
        stop, reason = should_stop_repair(prev, nxt)
        self.assertTrue(stop)
        self.assertEqual(reason, "repair_regressed_new_failures")

    def test_repeat_failures_stop(self):
        prev = ValidationResult(passed=False, failures=[ValidationFailure(code="x", message="")], word_count=0, bullet_count=0, bullet_word_counts=[])
        nxt = ValidationResult(passed=False, failures=[ValidationFailure(code="x", message="again")], word_count=0, bullet_count=0, bullet_word_counts=[])
        stop, reason = should_stop_repair(prev, nxt)
        self.assertTrue(stop)
        self.assertEqual(reason, "repair_failed_same_reasons")

    def test_failure_instructions(self):
        failures = [
            ValidationFailure(code="bullet_too_long", message=""),
            ValidationFailure(code="missing_micro_offer_cta", message=""),
        ]
        ins = failures_to_instructions(failures)
        self.assertTrue(any("2-3 bullets" in x for x in ins))
        self.assertTrue(any("micro-offer" in x.lower() for x in ins))


if __name__ == "__main__":
    unittest.main()

