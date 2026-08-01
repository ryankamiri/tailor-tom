"""Stage 3: holistic DSPy chooser and apply selected options."""

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import dspy
from pydantic import BaseModel, Field

from tailor_tom.latex_compiler import compile_latex
from tailor_tom.layout_analyzer import check_quality, extract_items_from_latex
from tailor_tom.config import settings

from tailor_tom.optimizer.v3.stage0_preprocess import BulletConstraint, _strip_latex_commands, replace_nth
from tailor_tom.optimizer.v3.llm_errors import classify_llm_exception
from tailor_tom.optimizer.v3.llm_usage import TokenUsage, usage_from_counts
from tailor_tom.optimizer.v3.types import LLMErrorInfo
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
    forced_changed_bullet_ids: list[int] = field(default_factory=list)
    forced_overlong_bullet_ids: list[int] = field(default_factory=list)
    min_changed_target: int = 0


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


def _snippet_preview(s: str, max_len: int = 180) -> str:
    """Compact single-line preview for debug logs."""
    t = " ".join(_normalize_snippet(s).split())
    return t if len(t) <= max_len else (t[: max_len - 3] + "...")


def _matching_item_indices(items: list[dict], target_norm: str) -> list[int]:
    """Return all item indices whose normalized latex equals target_norm."""
    if not target_norm:
        return []
    out: list[int] = []
    for i, item in enumerate(items):
        item_norm = _normalize_snippet(item.get("latex", ""))
        if item_norm == target_norm:
            out.append(i)
    return out


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
        chosen_norm = _normalize_snippet(chosen_latex)
        orig_norm = _normalize_snippet(orig_latex)
        if chosen_norm == orig_norm:
            continue
        src_idx = getattr(bullet, "source_item_index", bid - 1)
        if src_idx < 0:
            src_idx = bid - 1
        if src_idx >= len(items):
            chosen_match_indices = _matching_item_indices(items, chosen_norm)
            original_match_indices = _matching_item_indices(items, orig_norm)
            if debug_enabled():
                debug_log(
                    logger,
                    "stage3_ownership_mismatch",
                    reason="source_index_out_of_range",
                    bullet_id=bid,
                    option_id=option_id,
                    source_item_index=src_idx,
                    item_count=len(items),
                    snippet_occurrence_index=int(getattr(bullet, "snippet_occurrence_index", 0)),
                    chosen_match_indices=chosen_match_indices,
                    original_match_indices=original_match_indices,
                    chosen_preview=_snippet_preview(chosen_latex),
                    original_preview=_snippet_preview(orig_latex),
                )
            return False, f"ownership check: source_item_index {src_idx} out of range (items={len(items)})"
        item_latex = items[src_idx].get("latex", "")
        if _normalize_snippet(item_latex) != chosen_norm:
            chosen_match_indices = _matching_item_indices(items, chosen_norm)
            original_match_indices = _matching_item_indices(items, orig_norm)
            if debug_enabled():
                debug_log(
                    logger,
                    "stage3_ownership_mismatch",
                    reason="source_item_mismatch",
                    bullet_id=bid,
                    option_id=option_id,
                    source_item_index=src_idx,
                    item_count=len(items),
                    snippet_occurrence_index=int(getattr(bullet, "snippet_occurrence_index", 0)),
                    chosen_match_indices=chosen_match_indices,
                    original_match_indices=original_match_indices,
                    chosen_preview=_snippet_preview(chosen_latex),
                    source_item_preview=_snippet_preview(item_latex),
                    original_preview=_snippet_preview(orig_latex),
                )
            return False, f"ownership check: item at source_item_index {src_idx} does not match chosen replacement for bullet {bid}"
    return True, ""


def _verify_single_owned_apply(
    latex_after_apply: str,
    bullet: BulletConstraint,
    option_id: str,
    chosen_latex: str,
) -> tuple[bool, dict]:
    """Verify one applied replacement landed at bullet.source_item_index."""
    items = extract_items_from_latex(latex_after_apply)
    src_idx = int(getattr(bullet, "source_item_index", bullet.bullet_id - 1))
    if src_idx < 0:
        src_idx = bullet.bullet_id - 1
    chosen_norm = _normalize_snippet(chosen_latex or "")
    orig_norm = _normalize_snippet(bullet.latex_snippet or "")
    chosen_match_indices = _matching_item_indices(items, chosen_norm)
    original_match_indices = _matching_item_indices(items, orig_norm)
    if src_idx >= len(items):
        return False, {
            "reason": "source_index_out_of_range",
            "bullet_id": bullet.bullet_id,
            "option_id": option_id,
            "source_item_index": src_idx,
            "item_count": len(items),
            "snippet_occurrence_index": int(getattr(bullet, "snippet_occurrence_index", 0)),
            "chosen_match_indices": chosen_match_indices,
            "original_match_indices": original_match_indices,
            "chosen_preview": _snippet_preview(chosen_latex),
            "original_preview": _snippet_preview(bullet.latex_snippet or ""),
        }
    owned_item = items[src_idx].get("latex", "")
    if _normalize_snippet(owned_item) != chosen_norm:
        return False, {
            "reason": "source_item_mismatch",
            "bullet_id": bullet.bullet_id,
            "option_id": option_id,
            "source_item_index": src_idx,
            "item_count": len(items),
            "snippet_occurrence_index": int(getattr(bullet, "snippet_occurrence_index", 0)),
            "chosen_match_indices": chosen_match_indices,
            "original_match_indices": original_match_indices,
            "chosen_preview": _snippet_preview(chosen_latex),
            "source_item_preview": _snippet_preview(owned_item),
            "original_preview": _snippet_preview(bullet.latex_snippet or ""),
        }
    return True, {}


def _apply_choices_to_latex(
    original_latex: str,
    bullets: list[BulletConstraint],
    choices: dict[int, str],
    option_id_to_latex: dict[str, str],
) -> tuple[str, dict[int, str], list[int]]:
    """Apply chosen options with per-bullet fail-open.

    Returns:
    - final_latex: result after applying all successful non-original choices.
    - effective_choices: final choice per bullet after fallbacks (failed bullets -> original).
    - dropped_bullet_ids: bullets whose chosen candidate was dropped/fell back to original.
    """
    bullet_by_id = {b.bullet_id: b for b in bullets}
    current = original_latex
    effective_choices: dict[int, str] = dict(choices)
    dropped_bullet_ids: list[int] = []
    # Build an application plan first, then apply in an occurrence-safe order.
    # Why: when multiple bullets share the same original snippet text, replacing lower
    # occurrence indexes first can shift later occurrence targeting. For each snippet,
    # apply higher snippet_occurrence_index first.
    apply_plan: list[tuple[str, int, int, str, BulletConstraint, str]] = []
    for bid in sorted(choices.keys()):
        option_id = choices[bid]
        if option_id.endswith("_orig"):
            # Original choice means no edit required.
            continue
        latex_snippet = option_id_to_latex.get(option_id)
        bullet = bullet_by_id.get(bid)
        if not bullet or latex_snippet is None:
            if debug_enabled():
                debug_log(
                    logger,
                    "stage3_apply_failure",
                    reason="missing_bullet_or_option",
                    bullet_id=bid,
                    option_id=option_id,
                    bullet_exists=bullet is not None,
                    option_exists=latex_snippet is not None,
                )
            effective_choices[bid] = f"b{bid}_orig"
            dropped_bullet_ids.append(bid)
            continue
        n = int(getattr(bullet, "snippet_occurrence_index", 0))
        apply_plan.append((bullet.latex_snippet or "", -n, bid, option_id, bullet, latex_snippet))

    # Sort by snippet identity first, then descending occurrence index for that snippet.
    # Tie-break by bullet_id for deterministic behavior.
    apply_plan.sort(key=lambda row: (row[0], row[1], row[2]))
    if debug_enabled():
        debug_log(
            logger,
            "stage3_apply_order",
            applied_count=len(apply_plan),
            order=[{"bullet_id": bid, "option_id": oid, "occurrence_index": -neg_n} for _, neg_n, bid, oid, _, _ in apply_plan[:20]],
        )
    for _, neg_n, bid, option_id, bullet, latex_snippet in apply_plan:
        n = -neg_n
        current, applied = replace_nth(current, bullet.latex_snippet, latex_snippet, n)
        if not applied:
            if debug_enabled():
                debug_log(
                    logger,
                    "stage3_apply_failure",
                    reason="replace_nth_not_applied",
                    bullet_id=bid,
                    option_id=option_id,
                    snippet_occurrence_index=n,
                    bullet_source_item_index=getattr(bullet, "source_item_index", -1),
                    original_snippet_preview=_snippet_preview(bullet.latex_snippet or ""),
                    replacement_preview=_snippet_preview(latex_snippet or ""),
                )
            effective_choices[bid] = f"b{bid}_orig"
            dropped_bullet_ids.append(bid)
            continue
        owned_ok, owned_meta = _verify_single_owned_apply(current, bullet, option_id, latex_snippet)
        if not owned_ok:
            if debug_enabled():
                debug_log(logger, "stage3_apply_ownership_fail", **owned_meta)
            # Roll back only this bullet by applying original snippet at the same anchored occurrence.
            rolled_back, rollback_applied = replace_nth(current, latex_snippet, bullet.latex_snippet, n)
            if rollback_applied:
                current = rolled_back
            effective_choices[bid] = f"b{bid}_orig"
            dropped_bullet_ids.append(bid)
            if debug_enabled():
                debug_log(
                    logger,
                    "stage3_apply_drop_to_original",
                    bullet_id=bid,
                    option_id=option_id,
                    rollback_applied=rollback_applied,
                    snippet_occurrence_index=n,
                )
            continue
    return current, effective_choices, dropped_bullet_ids


def _compile_and_check_quality(final_latex: str, target_pages: int):
    """Compile a final candidate and run the quality gate."""
    compile_result = compile_latex(final_latex)
    if not compile_result.success:
        return False, compile_result.error_message or "Final compile failed", None, 0, None
    quality = check_quality(
        pdf_bytes=compile_result.pdf_bytes or b"",
        target_pages=target_pages,
        latex=final_latex,
    )
    return True, "", compile_result.pdf_bytes, compile_result.page_count or 0, quality


def _try_quality_fallback_by_reverting(
    original_latex: str,
    bullets: list[BulletConstraint],
    effective_choices: dict[int, str],
    option_id_to_latex: dict[str, str],
    target_pages: int,
) -> tuple[bool, Optional[bytes], int, bool, str, str, dict[int, str], list[int], dict]:
    """Try restoring changed bullets to originals until the final quality gate passes."""
    changed_bids = [bid for bid, oid in effective_choices.items() if oid != f"b{bid}_orig"]
    changed_bids.sort(
        key=lambda bid: (
            -(
                len(option_id_to_latex.get(effective_choices.get(bid, ""), ""))
                - len(option_id_to_latex.get(f"b{bid}_orig", ""))
            ),
            bid,
        )
    )
    fallback_meta = {
        "attempted": bool(changed_bids),
        "success": False,
        "reverted_bullet_ids": [],
        "attempts": [],
    }
    if not changed_bids:
        return False, None, 0, False, "", original_latex, effective_choices, [], fallback_meta

    trial_choices = dict(effective_choices)
    reverted: list[int] = []
    last_latex = original_latex
    last_effective = dict(effective_choices)
    last_dropped: list[int] = []
    last_quality_issues = ""
    last_page_count = 0
    last_pdf: Optional[bytes] = None

    for bid in changed_bids:
        trial_choices[bid] = f"b{bid}_orig"
        reverted.append(bid)
        trial_latex, trial_effective, trial_dropped = _apply_choices_to_latex(
            original_latex, bullets, trial_choices, option_id_to_latex
        )
        ownership_ok, ownership_err = _verify_ownership_after_apply(
            trial_latex, bullets, trial_effective, option_id_to_latex
        )
        if not ownership_ok:
            fallback_meta["attempts"].append({
                "reverted_bullet_ids": list(reverted),
                "error": f"Ownership verification failed: {ownership_err}",
            })
            continue
        compiled, compile_err, pdf_bytes, page_count, quality = _compile_and_check_quality(
            trial_latex, target_pages
        )
        if not compiled or quality is None:
            fallback_meta["attempts"].append({
                "reverted_bullet_ids": list(reverted),
                "error": compile_err,
            })
            continue
        last_latex = trial_latex
        last_effective = trial_effective
        last_dropped = trial_dropped
        last_quality_issues = quality.issues_summary
        last_page_count = page_count
        last_pdf = pdf_bytes
        fallback_meta["attempts"].append({
            "reverted_bullet_ids": list(reverted),
            "page_count": page_count,
            "quality_passes": quality.passes,
            "quality_issues_summary": quality.issues_summary,
        })
        if quality.passes:
            fallback_meta["success"] = True
            fallback_meta["reverted_bullet_ids"] = list(reverted)
            return (
                True,
                pdf_bytes,
                page_count,
                True,
                quality.issues_summary,
                trial_latex,
                trial_effective,
                trial_dropped,
                fallback_meta,
            )

    fallback_meta["reverted_bullet_ids"] = list(reverted)
    return (
        True,
        last_pdf,
        last_page_count,
        False,
        last_quality_issues,
        last_latex,
        last_effective,
        last_dropped,
        fallback_meta,
    )


def run_chooser(
    original_latex: str,
    bullets: list[BulletConstraint],
    options_per_bullet: dict[int, list[str]],
    option_id_to_latex: dict[str, str],
    job_description: str,
) -> tuple[Optional[ChooserResult], Optional[LLMErrorInfo]]:
    """Run DSPy chooser. Returns ChooserResult or None on failure."""
    options_str = _format_options_for_chooser(bullets, options_per_bullet, option_id_to_latex)
    resume_context = _format_resume_context_for_chooser(bullets)
    min_changed_bullets = max(0, int(getattr(settings, "optimizer_min_changed_bullets", 0)))
    min_changed_ratio = max(0.0, float(getattr(settings, "optimizer_min_changed_ratio", 0.0)))
    min_changed_target = max(min_changed_bullets, int(math.ceil(min_changed_ratio * len(bullets))))
    selection_policy = (
        "Pick one option per bullet that best improves overall JD alignment, "
        "while minimizing redundant keyword repetition. "
        f"Target at least {min_changed_target} changed bullets when feasible non-original options exist."
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
        return None, classify_llm_exception(e, stage="stage3_chooser")

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

    # Enforce minimum changed bullets by promoting some originals to first feasible non-original option.
    forced_changed: list[int] = []
    changed_count = sum(1 for bid, oid in choices_dict.items() if oid != f"b{bid}_orig")
    if changed_count < min_changed_target:
        need = min_changed_target - changed_count
        promotable: list[tuple[int, str]] = []
        for bid in sorted(required_bullet_ids):
            if choices_dict.get(bid) != f"b{bid}_orig":
                continue
            opts = options_per_bullet.get(bid, [])
            non_orig = [oid for oid in opts if oid in valid_option_ids and oid != f"b{bid}_orig"]
            if non_orig:
                promotable.append((bid, non_orig[0]))
        for bid, promote_oid in promotable[:need]:
            choices_dict[bid] = promote_oid
            forced_changed.append(bid)

    # If an original bullet violates the long-bullet gate, prefer the shortest
    # feasible repair over the original. Stage 2 has already verified the
    # replacement meets the rendered line target for these bullets.
    forced_overlong: list[int] = []
    for b in bullets:
        target_line_count = int(getattr(b, "target_line_count", b.line_count))
        if target_line_count >= b.line_count:
            continue
        opts = options_per_bullet.get(b.bullet_id, [])
        non_orig = [
            oid for oid in opts
            if oid in valid_option_ids and oid != f"b{b.bullet_id}_orig"
        ]
        if not non_orig:
            continue
        best_oid = min(
            non_orig,
            key=lambda oid: len(_strip_latex_commands(option_id_to_latex.get(oid, ""))),
        )
        if choices_dict.get(b.bullet_id) != best_oid:
            choices_dict[b.bullet_id] = best_oid
            forced_overlong.append(b.bullet_id)

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
            forced_changed_bullet_ids=forced_changed,
            forced_overlong_bullet_ids=forced_overlong,
            min_changed_target=min_changed_target,
            usage_source=usage.usage_source,
        )
    return (
        ChooserResult(
            choices=choices_dict,
            usage=usage,
            missing_filled_bullet_ids=missing_filled,
            missing_filled_count=len(missing_filled),
            invalid_cross_bullet_choice_count=invalid_cross_bullet_choice_count,
            forced_changed_bullet_ids=forced_changed,
            forced_overlong_bullet_ids=forced_overlong,
            min_changed_target=min_changed_target,
        ),
        None,
    )


def apply_and_verify(
    original_latex: str,
    bullets: list[BulletConstraint],
    choices: dict[int, str],
    option_id_to_latex: dict[str, str],
    target_pages: int,
    baseline_over_target: bool = False,
) -> tuple[bool, str, Optional[bytes], int, bool, str, str, dict[int, str], list[int], dict]:
    """Apply choices, compile, run quality check.
    Returns:
    (success, error_message, pdf_bytes, page_count, quality_passes, quality_issues_summary,
    final_latex, effective_choices, dropped_bullet_ids, quality_fallback).
    """
    final_latex, effective_choices, dropped_bullet_ids = _apply_choices_to_latex(
        original_latex, bullets, choices, option_id_to_latex
    )

    ownership_ok, ownership_err = _verify_ownership_after_apply(final_latex, bullets, effective_choices, option_id_to_latex)
    if not ownership_ok:
        if debug_enabled():
            debug_log(
                logger,
                "stage3_apply_and_verify_failure",
                reason="ownership_failed",
                ownership_error=ownership_err,
                chosen_count=len(choices),
                dropped_bullet_ids=dropped_bullet_ids,
            )
        return False, f"Ownership verification failed: {ownership_err}", None, 0, False, "", final_latex, effective_choices, dropped_bullet_ids, {"attempted": False, "success": False}

    compiled, compile_err, pdf_bytes, page_count, quality = _compile_and_check_quality(final_latex, target_pages)
    if not compiled or quality is None:
        return False, compile_err, None, 0, False, "", final_latex, effective_choices, dropped_bullet_ids, {"attempted": False, "success": False}
    fallback_meta = {"attempted": False, "success": False, "reverted_bullet_ids": [], "attempts": []}
    if not quality.passes and baseline_over_target and quality.page_count > target_pages:
        # The original resume already exceeds the target page count and has no long
        # bullets to trim, so reverting changed bullets can only move the document
        # toward the already-over-target baseline. Only short-circuit when the failure
        # is the page overflow itself: a long-bullet-only failure (page count fits) is
        # still recoverable by reverting the offending edit, so fall through to it.
        # Skip the revert fallback and surface a clear content-fit failure instead of
        # wasting compile cycles.
        reason = f"Resume content exceeds {target_pages} page(s); cannot fit target without cutting content."
        return (
            True,
            "",
            pdf_bytes,
            page_count,
            False,
            reason,
            final_latex,
            effective_choices,
            dropped_bullet_ids,
            {"attempted": False, "success": False, "reverted_bullet_ids": [], "attempts": [], "skipped_reason": "baseline_over_target"},
        )
    if not quality.passes:
        (
            fallback_success,
            fallback_pdf,
            fallback_page_count,
            fallback_quality_passes,
            fallback_quality_issues,
            fallback_latex,
            fallback_effective_choices,
            fallback_dropped,
            fallback_meta,
        ) = _try_quality_fallback_by_reverting(
            original_latex,
            bullets,
            effective_choices,
            option_id_to_latex,
            target_pages,
        )
        if fallback_success and fallback_meta.get("success"):
            return (
                True,
                "",
                fallback_pdf,
                fallback_page_count,
                fallback_quality_passes,
                fallback_quality_issues,
                fallback_latex,
                fallback_effective_choices,
                fallback_dropped,
                fallback_meta,
            )
    return (
        True,
        "",
        pdf_bytes,
        page_count,
        quality.passes,
        quality.issues_summary,
        final_latex,
        effective_choices,
        dropped_bullet_ids,
        fallback_meta,
    )
