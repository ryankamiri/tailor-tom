"""Stage 2: two-pass feasibility (pass1 static, pass2 slot compile) and reason codes."""

import re
from dataclasses import dataclass, field
from typing import Optional

from tailor_tom.config import settings
from tailor_tom.latex_compiler import compile_latex
from tailor_tom.layout_analyzer import extract_line_metrics

from tailor_tom.optimizer.v3.stage0_preprocess import BulletConstraint, _strip_latex_commands, replace_nth
from tailor_tom.optimizer.v3.stage1_generator import GeneratedCandidate
from tailor_tom.optimizer.v3.debug_logging import debug_enabled, debug_log

import logging

logger = logging.getLogger(__name__)

# Pass1 reason codes (standardized for retry feedback and diagnostics)
REASON_TOO_LONG_WORDS = "too_long_words"
REASON_TOO_LONG_CHARS = "too_long_chars"
REASON_TOO_SHORT_WORDS = "too_short_words"
REASON_TOO_SHORT_PERCENT = "too_short_percent"
REASON_SNIPPET_NOT_FOUND = "snippet_not_found"
REASON_ANCHORED_SNIPPET_NOT_FOUND = "anchored_snippet_not_found"
REASON_APPLY_NO_EFFECT = "apply_no_effect"
REASON_INVALID_PAYLOAD = "invalid_payload"
REASON_COMPILE_FAILED = "compile_failed"
REASON_LINE_COUNT_MISMATCH = "line_count_mismatch"


def _validate_pass1(
    bullet: BulletConstraint,
    replacement_latex: str,
) -> tuple[bool, str]:
    """Pass1 static checks. Returns (ok, reason_code). Uses settings for limits."""
    max_word_growth = max(0, int(getattr(settings, "optimizer_max_word_growth", 0)))
    max_char_growth = max(0, int(getattr(settings, "optimizer_max_char_growth", 10)))
    max_shrink_words = max(0, int(getattr(settings, "optimizer_max_shrink_words", 3)))
    max_shrink_percent = max(0.0, min(1.0, float(getattr(settings, "optimizer_max_shrink_percent", 0.15))))

    clean = _strip_latex_commands(replacement_latex or "")
    repl_words = len(clean.split()) if clean else 0
    repl_chars = len(clean) if clean else 0

    if repl_words > bullet.word_count + max_word_growth:
        return False, REASON_TOO_LONG_WORDS
    if repl_chars > bullet.char_count + max_char_growth:
        return False, REASON_TOO_LONG_CHARS
    word_shrink = bullet.word_count - repl_words
    if word_shrink > max_shrink_words:
        return False, REASON_TOO_SHORT_WORDS
    if bullet.char_count > 0:
        char_shrink = (bullet.char_count - repl_chars) / bullet.char_count
        if char_shrink > max_shrink_percent:
            return False, REASON_TOO_SHORT_PERCENT
    if repl_words < 2:
        return False, REASON_TOO_SHORT_WORDS

    return True, ""


def _apply_replacement_to_latex(
    latex: str,
    bullet: BulletConstraint,
    replacement_latex: str,
) -> tuple[str, bool, bool]:
    """Apply one replacement using anchored occurrence. Returns (new_latex, applied, was_noop)."""
    if not bullet.latex_snippet:
        return latex, False, False
    orig_norm = " ".join(bullet.latex_snippet.split())
    repl_norm = " ".join((replacement_latex or "").split())
    if orig_norm == repl_norm:
        return latex, True, True
    n = getattr(bullet, "snippet_occurrence_index", 0)
    new_latex, applied = replace_nth(latex, bullet.latex_snippet, replacement_latex or "", n)
    if not applied:
        return latex, False, False
    return new_latex, True, False


def _verify_line_counts(
    bullets: list[BulletConstraint],
    pdf_bytes: bytes,
    latex: str,
) -> dict[int, tuple[int, int]]:
    """Return dict bullet_id -> (original_line_count, new_line_count) for bullets that changed."""
    metrics = extract_line_metrics(pdf_bytes, latex=latex)
    new_bullets = metrics.get("bullets", [])
    failures: dict[int, tuple[int, int]] = {}
    for b in bullets:
        idx = b.bullet_id - 1
        if idx < len(new_bullets):
            new_lines = new_bullets[idx].get("line_count", 0)
            if new_lines != b.line_count:
                failures[b.bullet_id] = (b.line_count, new_lines)
    return failures


def _slot_from_option_id(option_id: str) -> Optional[int]:
    """Parse b{N}_c{idx}_it* -> idx (1-based slot). Returns None if not generated candidate."""
    if not option_id or "_c" not in option_id:
        return None
    try:
        part = option_id.split("_c", 1)[1]
        idx_str = part.split("_")[0]
        return int(idx_str)
    except (IndexError, ValueError):
        return None


def _iteration_from_option_id(option_id: str) -> int:
    """Parse _itN from option_id (e.g. b1_c2_it3 -> 3). Returns 0 if absent."""
    if not option_id or "_it" not in option_id:
        return 0
    try:
        return int(option_id.split("_it")[-1])
    except (IndexError, ValueError):
        return 0


@dataclass
class FeasibilityResult:
    """Result of Stage 2 two-pass feasibility."""
    feasible_option_ids: set[str] = field(default_factory=set)
    pass1_fail: dict[str, str] = field(default_factory=dict)  # option_id -> reason_code
    pass2_fail: dict[str, str] = field(default_factory=dict)
    pass1_reason_histogram: dict[str, int] = field(default_factory=dict)
    pass2_reason_histogram: dict[str, int] = field(default_factory=dict)
    no_effect_candidate_count: int = 0
    duplicate_slot_candidates_count: int = 0
    canonicalized_candidate_pairs_count: int = 0


def run_feasibility(
    original_latex: str,
    bullets: list[BulletConstraint],
    candidates: list[GeneratedCandidate],
) -> FeasibilityResult:
    """Run pass1 then pass2. Only candidates that pass both are feasible.
    Pass2: one compile per slot; line-count failure invalidates only that bullet's candidate for that slot.
    """
    bullet_by_id = {b.bullet_id: b for b in bullets}
    n_slots = max(1, getattr(settings, "candidates_per_bullet", 2))

    # Pass1: static + snippet apply
    pass1_ok: set[str] = set()
    pass1_fail: dict[str, str] = {}
    for c in candidates:
        bullet = bullet_by_id.get(c.bullet_id)
        if not bullet:
            pass1_fail[c.option_id] = REASON_INVALID_PAYLOAD
            continue
        ok, reason = _validate_pass1(bullet, c.replacement_latex)
        if not ok:
            pass1_fail[c.option_id] = reason
            continue
        _, applied, noop = _apply_replacement_to_latex(original_latex, bullet, c.replacement_latex)
        if noop:
            pass1_fail[c.option_id] = REASON_APPLY_NO_EFFECT
            continue
        if not applied:
            pass1_fail[c.option_id] = REASON_ANCHORED_SNIPPET_NOT_FOUND
            continue
        pass1_ok.add(c.option_id)

    pass1_hist: dict[str, int] = {}
    for r in pass1_fail.values():
        pass1_hist[r] = pass1_hist.get(r, 0) + 1
    no_effect_candidate_count = sum(1 for r in pass1_fail.values() if r == REASON_APPLY_NO_EFFECT)

    # Canonicalize: one candidate per (bullet_id, slot). Highest iteration wins; tie-break lexicographic option_id.
    candidate_by_option: dict[str, GeneratedCandidate] = {c.option_id: c for c in candidates}
    key_to_candidates: dict[tuple[int, int], list[GeneratedCandidate]] = {}
    for oid in pass1_ok:
        c = candidate_by_option.get(oid)
        if not c:
            continue
        slot = _slot_from_option_id(oid)
        if slot is not None and 1 <= slot <= n_slots:
            key = (c.bullet_id, slot)
            key_to_candidates.setdefault(key, []).append(c)
    duplicate_slot_candidates_count = 0
    canonicalized_candidate_pairs_count = 0
    canonical_per_key: dict[tuple[int, int], GeneratedCandidate] = {}
    for key, lst in key_to_candidates.items():
        if len(lst) > 1:
            canonicalized_candidate_pairs_count += 1
            duplicate_slot_candidates_count += len(lst) - 1
        # Highest iteration wins; tie-break: lexicographically smallest option_id
        best = sorted(lst, key=lambda x: (-_iteration_from_option_id(x.option_id), x.option_id))[0]
        canonical_per_key[key] = best
    if debug_enabled() and (duplicate_slot_candidates_count or canonicalized_candidate_pairs_count):
        kept = [c.option_id for c in canonical_per_key.values()]
        dropped = [c.option_id for key, lst in key_to_candidates.items() for c in lst if c is not canonical_per_key[key]]
        debug_log(logger, "stage2_canonical", duplicate_slot_candidates_count=duplicate_slot_candidates_count, canonicalized_candidate_pairs_count=canonicalized_candidate_pairs_count, sample_kept=kept[:5], sample_dropped=dropped[:5])

    # Pass2: per-slot compile using canonical candidates only, stable bullet order (bullet_id ascending)
    pass2_fail: dict[str, str] = {}
    by_slot: dict[int, list[GeneratedCandidate]] = {s: [] for s in range(1, n_slots + 1)}
    for (bid, slot), c in canonical_per_key.items():
        by_slot[slot].append(c)
    for slot in range(1, n_slots + 1):
        slot_candidates = sorted(by_slot[slot], key=lambda x: x.bullet_id)
        if not slot_candidates:
            continue
        test_latex = original_latex
        bullet_candidate: dict[int, GeneratedCandidate] = {}
        for c in slot_candidates:
            bullet = bullet_by_id.get(c.bullet_id)
            if not bullet:
                continue
            test_latex, applied, _ = _apply_replacement_to_latex(test_latex, bullet, c.replacement_latex)
            if applied:
                bullet_candidate[c.bullet_id] = c
        if not bullet_candidate:
            continue
        compile_result = compile_latex(test_latex)
        if not compile_result.success:
            for oid in (c.option_id for c in bullet_candidate.values()):
                pass2_fail[oid] = REASON_COMPILE_FAILED
            continue
        bullets_changed = list(bullet_candidate.keys())
        line_failures = _verify_line_counts(
            [bullet_by_id[bid] for bid in bullets_changed],
            compile_result.pdf_bytes or b"",
            test_latex,
        )
        for bid in line_failures:
            c = bullet_candidate.get(bid)
            if c:
                pass2_fail[c.option_id] = REASON_LINE_COUNT_MISMATCH

    pass2_hist = {REASON_COMPILE_FAILED: 0, REASON_LINE_COUNT_MISMATCH: 0}
    for r in pass2_fail.values():
        pass2_hist[r] = pass2_hist.get(r, 0) + 1

    canonical_option_ids = {c.option_id for c in canonical_per_key.values()}
    feasible = canonical_option_ids - set(pass2_fail.keys())
    if debug_enabled():
        debug_log(logger, "stage2_feasibility", pass1_ok=len(pass1_ok), pass1_fail=len(pass1_fail), pass2_fail=len(pass2_fail), feasible=len(feasible))
    return FeasibilityResult(
        feasible_option_ids=feasible,
        pass1_fail=pass1_fail,
        pass2_fail=pass2_fail,
        pass1_reason_histogram=pass1_hist,
        pass2_reason_histogram=pass2_hist,
        no_effect_candidate_count=no_effect_candidate_count,
        duplicate_slot_candidates_count=duplicate_slot_candidates_count,
        canonicalized_candidate_pairs_count=canonicalized_candidate_pairs_count,
    )
