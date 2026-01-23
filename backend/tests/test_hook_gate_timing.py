import os
import sys
import unittest
from datetime import date


# Ensure `backend/` is on sys.path so `import src...` works when running from repo root.
HERE = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from src.pipeline.hook_gate import (  # noqa: E402
    compute_buying_intent,
    compute_stale_metadata,
    compute_timing_metadata,
)
from src.pipeline.schemas import WebHook  # noqa: E402


class TestHookGateTiming(unittest.TestCase):
    def _base_hook(self, **overrides):
        data = dict(
            hook_type="deadline",
            quote="Applications due by March 31, 2026.",
            link="https://example.com/grant",
            trigger_excerpt="Applications due by March 31, 2026.",
            eligibility_excerpt=None,
            why_relevant="Relevant to coaching cycles.",
            confidence="high",
            source_quality_reason="Status: active",
        )
        data.update(overrides)
        return WebHook(**data)

    def test_compute_timing_metadata_near_term(self):
        hook = self._base_hook(deadline_date="2026-03-31")
        timing = compute_timing_metadata(hook, today=date(2026, 1, 15))
        self.assertEqual(timing["timing_bucket"], "near_term")
        self.assertGreaterEqual(timing["timing_score"], 8)

    def test_compute_buying_intent_rfp(self):
        hook = self._base_hook(trigger_excerpt="RFP closes March 31, 2026 for EL services.")
        signal = compute_buying_intent(hook)
        self.assertEqual(signal["signal_type"], "rfp_open")
        self.assertIsNotNone(signal["signal_summary"])

    def test_compute_stale_metadata_expired(self):
        hook = self._base_hook()
        stale = compute_stale_metadata(hook, timing_bucket="expired", timing_confidence="high")
        self.assertEqual(stale["stale_score"], 100)
        self.assertEqual(stale["stale_reason"], "deadline_passed")
