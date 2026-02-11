import os
import sys
import unittest


HERE = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from src.research.district_research import _compute_district_propensity, filter_district_hooks  # noqa: E402


class TestDistrictPropensity(unittest.TestCase):
    def test_propensity_rewards_timebound_authoritative_compliance(self):
        finding = {
            "district_name": "Sample District",
            "finding_type": "compliance",
            "title": "OCR monitoring action",
            "description": "District under OCR monitoring with corrective action milestones.",
            "deadline": "June 15, 2026",
            "amount": "$1.2M",
            "url": "https://state.k12.gov/ocr/sample",
            "why_district_specific": "This district has named milestones and board reporting requirements through SY26.",
        }
        score, reasons = _compute_district_propensity(finding)
        self.assertGreaterEqual(score, 18)
        self.assertIn("active_compliance_trigger", reasons)
        self.assertIn("authoritative_source", reasons)

    def test_passed_hooks_are_sorted_by_propensity(self):
        raw = [
            {
                "district_name": "A",
                "finding_type": "funding",
                "title": "Local levy",
                "description": "Funding opportunity",
                "deadline": "",
                "amount": "",
                "url": "https://example.org/levy",
                "why_district_specific": "A short note",
            },
            {
                "district_name": "B",
                "finding_type": "compliance",
                "title": "District corrective action",
                "description": "Monitoring and corrective action with timeline.",
                "deadline": "July 2026",
                "amount": "$500K",
                "url": "https://state.k12.gov/cap",
                "why_district_specific": "Detailed district-specific obligations and reporting cadence for multilingual learner services.",
            },
        ]
        passed, _filtered = filter_district_hooks(raw, state_hooks=[], product_key="care_coaching")
        self.assertGreaterEqual(len(passed), 1)
        if len(passed) >= 2:
            self.assertGreaterEqual(int(passed[0].get("propensity_score") or 0), int(passed[1].get("propensity_score") or 0))


if __name__ == "__main__":
    unittest.main()

