import os
import sys
import unittest


# Ensure `backend/` is on sys.path so `import src...` works when running from repo root.
HERE = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from src.pipeline.schemas import (  # noqa: E402
    ClaimsMapEntry,
    EvidenceChunkCitation,
    EvidencePack,
    SelectedHook,
    WebHook,
)
from src.pipeline.stages.validator import validate_email_draft  # noqa: E402


class TestPipelineValidator(unittest.TestCase):
    def _base_objects(self):
        evidence = EvidencePack(
            product="CARE Coaching",
            product_key="care_coaching",
            state="FL",
            retrieved_chunks=[
                EvidenceChunkCitation(
                    chunk_id="kb-1_chunk_0",
                    source_kb_id="kb-1",
                    title="CARE Coaching overview",
                    excerpt="CARE Coaching provides job-embedded coaching cycles and artifacts.",
                    category="product",
                    subcategory="care_coaching",
                    product_name="care_coaching",
                    applicable_states=["FL"],
                    chunk_index=0,
                    total_chunks=2,
                )
            ],
            micro_offer_candidates=[],
            supplemental_brief=None,
        )

        hook = WebHook(
            hook_type="deadline",
            quote="By March 31, FY26 EL plan updates are due.",
            link="https://example.com/state-guidance",
            trigger_excerpt="Districts must submit updates by March 31 for FY26.",
            eligibility_excerpt=None,
            why_relevant="A concrete deadline districts plan around.",
            confidence="high",
            source_quality_reason="State guidance page",
        )

        selected = SelectedHook(hook=hook, rank=1, reasons=["deadline in state guidance"])
        return evidence, hook, selected

    def _long_context_paragraph(self) -> str:
        # ~55–70 words, used to hit the 110–150 word validator window
        return (
            "Many districts are updating EL plans while keeping implementation realistic for schools. "
            "CARE Coaching gives a job-embedded structure: coaching cycles, practical tools, and documentation artifacts "
            "that align to your priorities. Teams leave with clear next steps and an evidence trail you can reuse "
            "for internal reviews, reporting, and budget narratives. "
            "This is designed to fit into existing PLCs and coaching routines, not add a new program to manage. "
            "If helpful, we can tailor the artifacts to the language in your FY26 submission."
        )

    def test_valid_email_passes(self):
        evidence, hook, selected = self._base_objects()

        subject_line = "March 31 FY26 EL plan updates"
        email_body = "\n\n".join(
            [
                "By March 31, FY26 EL plan updates are due — so districts are locking in documentation now.",
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft you can adapt? If it's easier, happy to talk for 15 minutes: calendly.com/wceps",
            ]
        )

        claims = [
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text="By March 31, FY26 EL plan updates are due — so districts are locking in documentation now.",
                kb_chunk_ids=[],
                urls=[hook.link],
            ),
            ClaimsMapEntry(
                claim_kind="deliverable_bullet",
                claim_text="Coaching cycles aligned to priorities",
                kb_chunk_ids=["kb-1_chunk_0"],
                urls=[],
            ),
            ClaimsMapEntry(
                claim_kind="deliverable_bullet",
                claim_text="Evidence checklist for documentation",
                kb_chunk_ids=["kb-1_chunk_0"],
                urls=[],
            ),
            ClaimsMapEntry(
                claim_kind="deliverable_bullet",
                claim_text="1-page budget narrative draft",
                kb_chunk_ids=["kb-1_chunk_0"],
                urls=[],
            ),
        ]

        result = validate_email_draft(
            subject_line=subject_line,
            email_body=email_body,
            selected_hook=selected,
            claims_map=claims,
            evidence_pack=evidence,
            treasure_hooks=[hook],
        )

        self.assertTrue(result.passed, msg=[f.code for f in result.failures])

    def test_missing_micro_offer_fails(self):
        evidence, hook, selected = self._base_objects()
        subject_line = "March 31 FY26 EL plan updates"
        email_body = "\n\n".join(
            [
                "By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- Budget narrative draft",
                "If it's easier, happy to talk for 15 minutes: calendly.com/wceps",
            ]
        )
        claims = [
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text="By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                urls=[hook.link],
                kb_chunk_ids=[],
            ),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Coaching cycles aligned to priorities", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Evidence checklist for documentation", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Budget narrative draft", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
        ]
        result = validate_email_draft(
            subject_line=subject_line,
            email_body=email_body,
            selected_hook=selected,
            claims_map=claims,
            evidence_pack=evidence,
            treasure_hooks=[hook],
        )
        self.assertFalse(result.passed)
        self.assertIn("missing_micro_offer_cta", [f.code for f in result.failures])

    def test_missing_trigger_in_opener_fails(self):
        evidence, hook, selected = self._base_objects()
        subject_line = "March 31 FY26 EL plan updates"
        email_body = "\n\n".join(
            [
                "EL plan updates are coming up, and documentation adds up quickly.",  # missing date/FY token
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft? If it's easier, happy to talk for 15 minutes: calendly.com/wceps",
            ]
        )
        claims = [
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text="EL plan updates are coming up, and documentation adds up quickly.",
                urls=[hook.link],
                kb_chunk_ids=[],
            ),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Coaching cycles aligned to priorities", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Evidence checklist for documentation", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="1-page budget narrative draft", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
        ]
        result = validate_email_draft(
            subject_line=subject_line,
            email_body=email_body,
            selected_hook=selected,
            claims_map=claims,
            evidence_pack=evidence,
            treasure_hooks=[hook],
        )
        self.assertFalse(result.passed)
        self.assertIn("missing_or_unsourced_trigger", [f.code for f in result.failures])

    def test_bullet_word_limit_enforced(self):
        evidence, hook, selected = self._base_objects()
        subject_line = "March 31 FY26 EL plan updates"
        email_body = "\n\n".join(
            [
                "By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                self._long_context_paragraph(),
                "- This bullet has definitely more than ten words total right now",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft? If it's easier, happy to talk for 15 minutes: calendly.com/wceps",
            ]
        )
        claims = [
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text="By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                urls=[hook.link],
                kb_chunk_ids=[],
            ),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="This bullet has definitely more than ten words total right now", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Evidence checklist for documentation", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="1-page budget narrative draft", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
        ]
        result = validate_email_draft(
            subject_line=subject_line,
            email_body=email_body,
            selected_hook=selected,
            claims_map=claims,
            evidence_pack=evidence,
            treasure_hooks=[hook],
        )
        self.assertFalse(result.passed)
        self.assertIn("bullet_too_long", [f.code for f in result.failures])

    def test_funding_requires_eligibility_excerpt(self):
        evidence, hook, selected = self._base_objects()
        subject_line = "March 31 FY26 EL plan updates"
        # funding claim cites the hook URL, but hook eligibility_excerpt is None -> fail
        email_body = "\n\n".join(
            [
                "By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft? If it's easier, happy to talk for 15 minutes: calendly.com/wceps",
            ]
        )
        claims = [
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text="By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                urls=[hook.link],
                kb_chunk_ids=[],
            ),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Coaching cycles aligned to priorities", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Evidence checklist for documentation", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="1-page budget narrative draft", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="funding", claim_text="This grant can fund PD support.", urls=[hook.link], kb_chunk_ids=[]),
        ]
        result = validate_email_draft(
            subject_line=subject_line,
            email_body=email_body,
            selected_hook=selected,
            claims_map=claims,
            evidence_pack=evidence,
            treasure_hooks=[hook],
        )
        self.assertFalse(result.passed)
        self.assertIn("funding_missing_eligibility_excerpt", [f.code for f in result.failures])

    def test_offering_phrase_required_when_present(self):
        evidence, hook, selected = self._base_objects()
        # Turn on offering enforcement via supplemental_brief
        evidence.supplemental_brief = {
            "offerings": ["Job-embedded coaching cycles aligned to district priorities"]
        }
        subject_line = "March 31 FY26 EL plan updates"
        email_body = "\n\n".join(
            [
                "By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft? If it's easier, happy to talk for 15 minutes: calendly.com/wceps",
            ]
        )
        claims = [
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text="By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                urls=[hook.link],
                kb_chunk_ids=[],
            ),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Coaching cycles aligned to priorities", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Evidence checklist for documentation", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="1-page budget narrative draft", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
        ]
        result = validate_email_draft(
            subject_line=subject_line,
            email_body=email_body,
            selected_hook=selected,
            claims_map=claims,
            evidence_pack=evidence,
            treasure_hooks=[hook],
        )
        self.assertFalse(result.passed)
        self.assertIn("missing_product_offering_phrase", [f.code for f in result.failures])

    def test_secondary_hook_required_when_provided(self):
        evidence, hook, selected = self._base_objects()

        secondary_hook = WebHook(
            hook_type="monitoring",
            quote="Districts may be selected for monitoring this spring.",
            link="https://example.com/monitoring",
            trigger_excerpt="The state will conduct monitoring this spring.",
            eligibility_excerpt=None,
            why_relevant="Monitoring language creates impetus to tighten documentation and routines.",
            confidence="high",
            source_quality_reason="State monitoring page",
        )
        secondary_selected = SelectedHook(hook=secondary_hook, rank=2, reasons=["human_selected_secondary"])

        subject_line = "March 31 FY26 EL plan updates"
        email_body = "\n\n".join(
            [
                "By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                "Separately, districts may be selected for monitoring this spring, so artifacts matter.",
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft? If it's easier, happy to talk for 15 minutes: calendly.com/wceps",
            ]
        )
        claims = [
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text="By March 31, FY26 EL plan updates are due — quick heads up for planning.",
                urls=[hook.link],
                kb_chunk_ids=[],
            ),
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text="Separately, districts may be selected for monitoring this spring, so artifacts matter.",
                urls=[secondary_hook.link],
                kb_chunk_ids=[],
            ),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Coaching cycles aligned to priorities", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="Evidence checklist for documentation", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
            ClaimsMapEntry(claim_kind="deliverable_bullet", claim_text="1-page budget narrative draft", kb_chunk_ids=["kb-1_chunk_0"], urls=[]),
        ]
        result = validate_email_draft(
            subject_line=subject_line,
            email_body=email_body,
            selected_hook=selected,
            secondary_hook=secondary_selected,
            claims_map=claims,
            evidence_pack=evidence,
            treasure_hooks=[hook, secondary_hook],
        )
        self.assertTrue(result.passed, msg=[f.code for f in result.failures])


if __name__ == "__main__":
    unittest.main()

