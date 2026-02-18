"""Stage 3: holistic DSPy chooser and apply selected options."""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import dspy
from pydantic import BaseModel, Field

from tailor_tom.latex_compiler import compile_latex
from tailor_tom.layout_analyzer import check_quality, extract_items_from_latex

from tailor_tom.optimizer.v3.stage0_preprocess import BulletConstraint, _strip_latex_commands, replace_nth
from tailor_tom.optimizer.v3.llm_usage import TokenUsage, usage_from_counts
from tailor_tom.optimizer.v3.usage_extractor import resolve_usage
from tailor_tom.optimizer.v3.debug_logging import debug_enabled, debug_log

logger = logging.getLogger(__name__)


@dataclass
class ChooserResult:
    """Result of Stage 3 chooser: choices, usage, and fallback/cross-bullet diagnostics."""
    choices: dict[int, str]
    usage: TokenUsage
    missing_filled_bullet_ids: list[int] = field(default_factory=list)
    missing_filled_count: int = 0
    invalid_cross_bullet_choice_count: int = 0


class ChooserRow(BaseModel):
    """One row: bullet_id, chosen_option_id."""
    bullet_id: int = Field(description="Bullet ID")
    chosen_option_id: str = Field(description="Option ID: b{N}_orig or b{N}_c{idx}_it{iter}")


class ChooserSignature(dspy.Signature):
    """Select one option per bullet from validated options to maximize overall JD alignment.

    HOLISTIC SELECTION OBJECTIVE:
    - Choose options that improve the resume as a whole, not bullet-by-bullet in isolation.
    - Balance keyword relevance with readability and non-redundancy.

    HARD RULES:
    - Return exactly one choice per bullet_id shown in options_per_bullet.
    - chosen_option_id must be one of the listed option IDs for that bullet.
    - Do not invent option IDs.

    CHOOSING HEURISTICS:
    - Prefer options that improve job-fit wording and concrete relevance.
    - Keep originals when alternates are stylistic-only or redundant.
    - Avoid selecting many options that repeat the same terms with no added value.
    - Treat all candidate options as pre-validated for factual/layout constraints.
    """
    job_description: str = dspy.InputField(desc="Job description")
    resume_context: str = dspy.InputField(desc="Compact resume context for edited bullets")
    options_per_bullet: str = dspy.InputField(desc="For each bullet: original text and validated option IDs with short previews")
    selection_policy: str = dspy.InputField(desc="Selection policy emphasizing holistic improvement and anti-redundancy")
    choices: list[ChooserRow] = dspy.OutputField(desc="One row per bullet: bullet_id, chosen_option_id")


def _format_options_for_chooser(
    bullets: list[BulletConstraint],
    options_per_bullet: dict[int, list[str]],
    option_id_to_latex: dict[str, str],
) -> str:
    """Format options per bullet for chooser input."""
    def _preview(text: str, max_len: int = 130) -> str:
        t = " ".join((text or "").split())
        return t if len(t) <= max_len else (t[: max_len - 3] + "...")

    lines = []
    for b in bullets:
        opts = options_per_bullet.get(b.bullet_id, [])
        lines.append(f"B{b.bullet_id} [{b.section}]")
        lines.append(f"Original text: {_preview(b.original_text)}")
        lines.append("Options:")
        for oid in opts:
            repl = option_id_to_latex.get(oid, "")
            plain = _strip_latex_commands(repl) if repl else ""
            marker = " (orig)" if oid.endswith("_orig") else ""
            lines.append(f"- {oid}{marker}: {_preview(plain)}")
        lines.append("")
    return "\n".join(lines)


def _format_resume_context_for_chooser(bullets: list[BulletConstraint]) -> str:
    """Compact context so chooser understands surrounding edited areas without huge token cost."""
    lines = ["Target bullets context:"]
    for b in bullets:
        lines.append(f"- B{b.bullet_id} [{b.section}]: {b.original_text}")
    return "\n".join(lines)


def _normalize_snippet(s: str) -> str:
    """Normalize for ownership comparison (whitespace, strip commands)."""
    return " ".join(_strip_latex_commands(s or "").split())


def _verify_ownership_after_apply(
    final_latex: str,
    bullets: list[BulletConstraint],
    choices: dict[int, str],
    option_id_to_latex: dict[str, str],
) -> tuple[bool, str]:
    """Verify each changed bullet's replacement landed in its owned source item.
    Returns (passed, error_message). On failure, error_message describes the mismatch.
    """
    items = extract_items_from_latex(final_latex)
    bullet_by_id = {b.bullet_id: b for b in bullets}
    for bid, option_id in choices.items():
        bullet = bullet_by_id.get(bid)
        if not bullet:
            continue
        chosen_latex = option_id_to_latex.get(option_id, "")
        orig_latex = bullet.latex_snippet or ""
        if _normalize_snippet(chosen_latex) == _normalize_snippet(orig_latex):
            continue
        src_idx = getattr(bullet, "source_item_index", bid - 1)
        if src_idx < 0:
            src_idx = bid - 1
        if src_idx >= len(items):
            return False, f"ownership check: source_item_index {src_idx} out of range (items={len(items)})"
        item_latex = items[src_idx].get("latex", "")
        if _normalize_snippet(item_latex) != _normalize_snippet(chosen_latex):
            return False, f"ownership check: item at source_item_index {src_idx} does not match chosen replacement for bullet {bid}"
    return True, ""


def _apply_choices_to_latex(
    original_latex: str,
    bullets: list[BulletConstraint],
    choices: dict[int, str],
    option_id_to_latex: dict[str, str],
) -> tuple[str, bool]:
    """Apply chosen option per bullet using anchored snippet replacement. Returns (final_latex, all_applied)."""
    bullet_by_id = {b.bullet_id: b for b in bullets}
    current = original_latex
    for bid in sorted(choices.keys()):
        option_id = choices[bid]
        latex_snippet = option_id_to_latex.get(option_id)
        bullet = bullet_by_id.get(bid)
        if not bullet or latex_snippet is None:
            return current, False
        n = getattr(bullet, "snippet_occurrence_index", 0)
        current, applied = replace_nth(current, bullet.latex_snippet, latex_snippet, n)
        if not applied:
            return current, False
    return current, True


def run_chooser(
    original_latex: str,
    bullets: list[BulletConstraint],
    options_per_bullet: dict[int, list[str]],
    option_id_to_latex: dict[str, str],
    job_description: str,
) -> Optional[ChooserResult]:
    """Run DSPy chooser. Returns ChooserResult or None on failure."""
    options_str = _format_options_for_chooser(bullets, options_per_bullet, option_id_to_latex)
    resume_context = _format_resume_context_for_chooser(bullets)
    selection_policy = (
        "Pick one option per bullet that best improves overall JD alignment, "
        "while minimizing redundant keyword repetition and keeping strong originals when alternatives are weak."
    )
    prompt_chars = len(job_description) + len(resume_context) + len(options_str) + len(selection_policy)
    try:
        predictor = dspy.Predict(ChooserSignature)
        result = predictor(
            job_description=job_description,
            resume_context=resume_context,
            options_per_bullet=options_str,
            selection_policy=selection_policy,
        )
        raw = result.choices if hasattr(result, "choices") else []
        if isinstance(raw, str):
            raw = json.loads(raw) if raw.strip() else []
        if not isinstance(raw, list):
            raw = []
    except Exception as e:
        logger.warning("Stage3 chooser failed: %s", e)
        return None

    valid_option_ids = set(option_id_to_latex.keys())
    choices_dict: dict[int, str] = {}
    invalid_cross_bullet_choice_count = 0
    for row in raw:
        if isinstance(row, dict):
            bid = row.get("bullet_id")
            oid = row.get("chosen_option_id")
        elif hasattr(row, "bullet_id") and hasattr(row, "chosen_option_id"):
            bid = row.bullet_id
            oid = row.chosen_option_id
        else:
            continue
        if bid is None or not oid:
            continue
        bid = int(bid)
        oid = str(oid)
        allowed = options_per_bullet.get(bid, [])
        if oid in allowed and oid in valid_option_ids:
            choices_dict[bid] = oid
        elif oid in valid_option_ids:
            invalid_cross_bullet_choice_count += 1

    # Fill missing bullets: fallback to b{bid}_orig if present, else first valid option for that bullet.
    required_bullet_ids = {b.bullet_id for b in bullets}
    missing_filled: list[int] = []
    for bid in sorted(required_bullet_ids):
        if bid in choices_dict:
            continue
        opts = options_per_bullet.get(bid, [])
        orig_id = f"b{bid}_orig"
        fallback: Optional[str] = None
        if orig_id in opts and orig_id in valid_option_ids:
            fallback = orig_id
        else:
            for oid in opts:
                if oid in valid_option_ids:
                    fallback = oid
                    break
        if not fallback:
            if debug_enabled():
                debug_log(logger, "stage3_chooser_missing_no_fallback", bullet_id=bid)
            return None
        choices_dict[bid] = fallback
        missing_filled.append(bid)

    completion_chars = 0
    try:
        completion_chars = len(json.dumps(raw))
    except Exception:
        completion_chars = 0
    usage = resolve_usage(result, prompt_chars, completion_chars)
    if debug_enabled():
        debug_log(
            logger,
            "stage3_chooser",
            choices=choices_dict,
            missing_filled_count=len(missing_filled),
            missing_filled_bullet_ids=missing_filled,
            invalid_cross_bullet_choice_count=invalid_cross_bullet_choice_count,
            usage_source=usage.usage_source,
        )
    return ChooserResult(
        choices=choices_dict,
        usage=usage,
        missing_filled_bullet_ids=missing_filled,
        missing_filled_count=len(missing_filled),
        invalid_cross_bullet_choice_count=invalid_cross_bullet_choice_count,
    )


def apply_and_verify(
    original_latex: str,
    bullets: list[BulletConstraint],
    choices: dict[int, str],
    option_id_to_latex: dict[str, str],
    target_pages: int,
) -> tuple[bool, str, Optional[bytes], int, bool, str]:
    """Apply choices, compile, run quality check.
    Returns (success, error_message, pdf_bytes, page_count, quality_passes, quality_issues_summary).
    """
    final_latex, all_applied = _apply_choices_to_latex(
        original_latex, bullets, choices, option_id_to_latex
    )
    if not all_applied:
        return False, "Failed to apply some chooser selections", None, 0, False, ""

    ownership_ok, ownership_err = _verify_ownership_after_apply(final_latex, bullets, choices, option_id_to_latex)
    if not ownership_ok:
        return False, f"Ownership verification failed: {ownership_err}", None, 0, False, ""

    compile_result = compile_latex(final_latex)
    if not compile_result.success:
        return False, compile_result.error_message or "Final compile failed", None, 0, False, ""

    quality = check_quality(
        pdf_bytes=compile_result.pdf_bytes or b"",
        target_pages=target_pages,
        latex=final_latex,
    )
    return (
        True,
        "",
        compile_result.pdf_bytes,
        compile_result.page_count or 0,
        quality.passes,
        quality.issues_summary,
    )
