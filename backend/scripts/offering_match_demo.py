"""Quick demo to verify hook-to-offering matching across products.

Run:
  cd backend
  python scripts/offering_match_demo.py
"""

from pathlib import Path
from types import SimpleNamespace
import sys

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir / "src"))

from src.pipeline.runner import _select_required_offering  # noqa: E402
from src.pipeline.schemas import SelectedHook, WebHook  # noqa: E402
from src.research.product_briefs import load_override_brief  # noqa: E402


def _make_hook(text: str) -> SelectedHook:
    hook = WebHook(
        hook_type="funding_guidance",
        quote=text,
        link="https://example.com",
        trigger_excerpt=text,
        eligibility_excerpt=None,
        why_relevant="demo hook",
    )
    return SelectedHook(hook=hook, rank=1, reasons=["demo"])


def _run_case(product_key: str, hook_text: str, purpose: str | None = None) -> str | None:
    brief = load_override_brief(product_key)
    evidence_pack = SimpleNamespace(supplemental_brief=brief, product_key=product_key)
    return _select_required_offering(evidence_pack, _make_hook(hook_text), purpose_prompt=purpose)


def main() -> None:
    cases = [
        ("care_coaching", "ORR refugee subgrant with newcomer supports", None),
        ("wida_model", "ACCESS prediction and interim ELP assessment window", None),
        ("webbalign", "DOK alignment study required for standards audit", None),
        ("wida_sis", "Title III compliance reporting deadlines", None),
        ("wida_professional_learning", "train-the-trainer PD for WIDA standards", None),
        ("call", "distributed leadership survey for improvement planning", None),
        ("discussion_project", "Structured Academic Controversy for civic discourse", None),
        ("aiw_institute", "AIW rubric scoring calibration for instructional artifacts", None),
    ]

    for product_key, hook_text, purpose in cases:
        match = _run_case(product_key, hook_text, purpose)
        print(f"{product_key}: {match or 'NO MATCH'}")


if __name__ == "__main__":
    main()
