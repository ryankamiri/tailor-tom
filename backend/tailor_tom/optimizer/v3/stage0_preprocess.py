"""Stage 0: compile original, extract bullet constraints, determine eligible bullets, build original options."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional

from tailor_tom.config import get_settings
from tailor_tom.latex_compiler import CompileResult, compile_latex
from tailor_tom.layout_analyzer import extract_line_metrics, extract_items_from_latex

from tailor_tom.optimizer.v3.debug_logging import debug_enabled, debug_log

import logging

logger = logging.getLogger(__name__)

# Mapping status for ownership tracking
MAPPING_STATUS_MAPPED = "mapped"
MAPPING_STATUS_DROPPED_UNMATCHED = "dropped_unmatched"
MAPPING_STATUS_DROPPED_LOW_CONFIDENCE = "dropped_low_confidence"


# Section names that are not editable (V1-equivalent eligibility)
_NON_EDITABLE_SECTIONS = ("Education", "Skills", "Unknown")
_MIN_WORDS_ELIGIBLE = 3
_MAX_BULLET_LINES = 3

# Education content phrases (protect from editing)
_EDUCATION_CONTENT_PHRASES = (
    "gpa", "grade point average", "relevant coursework", "coursework:",
    "candidate for bachelor", "candidate for master", "b.s.", "m.s.", "b.a.", "m.a.",
    "bachelor of ", "master of ", "b.s. in ", "m.s. in ", "ph.d", "phd ",
    "expected graduation", "graduated ", "graduation:", "dean's list", "honor roll",
    "cum laude", "magna cum laude", "summa cum laude", "major in ", "minor in ",
    "concentration in ",
)

# Section markers (preceding text): (substring, section_name). Last match wins.
_SECTION_MARKERS = [
    ("skills", "Skills"), ("technical skills", "Skills"), ("core competencies", "Skills"),
    ("education", "Education"), ("academic", "Education"), ("degree", "Education"),
    ("coursework", "Education"), ("certification", "Education"), ("certifications", "Education"),
    ("research", "Research"), ("publications", "Research"), ("project", "Projects"),
    ("portfolio", "Projects"), ("experience", "Experience"), ("employment", "Experience"),
    ("work history", "Experience"), ("work", "Experience"), ("professional", "Experience"),
    ("training", "Experience"),
]


@dataclass
class BulletConstraint:
    """Constraint for a single bullet (V3 copy of V1-style fields). Ownership and mapping are explicit."""
    bullet_id: int
    section: str
    original_text: str
    latex_snippet: str
    line_count: int
    word_count: int
    char_count: int
    target_line_count: int = _MAX_BULLET_LINES
    snippet_occurrence_index: int = 0  # N-th occurrence of this snippet in original latex (0-based)
    source_item_index: int = -1  # 0-based index in LaTeX items (stable ownership key)
    mapping_similarity: float = 0.0
    mapping_status: str = MAPPING_STATUS_DROPPED_UNMATCHED  # mapped | dropped_unmatched | dropped_low_confidence


def _strip_latex_commands(latex_text: str) -> str:
    """Strip LaTeX formatting to plain text for word/char counting (V1-equivalent)."""
    text = (latex_text or "").replace(r"\%", "%").replace(r"\&", "&").replace(r"\$", "$")
    text = text.replace(r"\_", "_").replace(r"\#", "#")
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)
    for _ in range(3):
        text = re.sub(r"\\(?:textbf|textit|emph|underline|textsc|textsf|texttt)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})?", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _detect_section_for_bullet(latex: str, latex_snippet: str) -> str:
    """Detect section from content heuristics then preceding LaTeX (V1-equivalent)."""
    if not latex_snippet:
        return "Unknown"
    plain = _strip_latex_commands(latex_snippet).lower()
    for phrase in _EDUCATION_CONTENT_PHRASES:
        if phrase in plain:
            return "Education"
    pos = latex.find(latex_snippet)
    if pos == -1:
        return "Unknown"
    preceding = latex[:pos].lower()
    best_section = "Experience"
    best_pos = -1
    for marker, section_name in _SECTION_MARKERS:
        pattern_pos = preceding.rfind(marker)
        if pattern_pos > best_pos:
            best_pos = pattern_pos
            best_section = section_name
    return best_section


def _normalized_similarity(a: str, b: str) -> float:
    """Normalized similarity in [0, 1] for confidence filter (whitespace-normalized)."""
    a = " ".join((a or "").split())
    b = " ".join((b or "").split())
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _find_all_occurrence_offsets(haystack: str, needle: str) -> list[int]:
    """Return all 0-based character offsets of needle in haystack."""
    if not needle:
        return []
    offsets: list[int] = []
    start = 0
    while True:
        pos = haystack.find(needle, start)
        if pos == -1:
            break
        offsets.append(pos)
        start = pos + len(needle)
    return offsets


def _global_occurrence_index_for_constraint(
    latex: str,
    latex_items: list[dict[str, Any]],
    constraint: BulletConstraint,
) -> int:
    """Compute snippet occurrence index against global LaTeX string occurrences.

    Falls back to source-item occurrence among extracted items when global position
    cannot be resolved.
    """
    snippet = constraint.latex_snippet or ""
    if not snippet:
        return 0

    all_offsets = _find_all_occurrence_offsets(latex, snippet)
    if not all_offsets:
        return 0

    src_idx = int(getattr(constraint, "source_item_index", -1))
    source_pos = -1
    if 0 <= src_idx < len(latex_items):
        raw_pos = latex_items[src_idx].get("source_pos")
        try:
            if raw_pos is not None:
                source_pos = int(raw_pos)
        except (TypeError, ValueError):
            source_pos = -1

    if source_pos >= 0:
        # Pick closest global occurrence to the owned source position.
        best_i = min(range(len(all_offsets)), key=lambda i: abs(all_offsets[i] - source_pos))
        return int(best_i)

    # Fallback: count identical snippets up to owned source item index across all extracted items.
    if src_idx >= 0:
        count = 0
        for i, item in enumerate(latex_items):
            if (item.get("latex") or "") == snippet:
                if i == src_idx:
                    return count
                count += 1
    return 0


def _extract_bullet_constraints(
    pdf_bytes: bytes,
    latex: str,
    mapping_threshold: float,
) -> tuple[list[BulletConstraint], dict[str, Any]]:
    """Extract bullet constraints from bullets_data using latex_source (no index pairing).
    Returns (all constraints with mapping_status set, diagnostics dict).
    """
    bullet_metrics = extract_line_metrics(pdf_bytes, latex=latex)
    bullets_data = bullet_metrics.get("bullets", [])
    latex_items = extract_items_from_latex(latex)
    stage0_total_latex_items = len(latex_items)
    stage0_matched_items = len(bullets_data)
    dropped_unmatched: list[int] = []
    dropped_low_confidence: list[int] = []
    dropped_by_section: list[int] = []
    dropped_too_short: list[int] = []

    constraints: list[BulletConstraint] = []
    for bullet in bullets_data:
        item_index = bullet.get("item_index")
        if item_index is None:
            # Legacy path or missing extraction metadata: treat as unmatched
            bullet_id = len(constraints) + 1
            dropped_unmatched.append(bullet_id)
            constraints.append(BulletConstraint(
                bullet_id=bullet_id,
                section="Unknown",
                original_text="",
                latex_snippet="",
                line_count=0,
                word_count=0,
                char_count=0,
                target_line_count=_MAX_BULLET_LINES,
                source_item_index=-1,
                mapping_similarity=0.0,
                mapping_status=MAPPING_STATUS_DROPPED_UNMATCHED,
            ))
            continue

        latex_snippet = bullet.get("latex_source") or ""
        match_similarity = float(bullet.get("match_similarity", 0.0))
        text_preview = bullet.get("text_preview", "")
        lines_text = bullet.get("lines_text", [])
        full_text = " ".join(lines_text) if lines_text else text_preview
        clean_text = full_text.strip()
        line_count = bullet.get("line_count", 1)
        word_count = len(clean_text.split()) if clean_text else 0
        char_count = len(clean_text) if clean_text else 0

        if not latex_snippet:
            dropped_unmatched.append(item_index + 1)
            constraints.append(BulletConstraint(
                bullet_id=item_index + 1,
                section="Unknown",
                original_text=clean_text,
                latex_snippet="",
                line_count=line_count,
                word_count=word_count,
                char_count=char_count,
                target_line_count=min(line_count, _MAX_BULLET_LINES),
                source_item_index=item_index,
                mapping_similarity=match_similarity,
                mapping_status=MAPPING_STATUS_DROPPED_UNMATCHED,
            ))
            continue

        # Confidence filter: normalized similarity between original_text and stripped latex_source
        stripped_snippet = _strip_latex_commands(latex_snippet)
        sim = _normalized_similarity(clean_text, stripped_snippet)
        if sim < mapping_threshold:
            dropped_low_confidence.append(item_index + 1)
            constraints.append(BulletConstraint(
                bullet_id=item_index + 1,
                section="Unknown",
                original_text=clean_text,
                latex_snippet=latex_snippet,
                line_count=line_count,
                word_count=word_count,
                char_count=char_count,
                target_line_count=min(line_count, _MAX_BULLET_LINES),
                source_item_index=item_index,
                mapping_similarity=sim,
                mapping_status=MAPPING_STATUS_DROPPED_LOW_CONFIDENCE,
            ))
            continue

        section = _detect_section_for_bullet(latex, latex_snippet)
        constraints.append(BulletConstraint(
            bullet_id=item_index + 1,
            section=section,
            original_text=clean_text,
            latex_snippet=latex_snippet,
            line_count=line_count,
            word_count=word_count,
            char_count=char_count,
            target_line_count=min(line_count, _MAX_BULLET_LINES),
            source_item_index=item_index,
            mapping_similarity=sim,
            mapping_status=MAPPING_STATUS_MAPPED,
        ))

    # Eligible before confidence = count with mapping_status == "mapped"
    stage0_eligible_before_confidence_filter = sum(
        1 for c in constraints if c.mapping_status == MAPPING_STATUS_MAPPED
    )
    stage0_dropped_unmatched_count = len(dropped_unmatched)
    stage0_dropped_low_confidence_count = len(dropped_low_confidence)

    # Filter to mapped-only for section/short and compute global snippet_occurrence_index
    mapped_constraints = [c for c in constraints if c.mapping_status == MAPPING_STATUS_MAPPED]
    mapped_constraints.sort(key=lambda c: c.source_item_index)
    for c in mapped_constraints:
        c.snippet_occurrence_index = _global_occurrence_index_for_constraint(latex, latex_items, c)

    # Section and too-short filters (only among mapped)
    eligible: list[BulletConstraint] = []
    for c in mapped_constraints:
        if c.section in _NON_EDITABLE_SECTIONS:
            dropped_by_section.append(c.bullet_id)
            continue
        if c.word_count < _MIN_WORDS_ELIGIBLE:
            dropped_too_short.append(c.bullet_id)
            continue
        eligible.append(c)

    stage0_dropped_by_section_count = len(dropped_by_section)
    stage0_dropped_too_short_count = len(dropped_too_short)

    diagnostics: dict[str, Any] = {
        "stage0_total_latex_items": stage0_total_latex_items,
        "stage0_matched_items": stage0_matched_items,
        "stage0_eligible_before_confidence_filter": stage0_eligible_before_confidence_filter,
        "stage0_dropped_unmatched_count": stage0_dropped_unmatched_count,
        "stage0_dropped_low_confidence_count": stage0_dropped_low_confidence_count,
        "stage0_dropped_by_section_count": stage0_dropped_by_section_count,
        "stage0_dropped_too_short_count": stage0_dropped_too_short_count,
        "stage0_dropped_unmatched_sample": dropped_unmatched[:20],
        "stage0_dropped_low_confidence_sample": dropped_low_confidence[:20],
        "stage0_dropped_by_section_sample": dropped_by_section[:20],
        "stage0_dropped_too_short_sample": dropped_too_short[:20],
        "stage0_global_occurrence_index_sample": [
            {
                "bullet_id": c.bullet_id,
                "source_item_index": c.source_item_index,
                "snippet_occurrence_index": c.snippet_occurrence_index,
            }
            for c in mapped_constraints[:20]
        ],
    }
    return eligible, diagnostics


def replace_nth(latex: str, old: str, new: str, n: int) -> tuple[str, bool]:
    """Replace the (n+1)-th occurrence of old with new in latex. Returns (new_latex, applied). n is 0-based."""
    if not old:
        return latex, False
    start = 0
    for i in range(n + 1):
        pos = latex.find(old, start)
        if pos == -1:
            return latex, False
        if i == n:
            return latex[:pos] + new + latex[pos + len(old) :], True
        start = pos + len(old)
    return latex, False


@dataclass
class Stage0Result:
    """Result of Stage 0 preprocessing."""
    success: bool
    error_message: Optional[str] = None
    original_latex: str = ""
    compile_result: Optional[CompileResult] = None
    no_eligible: bool = False
    eligible_bullets: list[BulletConstraint] = field(default_factory=list)
    original_options: dict[int, dict[str, str]] = field(default_factory=dict)
    stage0_diagnostics: Optional[dict[str, Any]] = None


def run_stage0(original_latex: str) -> Stage0Result:
    """Compile original, extract bullets, filter eligible, build original options.
    On compile failure: success=False, error_message set.
    On no eligible bullets: success=True, no_eligible=True, compile_result and stage0_diagnostics set (no-op success).
    Otherwise: success=True, no_eligible=False, eligible_bullets and original_options set.
    """
    compile_result = compile_latex(original_latex)
    if not compile_result.success:
        return Stage0Result(
            success=False,
            error_message=compile_result.error_message or "Original resume compilation failed",
            original_latex=original_latex,
        )
    settings = get_settings()
    threshold = getattr(settings, "optimizer_mapping_min_similarity", 0.74)
    eligible, stage0_diagnostics = _extract_bullet_constraints(
        compile_result.pdf_bytes or b"",
        original_latex,
        mapping_threshold=threshold,
    )
    if not eligible:
        if debug_enabled():
            debug_log(logger, "stage0_no_eligible", diagnostics=stage0_diagnostics)
        return Stage0Result(
            success=True,
            original_latex=original_latex,
            compile_result=compile_result,
            no_eligible=True,
            stage0_diagnostics=stage0_diagnostics,
        )
    original_options = {}
    for b in eligible:
        original_options[b.bullet_id] = {
            "option_id": f"b{b.bullet_id}_orig",
            "latex": b.latex_snippet,
        }
    if debug_enabled():
        debug_log(logger, "stage0_eligible", k=len(eligible), bullet_ids=[b.bullet_id for b in eligible])
    return Stage0Result(
        success=True,
        original_latex=original_latex,
        compile_result=compile_result,
        no_eligible=False,
        eligible_bullets=eligible,
        original_options=original_options,
        stage0_diagnostics=stage0_diagnostics,
    )
