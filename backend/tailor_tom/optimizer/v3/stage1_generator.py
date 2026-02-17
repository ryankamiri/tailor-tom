"""Stage 1: n-candidate generation per bullet (DSPy)."""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import dspy
from pydantic import BaseModel, Field

from tailor_tom.config import settings
from tailor_tom.optimizer.v3.stage0_preprocess import BulletConstraint, _strip_latex_commands
from tailor_tom.optimizer.v3.llm_usage import TokenUsage, merge_usage, usage_from_counts
from tailor_tom.optimizer.v3.usage_extractor import resolve_usage
from tailor_tom.optimizer.v3.debug_logging import debug_enabled, debug_log

logger = logging.getLogger(__name__)


class CandidateRow(BaseModel):
    """Single candidate row from LLM (bullet_id, candidate_index 1..n, replacement_latex)."""
    bullet_id: int = Field(description="Bullet ID from input")
    candidate_index: int = Field(description="Index of this candidate for that bullet (1 to n)")
    replacement_latex: str = Field(description="Optimized LaTeX for this bullet, preserving formatting")


class GenerateCandidatesOutput(BaseModel):
    """Output: list of candidates (n per bullet)."""
    candidates: list[CandidateRow] = Field(description="List of candidate replacements, n per bullet")


class GenerateCandidatesSignature(dspy.Signature):
    """Replace words in resume bullets with ATS-friendly keywords from the job description.

    LINE COUNT RULE (CRITICAL):
    - Each bullet has a specified line count.
    - Replacement must preserve that rendered line count target.
    - Longer or shorter rendered bullets are rejected downstream.

    WORD/CHAR RULES (CRITICAL):
    - Max words per bullet are provided in input.
    - Growth policy is provided in constraint_policy (max_word_growth, max_char_growth).
    - Do not exceed those growth limits.
    - Prefer word-for-word substitutions over appending clauses.

    REPLACEMENT STRATEGY:
    - Replace generic words with job-relevant keywords that fit context.
    - Preserve original meaning and facts; preserve entities, metrics, and technologies.
    - Do not keyword-stuff; obey growth/shrink constraints from constraint_policy.

    SEMANTIC RULES:
    - Keep domain relevance by bullet context (frontend/backend/ML/etc.).
    - Never invent claims, responsibilities, or outcomes.

    LATEX FORMATTING:
    - Preserve existing LaTeX style and commands.
    - Return valid replacement_latex snippets.

    MULTI-CANDIDATE OUTPUT:
    - Output exactly n_per_bullet candidates for EACH bullet_id (no fewer, no more per bullet).
    - candidate_index must be unique per bullet_id and in [1..n_per_bullet].
    - Candidate 1 = conservative/minimal edit.
    - Candidate 2+ = stronger JD-targeted wording while preserving meaning and facts.
    - If no safe improvement exists, one candidate may be unchanged/original.
    """
    job_description: str = dspy.InputField(desc="Job description with target keywords")
    bullets: str = dspy.InputField(desc="Bullets with IDs, section, line counts, max words/chars, plain text, and LaTeX")
    n_per_bullet: int = dspy.InputField(desc="Exact number of candidates required for each bullet")
    constraint_policy: str = dspy.InputField(desc="Hard constraints for growth/shrink and layout preservation")
    failed_feedback: str = dspy.InputField(desc="Optional retry feedback: reason_code, word_delta, char_delta, repair_hint per failed candidate; empty if first iteration")
    candidates: list[CandidateRow] = dspy.OutputField(desc="List of candidates: bullet_id, candidate_index (1..n), replacement_latex")


def _format_bullets_for_llm(
    bullets: list[BulletConstraint],
    failed_feedback: Optional[dict[int, str]] = None,
) -> str:
    """Format bullets for LLM with optional failure feedback."""
    lines = []
    if failed_feedback:
        lines.append("**REJECTED - Fix these issues:**")
        for bullet_id, reason in failed_feedback.items():
            lines.append(f"- B{bullet_id}: {reason}")
        lines.append("")
    for b in bullets:
        lines.append(
            f"**B{b.bullet_id}** [{b.section}] MUST stay {b.line_count} line(s), "
            f"max {b.word_count} words, original chars {b.char_count}"
        )
        lines.append(f"Plain: {b.original_text}")
        lines.append(f"LaTeX: {b.latex_snippet}")
        lines.append("")
    return "\n".join(lines)


@dataclass
class GeneratedCandidate:
    """One generated candidate with deterministic option_id."""
    bullet_id: int
    option_id: str
    replacement_latex: str


def generate_candidates(
    bullets: list[BulletConstraint],
    job_description: str,
    failed_feedback: Optional[dict[int, str]] = None,
    iteration: int = 0,
) -> tuple[list[GeneratedCandidate], TokenUsage]:
    """Generate n candidates per bullet. Returns (candidates with option_id, usage).
    Candidate IDs: b{bullet_id}_c{candidate_index}_it{iteration}.
    """
    n = max(1, min(6, getattr(settings, "candidates_per_bullet", 2)))
    max_word_growth = max(0, int(getattr(settings, "optimizer_max_word_growth", 0)))
    max_char_growth = max(0, int(getattr(settings, "optimizer_max_char_growth", 10)))
    max_shrink_words = max(0, int(getattr(settings, "optimizer_max_shrink_words", 3)))
    max_shrink_percent = max(0.0, min(1.0, float(getattr(settings, "optimizer_max_shrink_percent", 0.15))))
    bullets_str = _format_bullets_for_llm(bullets, failed_feedback)
    constraint_policy = (
        "Hard policy: "
        f"max_word_growth={max_word_growth}, "
        f"max_char_growth={max_char_growth}, "
        f"max_shrink_words={max_shrink_words}, "
        f"max_shrink_percent={max_shrink_percent:.2f}, "
        "preserve factual meaning and LaTeX formatting."
    )
    failed_feedback_text = ""
    if failed_feedback:
        failed_feedback_text = "; ".join(
            f"B{bid}: {reason}" for bid, reason in sorted(failed_feedback.items())
        )
    prompt_len = len(bullets_str) + len(job_description)

    try:
        predictor = dspy.ChainOfThought(GenerateCandidatesSignature)
        result = predictor(
            job_description=job_description,
            bullets=bullets_str,
            n_per_bullet=n,
            constraint_policy=constraint_policy,
            failed_feedback=failed_feedback_text,
        )
        raw = result.candidates if hasattr(result, "candidates") else []
        if isinstance(raw, str):
            raw = json.loads(raw) if raw.strip() else []
        if not isinstance(raw, list):
            raw = []
    except Exception as e:
        logger.warning("Stage1 generation failed: %s", e)
        return [], resolve_usage(None, prompt_len, 0)

    out: list[GeneratedCandidate] = []
    seen: set[tuple[int, int]] = set()
    malformed_count = 0
    for i, row in enumerate(raw):
        if not isinstance(row, CandidateRow):
            try:
                if isinstance(row, dict):
                    row = CandidateRow(**row)
                else:
                    malformed_count += 1
                    if debug_enabled():
                        debug_log(logger, "stage1_malformed_row", index=i, type=type(row).__name__, raw_preview=str(row)[:200])
                    continue
            except Exception as e:
                malformed_count += 1
                if debug_enabled():
                    debug_log(logger, "stage1_malformed_row", index=i, error=str(e), raw_preview=str(row)[:200] if row is not None else None)
                continue
        bid = getattr(row, "bullet_id", None)
        idx = getattr(row, "candidate_index", None)
        repl = getattr(row, "replacement_latex", "") or ""
        if bid is None or idx is None or (bid, idx) in seen:
            if debug_enabled() and (bid is None or idx is None):
                debug_log(logger, "stage1_skip_row", index=i, bullet_id=bid, candidate_index=idx, reason="missing_bid_or_idx_or_duplicate")
            continue
        if not (1 <= idx <= n):
            if debug_enabled():
                debug_log(logger, "stage1_skip_row", index=i, bullet_id=bid, candidate_index=idx, reason="index_out_of_range", n_per_bullet=n)
            continue
        seen.add((bid, idx))
        option_id = f"b{bid}_c{idx}_it{iteration}"
        out.append(GeneratedCandidate(bullet_id=bid, option_id=option_id, replacement_latex=repl))

    # Per-bullet count: expect n_per_bullet per bullet when possible
    bullet_ids_requested = {b.bullet_id for b in bullets}
    count_by_bullet: dict[int, int] = {}
    for c in out:
        count_by_bullet[c.bullet_id] = count_by_bullet.get(c.bullet_id, 0) + 1
    short_bullets = [bid for bid in bullet_ids_requested if count_by_bullet.get(bid, 0) < n]
    if debug_enabled() and (malformed_count or short_bullets):
        debug_log(logger, "stage1_parser", malformed_row_count=malformed_count, bullets_with_fewer_than_n=short_bullets, n_per_bullet=n)

    completion_len = sum(len(c.replacement_latex) for c in out)
    usage = resolve_usage(result, prompt_len, completion_len)
    if debug_enabled():
        debug_log(
            logger,
            "stage1_generated",
            iteration=iteration,
            requested_n=n,
            parsed=len(out),
            bullet_ids=[b.bullet_id for b in bullets],
            usage_source=usage.usage_source,
        )
    return out, usage
