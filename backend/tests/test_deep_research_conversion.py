import asyncio
import os
import sys
import unittest


HERE = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from src.research.deep_research import convert_to_webhooks  # noqa: E402


class TestDeepResearchConversion(unittest.TestCase):
    def test_compliance_deadline_uses_iso_fields(self):
        results = {
            "funding_items": [],
            "compliance_items": [
                {
                    "title": "Monitoring window",
                    "description": "District must complete monitoring actions.",
                    "type": "monitoring",
                    "districts_affected": ["Sample District"],
                    "deadline": "Action needed by Spring 2026",
                    "effective_date": "2026-02-01",
                    "review_window": "Spring 2026",
                    "timing_type": "monitoring_window",
                    "timing_summary": "Monitoring window active through May 2026",
                    "status": "active",
                    "url": "https://example.gov/monitoring",
                    "relevance_to_product": "Coaching supports corrective actions.",
                }
            ],
            "state_interventions": [],
        }

        hooks = asyncio.run(convert_to_webhooks(results, "care_coaching"))
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0].get("deadline_date"), "2026-02-01")


if __name__ == "__main__":
    unittest.main()

