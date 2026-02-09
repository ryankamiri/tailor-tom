"""Deterministic LaTeX renderer for structured resume JSON.

Converts a JSON resume structure into compilable LaTeX using pre-tuned
templates.  Includes a page-fitting algorithm that binary-searches over a
"tightness" parameter, re-rendering and recompiling locally (no LLM calls).
"""

import logging
from dataclasses import dataclass

from tailor_tom.latex_compiler import compile_latex

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LaTeX escaping
# ---------------------------------------------------------------------------

_LATEX_SPECIAL = {
    "&": "\\&",
    "%": "\\%",
    "$": "\\$",
    "#": "\\#",
    "_": "\\_",
    "{": "\\{",
    "}": "\\}",
    "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
}


def _escape_latex(text: str) -> str:
    """Escape LaTeX special characters in user-provided content."""
    return "".join(_LATEX_SPECIAL.get(c, c) for c in text)


def _escape_url(url: str) -> str:
    """Escape characters in a URL for use inside ``\\href{...}``."""
    return url.replace("%", "\\%")


# ---------------------------------------------------------------------------
# Spacing configuration
# ---------------------------------------------------------------------------


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation: *a* when t=0, *b* when t=1."""
    return a + (b - a) * t


@dataclass(frozen=True)
class SpacingConfig:
    """All tuneable spacing / sizing values for the resume layout."""

    margin_tb: float       # top & bottom margin (inches)
    margin_lr: float       # left & right margin (inches)
    font_size: int         # body font size (pt)
    section_before: float  # space above section heading (pt)
    section_after: float   # space below section rule (pt)
    entry_skip: float      # vertical gap between entries (pt)
    bullet_topsep: float   # gap before first bullet (pt)
    bullet_itemsep: float  # gap between bullets (pt)
    name_size: int         # header name font size (pt)
    contact_skip: float    # gap below contact line (pt)


def get_spacing_config(tightness: float) -> SpacingConfig:
    """Map *tightness* (0.0 = spacious, 1.0 = ultra-compact) to concrete values."""
    t = max(0.0, min(1.0, tightness))
    return SpacingConfig(
        margin_tb=round(_lerp(0.65, 0.25, t), 2),
        margin_lr=round(_lerp(0.65, 0.30, t), 2),
        font_size=10 if t < 0.85 else 9,
        section_before=round(_lerp(10, 2, t), 1),
        section_after=round(_lerp(4, 1, t), 1),
        entry_skip=round(_lerp(5, 1, t), 1),
        bullet_topsep=round(_lerp(3, 0, t), 1),
        bullet_itemsep=round(_lerp(2, 0, t), 1),
        name_size=round(_lerp(24, 16, t)),
        contact_skip=round(_lerp(6, 1, t), 1),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_resume_to_latex(resume_json: dict, config: SpacingConfig) -> str:
    """Render structured resume JSON into a complete LaTeX document string."""
    parts: list[str] = [
        _render_preamble(config),
        "\\begin{document}\n\n",
    ]

    header = resume_json.get("header")
    if header:
        parts.append(_render_header(header, config))

    for section in resume_json.get("sections", []):
        stype = section.get("type", "entry_list")
        if stype == "entry_list":
            parts.append(_render_entry_list_section(section, config))
        elif stype == "skills":
            parts.append(_render_skills_section(section))
        elif stype == "text":
            parts.append(_render_text_section(section))

    parts.append("\\end{document}\n")
    return "".join(parts)


def fit_to_pages(resume_json: dict, target_pages: int) -> tuple[str, bytes]:
    """Binary-search over *tightness* to fit the resume onto *target_pages*.

    Performs up to 7 local compile iterations (no LLM calls).  Returns the
    *loosest* (most spacious) layout that fits within the page budget.

    Returns:
        ``(latex_source, pdf_bytes)``

    Raises:
        ``RuntimeError`` if compilation fails at every tightness level.
    """
    lo, hi = 0.0, 1.0
    best_latex: str | None = None
    best_pdf: bytes | None = None
    max_iters = 7

    for iteration in range(max_iters):
        mid = round((lo + hi) / 2, 4)
        config = get_spacing_config(mid)
        latex = render_resume_to_latex(resume_json, config)
        result = compile_latex(latex)

        if not result.success:
            raise RuntimeError(
                f"Template compilation failed at tightness={mid}: "
                f"{result.error_message}"
            )

        logger.info(
            "Page fit iter %d/%d: tightness=%.3f -> %d page(s) (target=%d)",
            iteration + 1,
            max_iters,
            mid,
            result.page_count,
            target_pages,
        )

        if result.page_count <= target_pages:
            # Fits!  Save and search for a more spacious solution.
            best_latex = latex
            best_pdf = result.pdf_bytes
            hi = mid
        else:
            # Too many pages – go tighter.
            lo = mid

        # Early exit: search interval is narrow enough (< 2% of range)
        if hi - lo < 0.02:
            break

    if best_latex and best_pdf:
        return best_latex, best_pdf

    # Even the tightest layout overflows – return best-effort.
    logger.warning(
        "Cannot fit resume to %d page(s); returning tightest layout",
        target_pages,
    )
    config = get_spacing_config(1.0)
    latex = render_resume_to_latex(resume_json, config)
    result = compile_latex(latex)
    if result.success and result.pdf_bytes:
        return latex, result.pdf_bytes

    raise RuntimeError("Failed to compile resume with any spacing configuration")


# ---------------------------------------------------------------------------
# Private template helpers
# ---------------------------------------------------------------------------


def _render_preamble(c: SpacingConfig) -> str:
    return (
        f"\\documentclass[{c.font_size}pt]{{article}}\n"
        f"\\usepackage[top={c.margin_tb}in, bottom={c.margin_tb}in, "
        f"left={c.margin_lr}in, right={c.margin_lr}in]{{geometry}}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage{enumitem}\n"
        "\\usepackage{titlesec}\n"
        "\\usepackage[hidelinks]{hyperref}\n"
        "\n"
        "\\pagestyle{empty}\n"
        "\n"
        "% Section headings: bold title + horizontal rule\n"
        "\\titleformat{\\section}{\\large\\bfseries}{}{0pt}{}[\\titlerule]\n"
        f"\\titlespacing*{{\\section}}{{0pt}}{{{c.section_before}pt}}"
        f"{{{c.section_after}pt}}\n"
        "\n"
        "% Tight bullet lists\n"
        f"\\setlist[itemize]{{leftmargin=*, itemsep={c.bullet_itemsep}pt, "
        f"topsep={c.bullet_topsep}pt, parsep=0pt, partopsep=0pt}}\n"
        "\n"
        "\\setlength{\\parindent}{0pt}\n"
        "\\setlength{\\parskip}{0pt}\n"
        "\n"
    )


def _render_header(header: dict, c: SpacingConfig) -> str:
    name = _escape_latex(header.get("name", ""))
    items = header.get("contact_items", [])

    contact_parts: list[str] = []
    for item in items:
        text = _escape_latex(item.get("text", ""))
        url = item.get("url", "")
        if url:
            # Ensure protocol prefix
            if not url.startswith(("http://", "https://", "mailto:")):
                if "@" in item.get("text", ""):
                    url = f"mailto:{url}"
                else:
                    url = f"https://{url}"
            contact_parts.append(f"\\href{{{_escape_url(url)}}}{{{text}}}")
        else:
            contact_parts.append(text)

    contact_line = " $|$ ".join(contact_parts) if contact_parts else ""
    name_leading = c.name_size + 4

    lines = [
        "{\\centering",
        (
            f"{{\\fontsize{{{c.name_size}}}{{{name_leading}}}"
            f"\\selectfont \\textbf{{{name}}}}}\\\\[2pt]"
        ),
    ]
    if contact_line:
        lines.append(f"{contact_line}\\\\[{c.contact_skip}pt]")
    lines.append("}\n")
    return "\n".join(lines) + "\n"


def _render_entry_list_section(section: dict, c: SpacingConfig) -> str:
    title = _escape_latex(section.get("title", ""))
    lines = [f"\\section{{{title}}}"]

    for i, entry in enumerate(section.get("entries", [])):
        if i > 0:
            lines.append(f"\\vspace{{{c.entry_skip}pt}}")

        primary = _escape_latex(entry.get("primary", ""))
        secondary = _escape_latex(entry.get("secondary", ""))
        location = _escape_latex(entry.get("location", ""))
        dates = _escape_latex(entry.get("dates", ""))

        # Line 1: bold primary, location  \hfill  dates
        first_line = f"\\textbf{{{primary}}}"
        if location:
            first_line += f", {location}"
        if dates:
            first_line += f" \\hfill {dates}"

        if secondary:
            first_line += " \\\\"
            lines.append(first_line)
            lines.append(f"\\textit{{{secondary}}}")
        else:
            lines.append(first_line)

        bullets = entry.get("bullets", [])
        if bullets:
            lines.append("\\begin{itemize}")
            for b in bullets:
                lines.append(f"  \\item {_escape_latex(b)}")
            lines.append("\\end{itemize}")

    return "\n".join(lines) + "\n\n"


def _render_skills_section(section: dict) -> str:
    title = _escape_latex(section.get("title", ""))
    lines = [f"\\section{{{title}}}"]

    items = section.get("items", [])
    for i, item in enumerate(items):
        label = _escape_latex(item.get("label", ""))
        value = _escape_latex(item.get("value", ""))
        suffix = " \\\\" if i < len(items) - 1 else ""
        lines.append(f"\\textbf{{{label}}}: {value}{suffix}")

    return "\n".join(lines) + "\n\n"


def _render_text_section(section: dict) -> str:
    title = _escape_latex(section.get("title", ""))
    content = _escape_latex(section.get("content", ""))
    return f"\\section{{{title}}}\n{content}\n\n"
