"""Stage 0: compile original, extract bullet constraints, determine eligible bullets, build original options."""

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from tailor_tom.latex_compiler import CompileResult, compile_latex
from tailor_tom.layout_analyzer import extract_line_metrics, extract_items_from_latex

from tailor_tom.optimizer.v3.debug_logging import debug_enabled, debug_log

import logging

logger = logging.getLogger(__name__)


# Section names that are not editable (V1-equivalent eligibility)
_NON_EDITABLE_SECTIONS = ("Education", "Skills", "Unknown")
_MIN_WORDS_ELIGIBLE = 3

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
    """Constraint for a single bullet (V3 copy of V1-style fields)."""
    bullet_id: int
    section: str
    original_text: str
    latex_snippet: str
    line_count: int
    word_count: int
    char_count: int
    snippet_occurrence_index: int = 0  # N-th occurrence of this snippet in original latex (0-based)


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


def _extract_bullet_constraints(pdf_bytes: bytes, latex: str) -> list[BulletConstraint]:
    """Extract bullet constraints from compiled PDF and LaTeX (V1-equivalent)."""
    bullet_metrics = extract_line_metrics(pdf_bytes, latex=latex)
    bullets_data = bullet_metrics.get("bullets", [])
    latex_items = extract_items_from_latex(latex)
    constraints = []
    for i, bullet in enumerate(bullets_data):
        text_preview = bullet.get("text_preview", "")
        lines_text = bullet.get("lines_text", [])
        full_text = " ".join(lines_text) if lines_text else text_preview
        clean_text = full_text.strip()
        line_count = bullet.get("line_count", 1)
        word_count = len(clean_text.split()) if clean_text else 0
        char_count = len(clean_text) if clean_text else 0
        latex_snippet = ""
        if i < len(latex_items):
            latex_snippet = latex_items[i].get("latex", "")
        section = _detect_section_for_bullet(latex, latex_snippet)
        constraints.append(BulletConstraint(
            bullet_id=i + 1,
            section=section,
            original_text=clean_text,
            latex_snippet=latex_snippet,
            line_count=line_count,
            word_count=word_count,
            char_count=char_count,
        ))
    # Assign snippet_occurrence_index: N-th occurrence of same snippet in document order (0-based)
    snippet_next_index: dict[str, int] = {}
    for c in constraints:
        s = c.latex_snippet
        if s not in snippet_next_index:
            snippet_next_index[s] = 0
        c.snippet_occurrence_index = snippet_next_index[s]
        snippet_next_index[s] += 1
    return constraints


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


def run_stage0(original_latex: str) -> Stage0Result:
    """Compile original, extract bullets, filter eligible, build original options.
    On compile failure: success=False, error_message set.
    On no eligible bullets: success=True, no_eligible=True, compile_result set (no-op success).
    Otherwise: success=True, no_eligible=False, eligible_bullets and original_options set.
    """
    compile_result = compile_latex(original_latex)
    if not compile_result.success:
        return Stage0Result(
            success=False,
            error_message=compile_result.error_message or "Original resume compilation failed",
            original_latex=original_latex,
        )
    all_constraints = _extract_bullet_constraints(
        compile_result.pdf_bytes or b"",
        original_latex,
    )
    eligible = [
        c for c in all_constraints
        if c.section not in _NON_EDITABLE_SECTIONS and c.word_count >= _MIN_WORDS_ELIGIBLE
    ]
    if not eligible:
        if debug_enabled():
            debug_log(logger, "stage0_no_eligible", total_bullets=len(all_constraints))
        return Stage0Result(
            success=True,
            original_latex=original_latex,
            compile_result=compile_result,
            no_eligible=True,
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
    )
