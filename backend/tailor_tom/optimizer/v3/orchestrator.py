"""V3 orchestrator: Stage 0-3 pipeline with two-pass feasibility and chooser authority."""

import logging
from typing import Optional

from tailor_tom.optimizer.v3.types import V3OptimizationResult, TokenUsage
from tailor_tom.optimizer.v3.llm_usage import merge_usage, usage_from_counts
from tailor_tom.optimizer.v3.llm_errors import ERROR_INVALID_API_KEY
from tailor_tom.optimizer.v3.stage0_preprocess import run_stage0, Stage0Result
from tailor_tom.optimizer.v3.stage1_generator import generate_candidates, GeneratedCandidate
from tailor_tom.optimizer.v3.stage2_validation import run_feasibility, FeasibilityResult
from tailor_tom.optimizer.v3.stage3_chooser import run_chooser, apply_and_verify
from tailor_tom.optimizer.v3.debug_logging import debug_enabled, debug_log
from tailor_tom.layout_analyzer import check_quality
from tailor_tom.optimizer.v3.stage2_validation import (
    REASON_APPLY_NO_EFFECT,
    REASON_COMPILE_FAILED,
    REASON_LINE_COUNT_MISMATCH,
    REASON_LINE_MAPPING_MISSING,
    REASON_SNIPPET_NOT_FOUND,
    REASON_ANCHORED_SNIPPET_NOT_FOUND,
    REASON_TOO_LONG_WORDS,
    REASON_TOO_LONG_CHARS,
    REASON_TOO_SHORT_WORDS,
    REASON_TOO_SHORT_PERCENT,
    REASON_INVALID_PAYLOAD,
)

logger = logging.getLogger(__name__)


def _repair_hint_for_reason(reason_code: str) -> str:
    """Return a concise repair hint for structured retry feedback."""
    hints = {
        REASON_TOO_LONG_WORDS: "Reduce word count.",
        REASON_TOO_LONG_CHARS: "Reduce character count.",
        REASON_TOO_SHORT_WORDS: "Add or preserve enough words.",
        REASON_TOO_SHORT_PERCENT: "Avoid shrinking text too much.",
        REASON_SNIPPET_NOT_FOUND: "Match original LaTeX snippet exactly.",
        REASON_ANCHORED_SNIPPET_NOT_FOUND: "Match original LaTeX snippet at correct occurrence.",
        REASON_APPLY_NO_EFFECT: "Make a substantive change or keep original.",
        REASON_INVALID_PAYLOAD: "Return valid bullet_id and LaTeX.",
        REASON_COMPILE_FAILED: "Ensure valid LaTeX and no broken commands.",
        REASON_LINE_COUNT_MISMATCH: "Meet the rendered line target so bullet fits layout.",
        REASON_LINE_MAPPING_MISSING: "Post-compile bullet at source item index missing; layout may have shifted.",
    }
    return hints.get(reason_code, "Address validation failure.")


def _bullet_id_from_option_id(option_id: str) -> Optional[int]:
    """Parse b{N}_... -> N."""
    if not option_id or not option_id.startswith("b"):
        return None
    try:
        return int(option_id.split("_", 1)[0][1:])
    except (ValueError, IndexError):
        return None


def _compact_long_bullets(long_bullets: list[dict], limit: int = 10) -> list[dict]:
    """Return compact, non-sensitive-enough previews for diagnostics."""
    out: list[dict] = []
    for bullet in long_bullets[:limit]:
        preview = " ".join((bullet.get("text_preview") or "").split())
        out.append({
            "item_index": bullet.get("item_index"),
            "bullet_id": bullet.get("item_id"),
            "line_count": bullet.get("line_count", 0),
            "text_preview": preview[:180],
        })
    return out


def _baseline_quality_diagnostics(s0: Stage0Result, target_pages: int) -> tuple[dict, object | None]:
    """Compute baseline quality once so failures can explain pre-existing issues."""
    compile_result = s0.compile_result
    diagnostics: dict = {
        "baseline_page_count": compile_result.page_count if compile_result else 0,
        "baseline_quality_passes": None,
        "baseline_quality_issues_summary": "",
        "baseline_long_bullet_count": 0,
        "baseline_long_bullets": [],
    }
    if not compile_result or not compile_result.success or not compile_result.pdf_bytes:
        return diagnostics, None
    quality = check_quality(
        pdf_bytes=compile_result.pdf_bytes,
        target_pages=target_pages,
        latex=s0.original_latex,
    )
    diagnostics.update({
        "baseline_quality_passes": quality.passes,
        "baseline_quality_issues_summary": quality.issues_summary,
        "baseline_long_bullet_count": len(quality.long_bullets),
        "baseline_long_bullets": _compact_long_bullets(quality.long_bullets),
    })
    return diagnostics, quality


def optimize_resume_v3(
    resume_latex: str,
    job_description: str,
    target_pages: int = 1,
    max_iterations: int = 3,
    job_id: Optional[str] = None,
) -> V3OptimizationResult:
    """Run V3 Stage 0-3. No V2 logic; chooser is sole authority."""
    del job_id  # reserved for future status hooks

    # Stage 0
    s0 = run_stage0(resume_latex)
    if not s0.success:
        return V3OptimizationResult(
            success=False,
            error_message=s0.error_message,
            optimized_latex=resume_latex,
            passes_done=0,
            diagnostics={"stage": "stage0", "error": s0.error_message},
        )
    baseline_diagnostics, baseline_quality = _baseline_quality_diagnostics(s0, target_pages)
    baseline_over_target = (
        (baseline_diagnostics.get("baseline_page_count") or 0) > target_pages
        and (baseline_diagnostics.get("baseline_long_bullet_count") or 0) == 0
    )
    if s0.no_eligible:
        diag: dict = {"stage": "stage0", "no_eligible": True, "k": 0}
        diag.update(baseline_diagnostics)
        diag["baseline_over_target"] = baseline_over_target
        if getattr(s0, "stage0_diagnostics", None):
            diag.update(s0.stage0_diagnostics)
            diag["dropped_for_mapping_count"] = (
                diag.get("stage0_dropped_unmatched_count", 0)
                + diag.get("stage0_dropped_low_confidence_count", 0)
            )
            diag["dropped_for_mapping_sample"] = (
                (diag.get("stage0_dropped_unmatched_sample") or [])[:10]
                + (diag.get("stage0_dropped_low_confidence_sample") or [])[:10]
            )[:20]
        diag["mapping_integrity_passed"] = True
        quality_passes = baseline_quality.passes if baseline_quality is not None else True
        quality_issues = baseline_quality.issues_summary if baseline_quality is not None else ""
        # Inherent content-fit failure: baseline already exceeds target with no long
        # bullets to trim, and there are no eligible bullets to optimize. Surface the
        # same clear message as the stage3 short-circuit and mark it so the worker can
        # suppress the terminal ops alert (this is not an infra failure).
        content_fit_failure = bool(not quality_passes and baseline_over_target)
        if content_fit_failure:
            quality_issues = f"Resume content exceeds {target_pages} page(s); cannot fit target without cutting content."
        diag["content_fit_failure"] = content_fit_failure
        return V3OptimizationResult(
            success=quality_passes,
            optimized_latex=resume_latex,
            pdf_bytes=s0.compile_result.pdf_bytes if s0.compile_result else None,
            page_count=s0.compile_result.page_count if s0.compile_result else 0,
            passes_done=0,
            error_message=None if quality_passes else quality_issues,
            quality_passes=quality_passes,
            quality_issues_summary=quality_issues,
            token_usage=usage_from_counts(0, 0, 0.0, "estimated"),
            diagnostics=diag,
        )

    bullets = s0.eligible_bullets
    original_options = s0.original_options
    original_latex = s0.original_latex
    compile_result = s0.compile_result

    # Feasible options: original + any generated that pass both passes
    feasible_option_ids: set[str] = set()
    option_id_to_latex: dict[str, str] = {}
    for bid, opt in original_options.items():
        oid = opt.get("option_id") or f"b{bid}_orig"
        latex_snippet = opt.get("latex") or ""
        feasible_option_ids.add(oid)
        option_id_to_latex[oid] = latex_snippet

    # Start source as empty so first non-zero increment defines source correctly.
    token_usage_acc = usage_from_counts(0, 0, 0.0, "")
    diagnostics: dict = {
        "k": len(bullets),
        **baseline_diagnostics,
        "baseline_over_target": baseline_over_target,
        "content_fit_failure": False,
        "pass1_reason_histogram_by_iter": [],
        "pass2_reason_histogram_by_iter": [],
        "rejection_reasons_by_bullet": {},
        "zero_feasible_fallback_to_original": False,
        "bullets_with_zero_feasible_generated": [],
        "early_stop": False,
        "max_iterations_used": 0,
    }
    if getattr(s0, "stage0_diagnostics", None):
        diagnostics.update(s0.stage0_diagnostics)
        diagnostics["dropped_for_mapping_count"] = (
            diagnostics.get("stage0_dropped_unmatched_count", 0)
            + diagnostics.get("stage0_dropped_low_confidence_count", 0)
        )
        diagnostics["dropped_for_mapping_sample"] = (
            list(diagnostics.get("stage0_dropped_unmatched_sample") or [])[:10]
            + list(diagnostics.get("stage0_dropped_low_confidence_sample") or [])[:10]
        )[:20]

    all_candidates: list[GeneratedCandidate] = []
    pass1_hist_merged: dict[str, int] = {}
    pass2_hist_merged: dict[str, int] = {}
    last_feas: Optional[FeasibilityResult] = None
    used_iterations = 0

    def _feasible_generated_by_bullet() -> dict[int, list[str]]:
        out: dict[int, list[str]] = {b.bullet_id: [] for b in bullets}
        for oid in feasible_option_ids:
            if "_c" not in oid or "_it" not in oid:
                continue
            try:
                bid = int(oid.split("_")[0][1:])
                if bid in out:
                    out[bid].append(oid)
            except (ValueError, IndexError):
                pass
        return out

    for iteration in range(max_iterations):
        feasible_generated_by_bullet = _feasible_generated_by_bullet()
        bullets_with_zero = [b.bullet_id for b in bullets if not feasible_generated_by_bullet.get(b.bullet_id)]
        diagnostics["bullets_with_zero_feasible_generated"] = bullets_with_zero

        if not bullets_with_zero:
            diagnostics["early_stop"] = True
            diagnostics["max_iterations_used"] = used_iterations
            if debug_enabled():
                debug_log(logger, "v3_early_stop", iteration=iteration)
            break

        failed_feedback: dict[int, str] = {}
        if iteration > 0 and last_feas is not None:
            bullet_by_id = {b.bullet_id: b for b in bullets}
            for c in all_candidates:
                if c.bullet_id not in bullets_with_zero:
                    continue
                reason_code = (getattr(last_feas, "pass1_fail", {}) or {}).get(c.option_id) or (getattr(last_feas, "pass2_fail", {}) or {}).get(c.option_id)
                if not reason_code:
                    continue
                pass1_details = (getattr(last_feas, "pass1_fail_details", {}) or {}).get(c.option_id, {})
                bullet = bullet_by_id.get(c.bullet_id)
                repl = (c.replacement_latex or "").strip()
                repl_plain = repl  # use as-is for char count; word count from split
                repl_words = len(repl_plain.split()) if repl_plain else 0
                repl_chars = len(repl_plain)
                word_delta = repl_words - bullet.word_count if bullet else 0
                char_delta = repl_chars - bullet.char_count if bullet else 0
                old_lines = bullet.line_count if bullet else 0
                repair_hint = _repair_hint_for_reason(reason_code)
                min_words_allowed = pass1_details.get("min_words_allowed")
                max_words_allowed = pass1_details.get("max_words_allowed")
                max_chars_allowed = pass1_details.get("max_chars_allowed")
                max_shrink_words_allowed = pass1_details.get("max_shrink_words_allowed")
                max_shrink_percent_allowed = pass1_details.get("max_shrink_percent_allowed")
                part = (
                    f"reason_code={reason_code}; old_lines={old_lines}; "
                    f"word_delta={word_delta:+d}; char_delta={char_delta:+d}; "
                    f"required_min_words={min_words_allowed}; required_max_words={max_words_allowed}; "
                    f"required_max_chars={max_chars_allowed}; allowed_word_shrink={max_shrink_words_allowed}; "
                    f"allowed_char_shrink_pct={max_shrink_percent_allowed}; "
                    f"actual_words={pass1_details.get('repl_words', repl_words)}; "
                    f"actual_chars={pass1_details.get('repl_chars', repl_chars)}; "
                    f"repair_hint={repair_hint}"
                )
                failed_feedback[c.bullet_id] = failed_feedback.get(c.bullet_id, "") + (" | " if failed_feedback.get(c.bullet_id) else "") + part

        gen_bullets = bullets if iteration == 0 else [b for b in bullets if b.bullet_id in bullets_with_zero]

        used_iterations += 1
        new_candidates, usage, llm_error = generate_candidates(
            gen_bullets,
            job_description,
            failed_feedback=failed_feedback if iteration > 0 else None,
            iteration=iteration,
        )
        token_usage_acc = merge_usage(token_usage_acc, usage)
        if llm_error is not None:
            diagnostics["llm_error"] = {
                "code": llm_error.code,
                "message": llm_error.message,
                "stage": llm_error.stage,
                "raw_error": llm_error.raw_error,
            }
            diagnostics["llm_error_code"] = llm_error.code
            if llm_error.code == ERROR_INVALID_API_KEY:
                return V3OptimizationResult(
                    success=False,
                    error_message=llm_error.message,
                    optimized_latex=original_latex,
                    pdf_bytes=compile_result.pdf_bytes if compile_result else None,
                    page_count=compile_result.page_count if compile_result else 0,
                    passes_done=used_iterations,
                    token_usage=token_usage_acc,
                    diagnostics=diagnostics,
                )
        all_candidates.extend(new_candidates)

        feas = run_feasibility(original_latex, bullets, new_candidates)
        last_feas = feas
        for oid in feas.feasible_option_ids:
            feasible_option_ids.add(oid)
            c = next((x for x in new_candidates if x.option_id == oid), None)
            if c:
                option_id_to_latex[oid] = c.replacement_latex
        for k, v in feas.pass1_reason_histogram.items():
            pass1_hist_merged[k] = pass1_hist_merged.get(k, 0) + v
        for k, v in feas.pass2_reason_histogram.items():
            pass2_hist_merged[k] = pass2_hist_merged.get(k, 0) + v

        # Per-bullet reject reasons for debugging (helps explain bullets like 4/5).
        per_bullet = diagnostics.get("rejection_reasons_by_bullet") or {}
        for fail_map in (feas.pass1_fail, feas.pass2_fail):
            for oid, reason in (fail_map or {}).items():
                bid = _bullet_id_from_option_id(oid)
                if bid is None:
                    continue
                bkey = str(bid)
                bucket = per_bullet.setdefault(bkey, {})
                bucket[reason] = int(bucket.get(reason, 0)) + 1
        diagnostics["rejection_reasons_by_bullet"] = per_bullet

        diagnostics["pass1_reason_histogram_by_iter"].append(dict(feas.pass1_reason_histogram))
        diagnostics["pass2_reason_histogram_by_iter"].append(dict(feas.pass2_reason_histogram))

    diagnostics["pass1_reason_histogram"] = pass1_hist_merged
    diagnostics["pass2_reason_histogram"] = pass2_hist_merged
    if last_feas is not None:
        diagnostics["no_effect_candidate_count"] = getattr(last_feas, "no_effect_candidate_count", 0)
        diagnostics["duplicate_slot_candidates_count"] = getattr(last_feas, "duplicate_slot_candidates_count", 0)
        diagnostics["canonicalized_candidate_pairs_count"] = getattr(last_feas, "canonicalized_candidate_pairs_count", 0)
    if not diagnostics.get("early_stop"):
        diagnostics["max_iterations_used"] = used_iterations

    bullets_with_zero_final = [b.bullet_id for b in bullets if not any(
        "_c" in oid and "_it" in oid and oid.startswith(f"b{b.bullet_id}_")
        for oid in feasible_option_ids
    )]
    if bullets_with_zero_final:
        diagnostics["zero_feasible_fallback_to_original"] = True
        diagnostics["bullets_with_zero_feasible_generated"] = bullets_with_zero_final

    # Build options per bullet for chooser
    options_per_bullet: dict[int, list[str]] = {}
    for b in bullets:
        opts = [oid for oid in feasible_option_ids if oid == f"b{b.bullet_id}_orig" or (oid.startswith(f"b{b.bullet_id}_") and oid != f"b{b.bullet_id}_orig")]
        options_per_bullet[b.bullet_id] = sorted(opts)

    chooser_result, chooser_error = run_chooser(
        original_latex,
        bullets,
        options_per_bullet,
        option_id_to_latex,
        job_description,
    )
    if chooser_error is not None:
        diagnostics["llm_error"] = {
            "code": chooser_error.code,
            "message": chooser_error.message,
            "stage": chooser_error.stage,
            "raw_error": chooser_error.raw_error,
        }
        diagnostics["llm_error_code"] = chooser_error.code
        return V3OptimizationResult(
            success=False,
            error_message=chooser_error.message,
            optimized_latex=original_latex,
            pdf_bytes=compile_result.pdf_bytes if compile_result else None,
            page_count=compile_result.page_count if compile_result else 0,
            passes_done=used_iterations,
            token_usage=token_usage_acc,
            diagnostics=diagnostics,
        )
    if not chooser_result:
        return V3OptimizationResult(
            success=False,
            error_message="Chooser did not return valid choices",
            optimized_latex=original_latex,
            pdf_bytes=compile_result.pdf_bytes if compile_result else None,
            page_count=compile_result.page_count if compile_result else 0,
            passes_done=used_iterations,
            token_usage=token_usage_acc,
            diagnostics=diagnostics,
        )
    token_usage_acc = merge_usage(token_usage_acc, chooser_result.usage)
    choices = chooser_result.choices
    diagnostics["missing_filled_bullet_ids"] = chooser_result.missing_filled_bullet_ids
    diagnostics["missing_filled_count"] = chooser_result.missing_filled_count
    diagnostics["invalid_cross_bullet_choice_count"] = chooser_result.invalid_cross_bullet_choice_count
    diagnostics["forced_changed_bullet_ids"] = chooser_result.forced_changed_bullet_ids
    diagnostics["forced_changed_count"] = len(chooser_result.forced_changed_bullet_ids)
    diagnostics["forced_overlong_bullet_ids"] = chooser_result.forced_overlong_bullet_ids
    diagnostics["forced_overlong_count"] = len(chooser_result.forced_overlong_bullet_ids)
    diagnostics["min_changed_target"] = chooser_result.min_changed_target

    (
        success,
        err,
        pdf_bytes,
        page_count,
        quality_passes,
        quality_issues,
        final_latex,
        effective_choices,
        dropped_bullet_ids,
        quality_fallback,
    ) = apply_and_verify(
        original_latex,
        bullets,
        choices,
        option_id_to_latex,
        target_pages,
        baseline_over_target=baseline_over_target,
    )

    if not success:
        diagnostics["mapping_integrity_passed"] = False
        diagnostics["chooser_selected"] = choices
        if debug_enabled():
            debug_log(
                logger,
                "v3_final_apply_failure",
                error=err,
                chosen_count=len(choices),
                chooser_selected=choices,
                dropped_bullet_ids=dropped_bullet_ids,
            )
        return V3OptimizationResult(
            success=False,
            error_message=err,
            optimized_latex=original_latex,
            pdf_bytes=compile_result.pdf_bytes if compile_result else None,
            page_count=compile_result.page_count if compile_result else 0,
            passes_done=used_iterations,
            token_usage=token_usage_acc,
            diagnostics=diagnostics,
        )

    diagnostics["chooser_selected"] = choices
    diagnostics["chooser_effective_selected"] = effective_choices
    diagnostics["stage3_dropped_bullet_ids"] = dropped_bullet_ids
    diagnostics["stage3_dropped_bullet_count"] = len(dropped_bullet_ids)
    diagnostics["stage3_quality_fallback"] = quality_fallback
    # Only a genuine inherent content-fit failure (the stage3 short-circuit actually
    # fired) should suppress the worker's terminal alert. Every other success=False
    # path returns earlier with content_fit_failure=False so real infra failures
    # (API-key/chooser/ownership/compile errors) still page ops.
    diagnostics["content_fit_failure"] = bool(
        isinstance(quality_fallback, dict)
        and quality_fallback.get("skipped_reason") == "baseline_over_target"
    )
    diagnostics["fallback_filled_bullet_ids"] = chooser_result.missing_filled_bullet_ids
    changed_bullet_count = sum(1 for bid, oid in effective_choices.items() if oid != f"b{bid}_orig")
    diagnostics["changed_bullet_count"] = changed_bullet_count
    diagnostics["original_kept_count"] = len(effective_choices) - changed_bullet_count
    diagnostics["j"] = len(all_candidates)
    diagnostics["mapping_integrity_passed"] = True
    diagnostics["final_page_count"] = page_count
    diagnostics["final_quality_passes"] = quality_passes
    diagnostics["final_quality_issues_summary"] = quality_issues
    if pdf_bytes:
        final_quality = check_quality(pdf_bytes=pdf_bytes, target_pages=target_pages, latex=final_latex)
        diagnostics["final_long_bullet_count"] = len(final_quality.long_bullets)
        diagnostics["final_long_bullets"] = _compact_long_bullets(final_quality.long_bullets)
    # Drop large refs so they can be GC'd before return
    all_candidates.clear()

    return V3OptimizationResult(
        success=quality_passes,
        optimized_latex=final_latex,
        error_message=None if quality_passes else quality_issues,
        pdf_bytes=pdf_bytes,
        page_count=page_count,
        passes_done=used_iterations,
        quality_passes=quality_passes,
        quality_issues_summary=quality_issues,
        token_usage=token_usage_acc,
        diagnostics=diagnostics,
    )
