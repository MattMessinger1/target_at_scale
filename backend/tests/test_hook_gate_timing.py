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
    gate_treasure_hooks,
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

    def test_consolidation_preserves_enriched_metadata(self):
        hook_a = WebHook(
            hook_type="monitoring",
            quote="District A is under CSI status.",
            link="https://example.k12.wa.us/csi",
            trigger_excerpt="State monitoring CAP required by March 31, 2026.",
            eligibility_excerpt="District A Public Schools",
            why_relevant="This creates a compliance urgency that coaching can directly address.",
            confidence="high",
            source_quality_reason="state guidance",
            timing_summary="Action needed by March 31, 2026",
            deadline_date="2026-03-31",
        )
        hook_b = WebHook(
            hook_type="monitoring",
            quote="District B is under ATSI status.",
            link="https://example.k12.wa.us/atsi",
            trigger_excerpt="State monitoring and corrective action plan in effect.",
            eligibility_excerpt="District B Public Schools",
            why_relevant="District teams need implementation support to satisfy CAP milestones.",
            confidence="high",
            source_quality_reason="state guidance",
            timing_summary="Monitoring window active through May 2026",
            deadline_date="2026-05-15",
        )

        kept, _filtered, report = gate_treasure_hooks([hook_a, hook_b])
        self.assertEqual(report.kept, 1)
        self.assertEqual(len(kept), 1)
        merged = kept[0]
        self.assertIsNotNone(merged.timing_score)
        self.assertIsNotNone(merged.signal_strength)
        self.assertIn(merged.timing_bucket, ("near_term", "ongoing", "future", "unknown"))
