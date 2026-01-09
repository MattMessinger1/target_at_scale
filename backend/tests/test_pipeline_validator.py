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

        subject_line = "FY26 EL plan updates: due by March 31"
        opener = "FY26 EL plan updates are due by March 31."
        email_body = "\n\n".join(
            [
                # No URLs printed; paraphrase is OK as long as opener contains a sourced trigger token.
                opener,
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft you can adapt? Where should I route it?",
            ]
        )

        claims = [
            ClaimsMapEntry(
                claim_kind="hook",
                claim_text=opener,
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
        subject_line = "FY26 update: March 31 deadline"
        opener = "FY26 updates must be submitted by March 31."
        email_body = "\n\n".join(
            [
                opener,
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- Budget narrative draft",
                "Thanks for your time.",
            ]
        )
        claims = [
            ClaimsMapEntry(claim_kind="hook", claim_text=opener, urls=[hook.link], kb_chunk_ids=[]),
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

    def test_email_must_not_print_urls(self):
        evidence, hook, selected = self._base_objects()
        subject_line = "FY26 EL plan updates: March 31"
        opener = f"FY26 EL plan updates are due soon. ({hook.link})"
        email_body = "\n\n".join(
            [
                opener,  # URL printed -> fail
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft?",
            ]
        )
        claims = [
            ClaimsMapEntry(claim_kind="hook", claim_text=opener, urls=[hook.link], kb_chunk_ids=[]),
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
        self.assertIn("email_contains_url", [f.code for f in result.failures])

    def test_bullet_word_limit_enforced(self):
        evidence, hook, selected = self._base_objects()
        subject_line = "FY26 EL updates due March 31"
        opener = "FY26 updates must be submitted by March 31."
        email_body = "\n\n".join(
            [
                opener,
                self._long_context_paragraph(),
                "- This bullet has definitely more than ten words total right now",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft?",
            ]
        )
        claims = [
            ClaimsMapEntry(claim_kind="hook", claim_text=opener, urls=[hook.link], kb_chunk_ids=[]),
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
        # funding claim cites the hook URL, but hook eligibility_excerpt is None -> fail
        subject_line = "FY26 updates due March 31"
        opener = "FY26 updates must be submitted by March 31."
        email_body = "\n\n".join(
            [
                opener,
                self._long_context_paragraph(),
                "- Coaching cycles aligned to priorities",
                "- Evidence checklist for documentation",
                "- 1-page budget narrative draft",
                "Would it help if I sent a 1-page budget narrative draft?",
            ]
        )
        claims = [
            ClaimsMapEntry(claim_kind="hook", claim_text=opener, urls=[hook.link], kb_chunk_ids=[]),
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


if __name__ == "__main__":
    unittest.main()

