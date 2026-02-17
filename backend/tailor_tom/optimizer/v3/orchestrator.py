"""V3 orchestrator: Stage 0-3 pipeline with two-pass feasibility and chooser authority."""

import logging
from typing import Optional

from tailor_tom.optimizer.v3.types import V3OptimizationResult, TokenUsage
from tailor_tom.optimizer.v3.llm_usage import merge_usage, usage_from_counts
from tailor_tom.optimizer.v3.stage0_preprocess import run_stage0, Stage0Result
from tailor_tom.optimizer.v3.stage1_generator import generate_candidates, GeneratedCandidate
from tailor_tom.optimizer.v3.stage2_validation import run_feasibility, FeasibilityResult
from tailor_tom.optimizer.v3.stage3_chooser import run_chooser, apply_and_verify
from tailor_tom.optimizer.v3.debug_logging import debug_enabled, debug_log
from tailor_tom.optimizer.v3.stage2_validation import (
    REASON_APPLY_NO_EFFECT,
    REASON_COMPILE_FAILED,
    REASON_LINE_COUNT_MISMATCH,
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
        REASON_LINE_COUNT_MISMATCH: "Preserve line count so bullet fits layout.",
    }
    return hints.get(reason_code, "Address validation failure.")


def optimize_resume_v3(
    resume_latex: str,
    job_description: str,
    target_pages: int = 1,
    max_iterations: int = 3,
    max_bullet_lines: int = 2,
    job_id: Optional[str] = None,
) -> V3OptimizationResult:
    """Run V3 Stage 0-3. No V2 logic; chooser is sole authority. Hard fail before Stage 3 if any bullet has zero feasible generated."""
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
    if s0.no_eligible:
        return V3OptimizationResult(
            success=True,
            optimized_latex=resume_latex,
            pdf_bytes=s0.compile_result.pdf_bytes if s0.compile_result else None,
            page_count=s0.compile_result.page_count if s0.compile_result else 0,
            passes_done=0,
            quality_passes=True,
            token_usage=usage_from_counts(0, 0, 0.0, "estimated"),
            diagnostics={"stage": "stage0", "no_eligible": True, "k": 0},
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
        "pass1_reason_histogram_by_iter": [],
        "pass2_reason_histogram_by_iter": [],
        "bullets_with_zero_feasible_generated": [],
        "early_stop": False,
        "max_iterations_used": 0,
    }

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
        used_iterations += 1
        feasible_generated_by_bullet = _feasible_generated_by_bullet()
        bullets_with_zero = [b.bullet_id for b in bullets if not feasible_generated_by_bullet.get(b.bullet_id)]
        diagnostics["bullets_with_zero_feasible_generated"] = bullets_with_zero

        if not bullets_with_zero:
            diagnostics["early_stop"] = True
            diagnostics["max_iterations_used"] = used_iterations - 1
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
                bullet = bullet_by_id.get(c.bullet_id)
                repl = (c.replacement_latex or "").strip()
                repl_plain = repl  # use as-is for char count; word count from split
                repl_words = len(repl_plain.split()) if repl_plain else 0
                repl_chars = len(repl_plain)
                word_delta = repl_words - bullet.word_count if bullet else 0
                char_delta = repl_chars - bullet.char_count if bullet else 0
                old_lines = bullet.line_count if bullet else 0
                repair_hint = _repair_hint_for_reason(reason_code)
                part = f"reason_code={reason_code}; old_lines={old_lines}; word_delta={word_delta:+d}; char_delta={char_delta:+d}; repair_hint={repair_hint}"
                failed_feedback[c.bullet_id] = failed_feedback.get(c.bullet_id, "") + (" | " if failed_feedback.get(c.bullet_id) else "") + part

        gen_bullets = bullets if iteration == 0 else [b for b in bullets if b.bullet_id in bullets_with_zero]

        new_candidates, usage = generate_candidates(
            gen_bullets,
            job_description,
            failed_feedback=failed_feedback if iteration > 0 else None,
            iteration=iteration,
        )
        token_usage_acc = merge_usage(token_usage_acc, usage)
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
        return V3OptimizationResult(
            success=False,
            error_message="At least one bullet has zero feasible generated candidates after max iterations",
            optimized_latex=original_latex,
            pdf_bytes=compile_result.pdf_bytes if compile_result else None,
            page_count=compile_result.page_count if compile_result else 0,
            passes_done=used_iterations,
            token_usage=token_usage_acc,
            diagnostics={**diagnostics, "bullets_with_zero_feasible_generated": bullets_with_zero_final},
        )

    # Build options per bullet for chooser
    options_per_bullet: dict[int, list[str]] = {}
    for b in bullets:
        opts = [oid for oid in feasible_option_ids if oid == f"b{b.bullet_id}_orig" or (oid.startswith(f"b{b.bullet_id}_") and oid != f"b{b.bullet_id}_orig")]
        options_per_bullet[b.bullet_id] = sorted(opts)

    chooser_result = run_chooser(
        original_latex,
        bullets,
        options_per_bullet,
        option_id_to_latex,
        job_description,
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

    success, err, pdf_bytes, page_count, quality_passes, quality_issues = apply_and_verify(
        original_latex,
        bullets,
        choices,
        option_id_to_latex,
        target_pages,
        max_bullet_lines,
    )

    if not success:
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

    # Build optimized_latex from applied choices (we need to re-apply to get string)
    from tailor_tom.optimizer.v3.stage3_chooser import _apply_choices_to_latex
    final_latex, _ = _apply_choices_to_latex(original_latex, bullets, choices, option_id_to_latex)

    diagnostics["chooser_selected"] = choices
    diagnostics["fallback_filled_bullet_ids"] = chooser_result.missing_filled_bullet_ids
    changed_bullet_count = sum(1 for bid, oid in choices.items() if oid != f"b{bid}_orig")
    diagnostics["changed_bullet_count"] = changed_bullet_count
    diagnostics["original_kept_count"] = len(choices) - changed_bullet_count
    diagnostics["j"] = len(all_candidates)
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
