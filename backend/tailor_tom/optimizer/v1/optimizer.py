"""DSPy-based resume optimization for ATS.

This module implements a unified length-preserving optimization pipeline:
- Compiles first to get bullet metrics (line count, word count)
- Uses search-and-replace approach with strict length validation
- Failed replacements retry with ICL feedback up to max_iterations
"""

import gc
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any

import dspy
import fitz  # PyMuPDF
from pydantic import BaseModel, Field

from tailor_tom.config import settings
from tailor_tom.llm_runtime import configure_dspy as _configure_dspy
from tailor_tom.latex_compiler import compile_latex, CompileResult, validate_latex
from tailor_tom.layout_analyzer import check_quality, QualityResult, extract_line_metrics, extract_items_from_latex
from api.storage import update_job_status

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models for Unified Optimizer
# =============================================================================


@dataclass
class BulletConstraint:
    """Constraint information for a single bullet point."""
    bullet_id: int  # Sequential ID for tracking
    section: str  # "Experience", "Projects", etc.
    original_text: str  # Clean text content (no LaTeX commands)
    latex_snippet: str  # Original LaTeX for this bullet (for replacement)
    line_count: int  # Current lines in PDF (MUST preserve)
    word_count: int  # Current words (target: within delta)
    char_count: int  # Current characters (target: within delta)
    
    # Tracking for iterations
    last_failure_reason: Optional[str] = None
    attempts: int = 0


class BulletReplacement(BaseModel):
    """A single bullet optimization replacement from LLM."""
    bullet_id: int = Field(description="Bullet ID from input")
    replacement_latex: str = Field(description="Optimized LaTeX with formatting preserved")
    keywords_integrated: List[str] = Field(description="Keywords from job description that were added")


class OptimizeBulletsOutput(BaseModel):
    """Output from bullet optimization LLM call."""
    replacements: List[BulletReplacement] = Field(description="List of optimized bullets")


# =============================================================================
# DSPy Signature for Unified Optimizer
# =============================================================================


class OptimizeBullets(dspy.Signature):
    """Replace words in resume bullets with ATS-friendly keywords from the job description.

    LINE COUNT RULE (CRITICAL):
    - Each bullet has a specified line count (e.g., "2 lines")
    - Your replacement MUST render to the SAME number of lines
    - If a bullet is 2 lines, your replacement must also be ~2 lines when rendered
    - Making it longer (more lines) = REJECTED
    - Making it shorter (fewer lines) = REJECTED
    
    WORD COUNT RULE (CRITICAL):
    - Each bullet shows its max word count (e.g., "max 14 words")
    - Your replacement MUST have the SAME number of words or FEWER than the original
    - Exceeding the max word count = REJECTED
    - NEVER add new phrases or clauses -- only REPLACE existing words with better keywords
    
    REPLACEMENT STRATEGY:
    - REPLACE generic words with job-relevant keywords
    - "worked on" -> "developed", "helped" -> "contributed"
    - "system" -> "microservices", "built" -> "engineered"
    - Swap words 1-for-1 to keep the same word count and preserve line count
    - Do NOT append extra keywords at the end of a bullet
    
    SEMANTIC RULES:
    - Only insert keywords that make SENSE in context
    - ML bullets get ML keywords, frontend bullets get frontend keywords, backend bullets get backend keywords
    - Do NOT replace technical terms with unrelated keywords
    - Preserve all facts, metrics, and achievements
    
    LATEX FORMATTING:
    - Preserve all \\textbf{}, \\textit{}, \\href{} formatting
    - Escape special characters: & -> \\&, % -> \\%, $ -> \\$
    
    OUTPUT:
    - Return a replacement for EVERY bullet
    - If no good substitution exists, return the ORIGINAL unchanged
    - List which keywords you integrated
    """
    
    job_description: str = dspy.InputField(desc="Job description with target keywords to integrate")
    bullets: str = dspy.InputField(desc="Bullets with IDs, line counts, word count limits, and LaTeX content")
    replacements: List[BulletReplacement] = dspy.OutputField(
        desc="Optimized bullets - each must preserve the original line count and not exceed max word count"
    )


# =============================================================================
# Bullet Extraction and Formatting Helpers
# =============================================================================


def _extract_bullet_constraints(
    pdf_bytes: bytes,
    latex: str,
) -> List[BulletConstraint]:
    """Extract bullet constraints from compiled PDF and LaTeX source.
    
    Args:
        pdf_bytes: Compiled PDF bytes
        latex: Original LaTeX source
        
    Returns:
        List of BulletConstraint objects with metrics for each bullet
    """
    # Get bullet metrics from PDF (line counts, positions)
    bullet_metrics = extract_line_metrics(pdf_bytes, latex=latex)
    bullets_data = bullet_metrics.get("bullets", [])
    
    # Get bullet LaTeX snippets
    latex_items = extract_items_from_latex(latex)
    
    constraints = []
    
    for i, bullet in enumerate(bullets_data):
        # Get text from PDF metrics
        text_preview = bullet.get("text_preview", "")
        lines_text = bullet.get("lines_text", [])
        full_text = " ".join(lines_text) if lines_text else text_preview
        
        # Clean text for word/char counting
        clean_text = full_text.strip()
        
        # Get line count from PDF
        line_count = bullet.get("line_count", 1)
        
        # Calculate word and character counts
        word_count = len(clean_text.split()) if clean_text else 0
        char_count = len(clean_text) if clean_text else 0
        
        # Try to find matching LaTeX snippet
        latex_snippet = ""
        if i < len(latex_items):
            latex_snippet = latex_items[i].get("latex", "")
        
        # Determine section (heuristic based on position or content)
        # For now, default to "Experience" - could be enhanced to detect from LaTeX
        section = _detect_section_for_bullet(latex, latex_snippet)
        
        constraints.append(BulletConstraint(
            bullet_id=i + 1,  # 1-indexed for human readability
            section=section,
            original_text=clean_text,
            latex_snippet=latex_snippet,
            line_count=line_count,
            word_count=word_count,
            char_count=char_count,
        ))
    
    return constraints


# Content phrases that indicate an Education bullet (protect from editing)
_EDUCATION_CONTENT_PHRASES = (
    "gpa",
    "grade point average",
    "relevant coursework",
    "coursework:",
    "candidate for bachelor",
    "candidate for master",
    "candidate for b.s",
    "candidate for m.s",
    "candidate for b.a",
    "candidate for m.a",
    "bachelor of ",
    "master of ",
    "b.s. in ",
    "m.s. in ",
    "b.a. in ",
    "m.a. in ",
    "ph.d",
    "phd ",
    "expected graduation",
    "graduated ",
    "graduation:",
    "dean's list",
    "dean list",
    "honor roll",
    "cum laude",
    "magna cum laude",
    "summa cum laude",
    "major in ",
    "minor in ",
    "concentration in ",
)


def _detect_section_for_bullet(latex: str, latex_snippet: str) -> str:
    """Detect which section a bullet belongs to.
    
    Uses (1) bullet content heuristics for Education, then (2) preceding
    LaTeX section markers.
    
    Args:
        latex: Full LaTeX source
        latex_snippet: The specific bullet's LaTeX
        
    Returns:
        Section name (e.g., "Experience", "Projects", "Education", "Skills")
    """
    if not latex_snippet:
        return "Unknown"
    
    # 1. Content-based: if bullet text clearly indicates Education, protect it
    plain = _strip_latex_commands(latex_snippet).lower()
    for phrase in _EDUCATION_CONTENT_PHRASES:
        if phrase in plain:
            return "Education"
    
    # 2. Position-based: find nearest section header before this bullet
    pos = latex.find(latex_snippet)
    if pos == -1:
        return "Unknown"
    
    preceding = latex[:pos].lower()
    
    # Section header markers (reverse order of priority; last match wins)
    section_markers = [
        # Skills section - DO NOT EDIT
        ("skills", "Skills"),
        ("technical skills", "Skills"),
        ("core competencies", "Skills"),
        ("competencies", "Skills"),
        # Education section - DO NOT EDIT
        ("education", "Education"),
        ("academic", "Education"),
        ("academics", "Education"),
        ("degree", "Education"),
        ("coursework", "Education"),
        ("certification", "Education"),
        ("certifications", "Education"),
        ("qualifications", "Education"),
        # Research section - OK to edit
        ("research", "Research"),
        ("publications", "Research"),
        ("papers", "Research"),
        # Projects section - OK to edit
        ("project", "Projects"),
        ("portfolio", "Projects"),
        ("hackathon", "Projects"),
        # Experience section - OK to edit
        ("experience", "Experience"),
        ("employment", "Experience"),
        ("work history", "Experience"),
        ("work", "Experience"),
        ("professional", "Experience"),
        ("university", "Experience"),
        ("college", "Experience"),
        ("school", "Experience"),
        ("training", "Experience"),
    ]
    
    best_section = "Experience"
    best_pos = -1
    
    for marker, section_name in section_markers:
        pattern_pos = preceding.rfind(marker)
        if pattern_pos > best_pos:
            best_pos = pattern_pos
            best_section = section_name
    
    return best_section


def _format_bullets_for_llm(
    bullets: List[BulletConstraint],
    failed_feedback: Optional[Dict[int, str]] = None,
) -> str:
    """Format bullets for LLM consumption with LaTeX content and line count constraints.
    
    Args:
        bullets: List of bullet constraints to optimize
        failed_feedback: Optional dict of bullet_id -> failure reason for ICL
        
    Returns:
        Formatted string for LLM input with LaTeX content
    """
    lines = []
    
    # ICL feedback for retries - line count and word count failures
    if failed_feedback:
        lines.append("**REJECTED - Fix these issues:**")
        for bullet_id, reason in failed_feedback.items():
            lines.append(f"- B{bullet_id}: {reason}")
        lines.append("")
    
    for bullet in bullets:
        # Format: Show line count AND word count as constraints
        lines.append(f"**B{bullet.bullet_id}** [{bullet.section}] MUST stay {bullet.line_count} line{'s' if bullet.line_count != 1 else ''}, max {bullet.word_count} words")
        lines.append(f"LaTeX: {bullet.latex_snippet}")
        
        if bullet.last_failure_reason:
            lines.append(f"*REJECTED: {bullet.last_failure_reason}*")
        
        lines.append("")
    
    return "\n".join(lines)


# =============================================================================
# Replacement Validation and Application
# =============================================================================


def _strip_latex_commands(latex_text: str) -> str:
    """Strip LaTeX formatting commands to get plain text for word/char counting.
    
    Removes:
    - \\textbf{...}, \\textit{...}, \\emph{...} -> keeps content
    - \\href{url}{text} -> keeps text only
    - \\% -> %
    - \\& -> &
    - \\$ -> $
    - Other backslash commands
    
    Args:
        latex_text: LaTeX text with formatting commands
        
    Returns:
        Plain text with commands stripped
    """
    text = latex_text
    
    # Replace escaped special characters
    text = text.replace(r'\%', '%')
    text = text.replace(r'\&', '&')
    text = text.replace(r'\$', '$')
    text = text.replace(r'\_', '_')
    text = text.replace(r'\#', '#')
    
    # Remove \href{url}{text} -> keep just text
    # Pattern: \href{...}{text} - we want to keep "text"
    text = re.sub(r'\\href\{[^}]*\}\{([^}]*)\}', r'\1', text)
    
    # Remove formatting commands but keep content: \textbf{content} -> content
    # Handle nested braces by doing multiple passes
    for _ in range(3):  # Handle up to 3 levels of nesting
        text = re.sub(r'\\(?:textbf|textit|emph|underline|textsc|textsf|texttt)\{([^{}]*)\}', r'\1', text)
    
    # Remove any remaining simple commands like \item, \par, etc.
    text = re.sub(r'\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})?', '', text)
    
    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def _validate_replacement(
    original: BulletConstraint,
    replacement_latex: str,
    max_shrink_words: int = 3,
    max_shrink_percent: float = 0.15,
) -> Tuple[bool, str]:
    """Validate that a LaTeX replacement meets strict length constraints.
    
    Strips LaTeX commands before counting words/characters to compare
    against the original plain text metrics.
    
    STRICT MODE: 
    - Replacements must be same length or SHORTER (never longer!)
    - Being shorter is OK (up to max_shrink_words or max_shrink_percent)
    
    Args:
        original: Original bullet constraint (with plain text metrics)
        replacement_latex: Proposed replacement LaTeX from LLM
        max_shrink_words: Max words allowed to be removed (default: 3)
        max_shrink_percent: Max percentage shorter allowed (default: 15%)
        
    Returns:
        Tuple of (is_valid, reason_if_invalid)
    """
    # Strip LaTeX commands to get plain text for counting
    clean_replacement = _strip_latex_commands(replacement_latex)
    
    repl_words = len(clean_replacement.split()) if clean_replacement else 0
    repl_chars = len(clean_replacement) if clean_replacement else 0
    
    # STRICT NO GROWTH CHECK - reject ANY increase in word count
    if repl_words > original.word_count:
        growth = repl_words - original.word_count
        return False, f"TOO LONG: +{growth} words (orig {original.word_count}, got {repl_words}). Use SHORTER words."
    
    # STRICT NO GROWTH CHECK - reject ANY increase in character count
    # Even +2-3 chars can cause line wrapping on tight bullets
    if repl_chars > original.char_count:
        growth = repl_chars - original.char_count
        return False, f"TOO LONG: +{growth} chars (orig {original.char_count}, got {repl_chars}). Use SHORTER words."
    
    # Check if too SHORT (meaning too much content was removed)
    word_shrink = original.word_count - repl_words
    if word_shrink > max_shrink_words:
        return False, f"Too much removed: -{word_shrink} words (orig {original.word_count}, got {repl_words})"
    
    # Check character shrinkage percentage
    if original.char_count > 0:
        char_shrink_percent = (original.char_count - repl_chars) / original.char_count
        if char_shrink_percent > max_shrink_percent:
            return False, f"Too much removed: -{char_shrink_percent:.0%} chars (orig {original.char_count}, got {repl_chars})"
    
    # Check for empty or trivial replacement
    if repl_words < 2:
        return False, f"Replacement too short: only {repl_words} words"
    
    return True, ""


def _apply_replacement_to_latex(
    latex: str,
    original: BulletConstraint,
    replacement_latex: str,
) -> Tuple[str, bool, bool]:
    """Apply a single LaTeX replacement to LaTeX source.
    
    Since the LLM now returns LaTeX directly (with formatting preserved),
    this is a simple find-and-replace operation.
    
    Args:
        latex: Current LaTeX source
        original: Original bullet constraint (contains latex_snippet)
        replacement_latex: New LaTeX content from LLM (with formatting)
        
    Returns:
        Tuple of (modified_latex, success, was_unchanged)
        - success: True if operation completed (even if no change was made)
        - was_unchanged: True if LLM returned original (no substitution found)
    """
    if not original.latex_snippet:
        logger.warning(f"Bullet {original.bullet_id}: No LaTeX snippet to replace")
        return latex, False, False
    
    # Check if LLM returned the original unchanged (no substitution possible)
    # Normalize whitespace for comparison
    original_normalized = ' '.join(original.latex_snippet.split())
    replacement_normalized = ' '.join(replacement_latex.split())
    
    if original_normalized == replacement_normalized:
        # LLM couldn't find a valid substitution - accept as "no change needed"
        logger.info(f"Bullet {original.bullet_id}: No substitution found (returned original)")
        return latex, True, True  # Success, but unchanged
    
    # Find the original LaTeX snippet in the document
    if original.latex_snippet not in latex:
        # Try with normalized whitespace
        logger.warning(f"Bullet {original.bullet_id}: LaTeX snippet not found in document (exact match)")
        return latex, False, False
    
    # Direct replacement: old LaTeX snippet -> new LaTeX from LLM
    new_latex = latex.replace(original.latex_snippet, replacement_latex, 1)
    
    if new_latex == latex:
        logger.warning(f"Bullet {original.bullet_id}: Replacement had no effect (replace returned same)")
        return latex, False, False
    
    return new_latex, True, False


def _verify_line_counts(
    original_constraints: List[BulletConstraint],
    new_pdf_bytes: bytes,
    new_latex: str,
) -> Dict[int, Tuple[int, int]]:
    """Verify that line counts are preserved after replacements.
    
    Args:
        original_constraints: Original bullet constraints with line counts
        new_pdf_bytes: PDF bytes after replacements
        new_latex: LaTeX after replacements
        
    Returns:
        Dict of bullet_id -> (original_lines, new_lines) for bullets that changed
    """
    # Get new bullet metrics
    new_metrics = extract_line_metrics(new_pdf_bytes, latex=new_latex)
    new_bullets = new_metrics.get("bullets", [])
    
    failures = {}
    
    for orig in original_constraints:
        # Find corresponding bullet in new metrics (by index)
        new_idx = orig.bullet_id - 1  # Convert to 0-indexed
        
        if new_idx < len(new_bullets):
            new_line_count = new_bullets[new_idx].get("line_count", 0)
            
            if new_line_count != orig.line_count:
                logger.info(
                    f"Bullet {orig.bullet_id}: Line count changed from {orig.line_count} to {new_line_count}"
                )
                failures[orig.bullet_id] = (orig.line_count, new_line_count)
    
    return failures


# =============================================================================
# Legacy Helper Functions (kept for compatibility)
# =============================================================================


def _fix_latex_issues(latex: str) -> str:
    """Fix common LaTeX issues introduced by LLMs.
    
    Args:
        latex: LaTeX content that may have issues.
        
    Returns:
        Fixed LaTeX content.
    """
    fixed = latex
    
    # Fix LLM replacing | with $—$ (em-dash in math mode)
    # This commonly happens in job titles like "Company | Role"
    fixed = fixed.replace('$—$', '$|$')
    fixed = fixed.replace('$–$', '$|$')  # en-dash variant
    fixed = fixed.replace('—', '$|$')    # raw em-dash
    fixed = fixed.replace('–', '-')       # en-dash to hyphen
    
    # Fix unescaped & characters (but not in already escaped \&)
    # IMPORTANT: Do NOT escape & in protected contexts:
    # 1. Tabular/array environments (column separator)
    # 2. Math mode (alignment character)
    # 3. Verbatim environments (literal content)
    # 4. Comments (not processed)
    
    def find_environment_content_start(pos, env_end_pos):
        """Find where environment content actually starts (after \begin{...} and all arguments)."""
        pos = env_end_pos
        # Skip whitespace
        while pos < len(fixed) and fixed[pos].isspace():
            pos += 1
        # Parse optional arguments [t], [b], etc.
        if pos < len(fixed) and fixed[pos] == '[':
            depth = 1
            pos += 1
            while pos < len(fixed) and depth > 0:
                if fixed[pos] == '[':
                    depth += 1
                elif fixed[pos] == ']':
                    depth -= 1
                pos += 1
            while pos < len(fixed) and fixed[pos].isspace():
                pos += 1
        # Parse required arguments
        while pos < len(fixed) and fixed[pos] == '{':
            depth = 1
            pos += 1
            while pos < len(fixed) and depth > 0:
                if fixed[pos] == '{':
                    depth += 1
                elif fixed[pos] == '}':
                    depth -= 1
                pos += 1
            while pos < len(fixed) and fixed[pos].isspace():
                pos += 1
        return pos
    
    # Track all protected ranges where & should NOT be escaped
    protected_ranges = []
    
    # 1. Tabular/array environments (column separator)
    tabular_patterns = [
        r'\\begin\{tabular\*?\}',
        r'\\begin\{array\}',
        r'\\begin\{tabularx\}',
        r'\\begin\{longtabu\}',
        r'\\begin\{longtable\}',
        r'\\begin\{xtabular\}',
        r'\\begin\{supertabular\}',
        r'\\begin\{tabu\}',
    ]
    end_tabular_patterns = [
        r'\\end\{tabular\*?\}',
        r'\\end\{array\}',
        r'\\end\{tabularx\}',
        r'\\end\{longtabu\}',
        r'\\end\{longtable\}',
        r'\\end\{xtabular\}',
        r'\\end\{supertabular\}',
        r'\\end\{tabu\}',
    ]
    
    tabular_envs = []
    for pattern in tabular_patterns:
        for match in re.finditer(pattern, fixed):
            content_start = find_environment_content_start(match.start(), match.end())
            tabular_envs.append({
                'type': 'begin',
                'pos': match.start(),
                'content_start': content_start,
            })
    for pattern in end_tabular_patterns:
        for match in re.finditer(pattern, fixed):
            tabular_envs.append({
                'type': 'end',
                'pos': match.start(),
            })
    
    tabular_envs.sort(key=lambda x: x['pos'])
    stack = []
    for env in tabular_envs:
        if env['type'] == 'begin':
            stack.append(env['content_start'])
        else:
            if stack:
                protected_ranges.append((stack.pop(), env['pos']))
    
    # Clear intermediate lists after use
    tabular_envs = None
    stack = None
    
    # 2. Math alignment environments (also use & as column separator)
    math_align_patterns = [
        r'\\begin\{align\*?\}',
        r'\\begin\{alignat\*?\}',
        r'\\begin\{aligned\}',
        r'\\begin\{eqnarray\*?\}',
        r'\\begin\{split\}',
        r'\\begin\{gather\*?\}',
        r'\\begin\{multline\*?\}',
    ]
    end_math_align_patterns = [
        r'\\end\{align\*?\}',
        r'\\end\{alignat\*?\}',
        r'\\end\{aligned\}',
        r'\\end\{eqnarray\*?\}',
        r'\\end\{split\}',
        r'\\end\{gather\*?\}',
        r'\\end\{multline\*?\}',
    ]
    
    math_align_envs = []
    for pattern in math_align_patterns:
        for match in re.finditer(pattern, fixed):
            content_start = find_environment_content_start(match.start(), match.end())
            math_align_envs.append({
                'type': 'begin',
                'pos': match.start(),
                'content_start': content_start,
            })
    for pattern in end_math_align_patterns:
        for match in re.finditer(pattern, fixed):
            math_align_envs.append({
                'type': 'end',
                'pos': match.start(),
            })
    
    math_align_envs.sort(key=lambda x: x['pos'])
    stack = []
    for env in math_align_envs:
        if env['type'] == 'begin':
            stack.append(env['content_start'])
        else:
            if stack:
                protected_ranges.append((stack.pop(), env['pos']))
    
    # Clear intermediate lists after use
    math_align_envs = None
    stack = None
    
    # 3. Inline and display math: $...$, \(...\), \[...\], $$...$$
    # Track positions already covered by $$ to avoid double-matching
    dollar_dollar_positions = set()
    
    # Handle $$...$$ (display math) first to avoid matching individual $ characters
    for match in re.finditer(r'(?<!\\)\$\$', fixed):
        dollar_start = match.start()
        start_pos = match.end()
        # Find matching $$
        end_match = re.search(r'(?<!\\)\$\$', fixed[start_pos:])
        if end_match:
            end_pos = start_pos + end_match.start()
            dollar_end = start_pos + end_match.end()
            protected_ranges.append((start_pos, end_pos))
            # Mark all positions in this $$...$$ block (including delimiters)
            for pos in range(dollar_start, dollar_end):
                dollar_dollar_positions.add(pos)
    
    # Handle $...$ (inline math) - but skip if already part of $$
    for match in re.finditer(r'(?<!\\)\$', fixed):
        if match.start() in dollar_dollar_positions:
            continue  # Skip if already part of $$...$$
        start_pos = match.end()
        # Find matching $
        end_match = re.search(r'(?<!\\)\$', fixed[start_pos:])
        if end_match:
            end_pos = start_pos + end_match.start()
            protected_ranges.append((start_pos, end_pos))
    
    # \(...\) (inline math)
    for match in re.finditer(r'\\\(', fixed):
        start_pos = match.end()
        end_match = re.search(r'\\\)', fixed[start_pos:])
        if end_match:
            end_pos = start_pos + end_match.start()
            protected_ranges.append((start_pos, end_pos))
    
    # \[...\] (display math)
    for match in re.finditer(r'\\\[', fixed):
        start_pos = match.end()
        end_match = re.search(r'\\\]', fixed[start_pos:])
        if end_match:
            end_pos = start_pos + end_match.start()
            protected_ranges.append((start_pos, end_pos))
    
    # 4. Verbatim environments (literal content, no escaping)
    verbatim_patterns = [
        r'\\begin\{verbatim\}',
        r'\\begin\{lstlisting\}',
        r'\\begin\{alltt\}',
    ]
    end_verbatim_patterns = [
        r'\\end\{verbatim\}',
        r'\\end\{lstlisting\}',
        r'\\end\{alltt\}',
    ]
    
    verbatim_envs = []
    for pattern in verbatim_patterns:
        for match in re.finditer(pattern, fixed):
            content_start = find_environment_content_start(match.start(), match.end())
            verbatim_envs.append({
                'type': 'begin',
                'pos': match.start(),
                'content_start': content_start,
            })
    for pattern in end_verbatim_patterns:
        for match in re.finditer(pattern, fixed):
            verbatim_envs.append({
                'type': 'end',
                'pos': match.start(),
            })
    
    verbatim_envs.sort(key=lambda x: x['pos'])
    stack = []
    for env in verbatim_envs:
        if env['type'] == 'begin':
            stack.append(env['content_start'])
        else:
            if stack:
                protected_ranges.append((stack.pop(), env['pos']))
    
    # Clear intermediate lists after use
    verbatim_envs = None
    stack = None
    dollar_dollar_positions = None
    
    # 5. \verb|...| commands (inline verbatim)
    for match in re.finditer(r'\\verb([^\\\s])', fixed):
        delimiter = match.group(1)
        start_pos = match.end()
        # Find matching delimiter (not escaped)
        end_pos = start_pos
        while end_pos < len(fixed):
            if fixed[end_pos] == delimiter and (end_pos == start_pos or fixed[end_pos-1] != '\\'):
                protected_ranges.append((start_pos, end_pos))
                break
            end_pos += 1
    
    def is_in_protected_range(pos):
        """Check if position is in any protected range."""
        for start, end in protected_ranges:
            if start <= pos < end:
                return True
        return False
    
    def is_in_comment(pos):
        """Check if position is in a LaTeX comment."""
        # Find start of line
        line_start = fixed.rfind('\n', 0, pos) + 1
        # Check if line has % before this position (after whitespace)
        line_prefix = fixed[line_start:pos].lstrip()
        return line_prefix.startswith('%')
    
    # Escape & characters, but skip those in protected contexts
    result = []
    i = 0
    while i < len(fixed):
        if fixed[i] == '&' and (i == 0 or fixed[i-1] != '\\'):
            # Check if this & is in a protected context
            if is_in_protected_range(i) or is_in_comment(i):
                # Keep it unescaped
                result.append('&')
            else:
                # Escape it
                result.append('\\&')
        else:
            result.append(fixed[i])
        i += 1
    
    fixed = ''.join(result)
    
    # Clear intermediate data structures after use
    result = None
    
    # Fix incomplete commands (missing closing braces)
    # Check for \textbf{ that doesn't have a closing brace
    # This is a common error - LLMs sometimes forget to close formatting commands
    textbf_pattern = r'\\textbf\{'
    matches = list(re.finditer(textbf_pattern, fixed))
    
    for match in reversed(matches):  # Process from end to start
        start_pos = match.end()  # Position after \textbf{
        # Track brace depth to find matching closing brace
        brace_depth = 1
        pos = start_pos
        found_close = False
        
        while pos < len(fixed):
            if fixed[pos] == '{':
                brace_depth += 1
            elif fixed[pos] == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    found_close = True
                    break
            pos += 1
        
        # If no closing brace found, add one before \end{document} or at the end
        if not found_close:
            # Find insertion point (before \end{document} or at end of file)
            insert_pos = fixed.find('\\end{document}', start_pos)
            if insert_pos == -1:
                insert_pos = len(fixed)
            # Insert closing brace
            fixed = fixed[:insert_pos] + '}' + fixed[insert_pos:]
    
    # Fix incomplete/extra environments - handle "Paragraph ended before \end was complete" errors
    # This happens when a \begin{...} environment is opened but not closed with \end{...}
    # OR when there are extra \end tags
    # Use a stack-based approach to properly handle nested environments
    
    begin_pattern = r'\\begin\{([^}]+)\}'
    end_pattern = r'\\end\{([^}]+)\}'
    
    # Find all begin and end tags with their positions
    all_tags = []
    for match in re.finditer(begin_pattern, fixed):
        all_tags.append({
            'type': 'begin',
            'name': match.group(1),
            'pos': match.start(),
            'full_match': match.group(0),
        })
    for match in re.finditer(end_pattern, fixed):
        all_tags.append({
            'type': 'end',
            'name': match.group(1),
            'pos': match.start(),
            'full_match': match.group(0),
        })
    
    # Sort by position
    all_tags.sort(key=lambda x: x['pos'])
    
    # Track open environments using a stack and identify extra end tags
    open_stack = []
    extra_end_positions = []  # Track positions of extra end tags to remove
    
    for tag in all_tags:
        if tag['type'] == 'begin':
            # Skip document environment - it should always be present
            if tag['name'] != 'document':
                open_stack.append(tag['name'])
        else:  # end
            # Skip document environment
            if tag['name'] == 'document':
                continue
            # Find matching begin in stack
            if open_stack and open_stack[-1] == tag['name']:
                open_stack.pop()
            else:
                # No matching begin - this is an extra end tag
                # Store position and length for removal
                extra_end_positions.append((tag['pos'], len(tag['full_match'])))
    
    # Remove extra end tags (process in reverse order to preserve positions)
    for pos, length in reversed(extra_end_positions):
        fixed = fixed[:pos] + fixed[pos + length:]
    
    # Clear intermediate lists after use
    all_tags = None
    extra_end_positions = None
    
    # Any remaining items in open_stack are unclosed environments
    # Add their closing tags before \end{document}
    if open_stack:
        end_doc_pos = fixed.find('\\end{document}')
        if end_doc_pos == -1:
            end_doc_pos = len(fixed)
        
        # Insert closing tags in reverse order (LIFO - last opened, first closed)
        closing_tags = '\n'.join([f'\\end{{{env}}}' for env in reversed(open_stack)])
        fixed = fixed[:end_doc_pos] + '\n' + closing_tags + '\n' + fixed[end_doc_pos:]
    
    # Clear intermediate data after use
    open_stack = None
    protected_ranges = None
    
    # Fix unmatched braces - count braces and try to balance (after all other fixes)
    # This ensures any braces added by previous fixes are accounted for
    open_braces = fixed.count('{')
    close_braces = fixed.count('}')
    if open_braces > close_braces:
        # Add missing closing braces before \end{document}
        missing = open_braces - close_braces

        if '\\end{document}' in fixed:
            fixed = fixed.replace('\\end{document}', '}' * missing + '\n\\end{document}')
        else:
            # If no \end{document}, add at the end
            fixed = fixed + '}' * missing
    
    # Remove trailing backslashes before newlines (except line breaks \\)
    fixed = re.sub(r'\\(?<!\\\\)\s*\n', r'\n', fixed)
    
    # Fix dimension commands missing units (e.g., \vspace{-8} -> \vspace{-8pt})
    # This is common when users copy LaTeX from Overleaf which is more lenient
    # Common dimension commands: vspace, hspace, setlength, addtolength, etc.
    dimension_pattern = r'\\(vspace|hspace|vspace\*|hspace\*)\s*\{(-?\d+(?:\.\d+)?)\}'
    
    def add_dimension_unit(match):
        cmd = match.group(1)
        value = match.group(2)
        # Check if value already has a unit
        if not re.search(r'(pt|em|ex|in|cm|mm|pc|bp|dd|cc|sp)$', value):
            # Add default unit 'pt' (printer's points, LaTeX default)
            return f'\\{cmd}{{{value}pt}}'
        return match.group(0)
    
    fixed = re.sub(dimension_pattern, add_dimension_unit, fixed)
    
    # Fix \setlength and similar two-argument commands
    setlength_pattern = r'\\(setlength|addtolength|settowidth|settoheight|settodepth)\s*\{([^}]+)\}\s*\{(-?\d+(?:\.\d+)?)\}'
    
    def fix_setlength(match):
        cmd = match.group(1)
        length_name = match.group(2)
        value = match.group(3)
        # Check if value already has a unit
        if not re.search(r'(pt|em|ex|in|cm|mm|pc|bp|dd|cc|sp)$', value):
            return f'\\{cmd}{{{length_name}}}{{{value}pt}}'
        return match.group(0)
    
    fixed = re.sub(setlength_pattern, fix_setlength, fixed)
    
    return fixed


def _extract_item_content(latex: str) -> List[str]:
    """Extract content from all \\item commands in LaTeX.
    
    Args:
        latex: LaTeX source code.
        
    Returns:
        List of item contents (text within \\item{} commands), preserving order.
    """
    items = []
    
    # Pattern to match \item with optional whitespace and opening brace
    # Matches: \item {content} or \item content or \item\n{content}
    pattern = r'\\item\s*(?:\{([^}]*)\}|([^\n\\]+))'
    
    for match in re.finditer(pattern, latex):
        # Check which group matched
        if match.group(1) is not None:
            items.append(match.group(1))  # Content from { }
        elif match.group(2) is not None:
            items.append(match.group(2).strip())  # Content without braces
    
    return items


def _extract_section_content(latex: str, section_name: str) -> str:
    """Extract content of a specific section from LaTeX.
    
    Args:
        latex: LaTeX source code.
        section_name: Name of section to extract (e.g., "Education", "Skills").
        
    Returns:
        Section content as string.
    """
    # Find section start
    section_pattern = r'\\begin\{resume_section\}\{' + re.escape(section_name) + r'\}'
    match = re.search(section_pattern, latex)
    
    if not match:
        return ""
    
    start_pos = match.end()
    
    # Find matching \end{resume_section}
    # Need to track nested resume_section environments
    depth = 1
    pos = start_pos
    
    while pos < len(latex) and depth > 0:
        # Look for \begin{resume_section} or \end{resume_section}
        begin_match = re.search(r'\\begin{resume_section}', latex[pos:])
        end_match = re.search(r'\\end{resume_section}', latex[pos:])
        
        begin_pos = begin_match.start() if begin_match else len(latex)
        end_pos = end_match.start() if end_match else len(latex)
        
        if begin_pos < end_pos:
            depth += 1
            pos += begin_pos + len(begin_match.group(0))
        else:
            depth -= 1
            if depth == 0:
                return latex[start_pos:pos + end_pos]
            pos += end_pos + len(end_match.group(0))
    
    # If we get here, section wasn't closed properly
    return latex[start_pos:]


def _validate_section_preservation(optimized_latex: str, original_latex: str, section_name: str) -> bool:
    """Validate that a specific section is unchanged.
    
    Args:
        optimized_latex: Optimized LaTeX source.
        original_latex: Original LaTeX source.
        section_name: Name of section to check (e.g., "Education", "Skills").
        
    Returns:
        True if section is unchanged, False otherwise.
    """
    original_section = _extract_section_content(original_latex, section_name)
    optimized_section = _extract_section_content(optimized_latex, section_name)
    
    if not original_section and not optimized_section:
        return True  # Section doesn't exist in either (OK)
    
    if original_section != optimized_section:
        return False
    
    return True


def _extract_name_from_latex(latex: str) -> Tuple[str, str]:
    """Extract first and last name from LaTeX resume.
    
    Looks for \\name{FirstName LastName} command.
    
    Args:
        latex: LaTeX source code.
        
    Returns:
        Tuple of (first_name, last_name). Returns ("Unknown", "Unknown") if not found.
    """
    name_pattern = r'\\name\{([^}]+)\}'
    match = re.search(name_pattern, latex)
    
    if not match:
        return ("Unknown", "Unknown")
    
    name = match.group(1).strip()
    name_parts = name.split()
    
    if len(name_parts) >= 2:
        first_name = name_parts[0]
        last_name = name_parts[-1]  # Take last part as last name
        return (first_name, last_name)
    elif len(name_parts) == 1:
        return (name_parts[0], "Unknown")
    else:
        return ("Unknown", "Unknown")




def _generate_output_filename(resume_latex: str, company_name: str) -> str:
    """Generate output filename in format FirstName_LastName_CompanyName.pdf (Title_Case)
    
    Args:
        resume_latex: Resume LaTeX source.
        company_name: Company name (from LLM output).
        
    Returns:
        Filename string.
    """
    first_name, last_name = _extract_name_from_latex(resume_latex)
    
    # Clean company name for filename
    company = company_name.strip()
    company = company.strip('"\'')
    company = re.sub(r'[^\w\s]', '', company)
    company = re.sub(r'\s+', '_', company)
    
    # Title case: capitalize first letter of each word, rest lowercase
    parts = company.split('_')
    company = '_'.join([part.capitalize() if part else '' for part in parts])
    
    # Clean names for filename (remove special chars, title case)
    first_name = re.sub(r'[^\w]', '', first_name)
    last_name = re.sub(r'[^\w]', '', last_name)
    
    # Title case: capitalize first letter, rest lowercase
    first_name = first_name.capitalize() if first_name else "Unknown"
    last_name = last_name.capitalize() if last_name else "Unknown"
    
    # Fallback if company name is empty
    if not company or len(company) < 2:
        company = "Company"
    
    filename = f"{first_name}_{last_name}_{company}.pdf"
    return filename


# =============================================================================
# Result Data Classes
# =============================================================================


@dataclass
class OptimizationResult:
    """Result of the resume optimization pipeline."""

    success: bool
    original_latex: str
    optimized_latex: Optional[str] = None
    pdf_bytes: Optional[bytes] = None
    page_count: int = 0
    iterations: int = 0
    error_message: Optional[str] = None
    filename: Optional[str] = None

    @property
    def is_single_page(self) -> bool:
        """Check if the result fits on a single page."""
        return self.page_count == 1


# =============================================================================
# Optimization Pipeline
# =============================================================================


class ResumeOptimizerPipeline(dspy.Module):
    """Unified length-preserving resume optimizer.

    Uses a search-and-replace approach with strict constraints:
    - Compile first to get bullet metrics (line count, word count)
    - LLM generates replacements within word/char limits
    - Failed replacements retry with ICL feedback up to max_iterations
    """

    def __init__(
        self,
        max_iterations: Optional[int] = None,
        target_pages: Optional[int] = None,
        max_bullet_lines: Optional[int] = None,
        job_id: Optional[str] = None,
    ):
        """Initialize the optimizer pipeline.

        Args:
            max_iterations: Maximum iterations for retry loop (from user settings).
            target_pages: Target number of pages for the resume (default: 1).
            max_bullet_lines: Maximum lines per bullet point (default: 2).
            job_id: Optional job ID for status updates.
        """
        super().__init__()
        self.max_iterations = max_iterations if max_iterations is not None else 3
        self.target_pages = target_pages if target_pages is not None else 1
        self.max_bullet_lines = max_bullet_lines if max_bullet_lines is not None else 2
        self.job_id = job_id

        # Unified optimizer - modern DSPy supports typed outputs directly in signatures
        # ChainOfThought adds reasoning which improves keyword integration quality
        self.bullet_optimizer = dspy.ChainOfThought(OptimizeBullets)

    def forward(
        self,
        resume_latex: str,
        job_description: str,
    ) -> OptimizationResult:
        """Run the unified optimization pipeline.

        Args:
            resume_latex: Original resume in LaTeX format.
            job_description: Job description to optimize for.

        Returns:
            OptimizationResult with optimized LaTeX and PDF.
        """
        # Update status to "processing" when actual work starts
        if self.job_id:
            update_job_status(self.job_id, "processing")

        # Step 1: Compile original to get baseline metrics
        logger.info("Compiling original resume to extract bullet metrics...")
        original_compile = compile_latex(resume_latex)
        
        if not original_compile.success:
            logger.error(f"Original resume compilation failed: {original_compile.error_message}")
            return OptimizationResult(
                success=False,
                original_latex=resume_latex,
                optimized_latex=resume_latex,
                iterations=0,
                error_message=f"Original resume compilation failed: {original_compile.error_message}",
                filename=None,
            )

        # Step 2: Extract bullet constraints from compiled PDF
        logger.info("Extracting bullet constraints from PDF...")
        all_constraints = _extract_bullet_constraints(
            original_compile.pdf_bytes,
            resume_latex,
        )
        
        # Filter to only Experience and Projects bullets (skip Education, Skills)
        constraints_to_optimize = [
            c for c in all_constraints
            if c.section not in ("Education", "Skills", "Unknown")
            and c.word_count >= 3  # Skip very short bullets
        ]
        
        if not constraints_to_optimize:
            logger.info("No bullets to optimize, returning original")
            return OptimizationResult(
                success=True,
                original_latex=resume_latex,
                optimized_latex=resume_latex,
                pdf_bytes=original_compile.pdf_bytes,
                page_count=original_compile.page_count,
                iterations=0,
                error_message=None,
                filename=None,
            )
        
        logger.info(f"Found {len(constraints_to_optimize)} bullets to optimize")
        
        # Step 3: Iterative optimization loop
        current_latex = resume_latex
        pending_bullets = constraints_to_optimize.copy()
        accepted_bullets: List[BulletConstraint] = []
        failed_feedback: Dict[int, str] = {}  # For ICL feedback
        
        for iteration in range(self.max_iterations):
            if not pending_bullets:
                logger.info(f"All bullets accepted by iteration {iteration}")
                break
            
            logger.info(f"Iteration {iteration + 1}/{self.max_iterations}: {len(pending_bullets)} bullets pending")
            
            # Format bullets for LLM (include feedback for retries)
            bullets_str = _format_bullets_for_llm(
                pending_bullets,
                failed_feedback=failed_feedback if iteration > 0 else None,
            )
            
            # Call LLM
            try:
                result = self.bullet_optimizer(
                    job_description=job_description,
                    bullets=bullets_str,
                )
                replacements = result.replacements
                
            except Exception as e:
                error_type = type(e).__name__
                error_details = str(e)
                logger.error(
                    f"Iteration {iteration + 1}: LLM call failed: {error_type}: {error_details}",
                    exc_info=True
                )
                # Continue to next iteration
                continue
            
            # Step 3a: Apply replacements with pre-validation
            test_latex = current_latex
            applied_replacements: Dict[int, Tuple[str, str, str]] = {}  # bullet_id -> (original_snippet, replacement_latex, keywords)
            bullets_unchanged: List[BulletConstraint] = []
            
            for bullet in pending_bullets:
                # Find replacement for this bullet
                replacement = next(
                    (r for r in replacements if r.bullet_id == bullet.bullet_id),
                    None
                )
                
                if not replacement:
                    logger.warning(f"Bullet {bullet.bullet_id}: No replacement provided by LLM")
                    bullet.last_failure_reason = "No replacement provided by LLM"
                    bullet.attempts += 1
                    continue
                
                # Pre-validate word/char count BEFORE applying to LaTeX
                is_valid, rejection_reason = _validate_replacement(bullet, replacement.replacement_latex)
                if not is_valid:
                    logger.info(f"Bullet {bullet.bullet_id}: Pre-validation failed - {rejection_reason}")
                    bullet.last_failure_reason = rejection_reason
                    bullet.attempts += 1
                    failed_feedback[bullet.bullet_id] = rejection_reason
                    continue
                
                # Apply replacement to LaTeX
                new_latex, success, was_unchanged = _apply_replacement_to_latex(
                    test_latex,
                    bullet,
                    replacement.replacement_latex,
                )
                
                if not success:
                    logger.warning(f"Bullet {bullet.bullet_id}: Failed to apply replacement to LaTeX")
                    bullet.last_failure_reason = "Failed to apply replacement to LaTeX"
                    bullet.attempts += 1
                    continue
                
                # If LLM returned original unchanged, accept it immediately
                if was_unchanged:
                    bullets_unchanged.append(bullet)
                    logger.info(f"Bullet {bullet.bullet_id}: Unchanged (no substitution found)")
                    continue
                
                # Track the replacement for potential revert
                applied_replacements[bullet.bullet_id] = (
                    bullet.latex_snippet,
                    replacement.replacement_latex,
                    ", ".join(replacement.keywords_integrated) if replacement.keywords_integrated else ""
                )
                test_latex = new_latex
            
            # Step 3b: Compile and check line counts
            if applied_replacements:
                logger.info(f"Compiling to verify line counts for {len(applied_replacements)} bullets...")
                test_compile = compile_latex(test_latex)
                
                if not test_compile.success:
                    # Compilation failed - reject all replacements in this batch
                    logger.warning("Compilation failed after replacements - rejecting all")
                    for bullet_id in applied_replacements:
                        bullet = next(b for b in pending_bullets if b.bullet_id == bullet_id)
                        bullet.last_failure_reason = "Compilation failed"
                        bullet.attempts += 1
                        failed_feedback[bullet_id] = "LaTeX compilation error"
                else:
                    # Check line counts
                    bullets_to_check = [b for b in pending_bullets if b.bullet_id in applied_replacements]
                    line_failures = _verify_line_counts(bullets_to_check, test_compile.pdf_bytes, test_latex)
                    
                    # Process results
                    for bullet_id, (original_snippet, replacement_latex, keywords) in applied_replacements.items():
                        bullet = next(b for b in pending_bullets if b.bullet_id == bullet_id)
                        
                        if bullet_id in line_failures:
                            # Line count changed - REJECT and provide feedback with word count analysis
                            old_lines, new_lines = line_failures[bullet_id]
                            clean_repl = _strip_latex_commands(replacement_latex)
                            repl_words = len(clean_repl.split()) if clean_repl else 0
                            word_diff = repl_words - bullet.word_count
                            
                            if new_lines > old_lines:
                                word_info = f" (you used {repl_words} words vs original {bullet.word_count}, {'+' if word_diff > 0 else ''}{word_diff})" if word_diff != 0 else ""
                                feedback = f"TOO LONG: went from {old_lines} to {new_lines} lines{word_info}. REPLACE words instead of adding new ones. Max {bullet.word_count} words."
                            else:
                                word_info = f" (you used {repl_words} words vs original {bullet.word_count}, {word_diff})" if word_diff != 0 else ""
                                feedback = f"TOO SHORT: went from {old_lines} to {new_lines} lines{word_info}. Don't remove content."
                            
                            logger.info(f"Bullet {bullet_id}: Line count changed - {feedback}")
                            bullet.last_failure_reason = feedback
                            bullet.attempts += 1
                            failed_feedback[bullet_id] = feedback
                            # Revert this bullet's change
                            test_latex = test_latex.replace(replacement_latex, original_snippet, 1)
                        else:
                            # Line count preserved - ACCEPT
                            accepted_bullets.append(bullet)
                            logger.info(f"Bullet {bullet_id}: Accepted (keywords: {keywords})")
                    
                    # Update current_latex with accepted changes
                    current_latex = test_latex
            
            # Accept unchanged bullets
            for bullet in bullets_unchanged:
                accepted_bullets.append(bullet)
            
            # Build new pending list
            new_pending = []
            for bullet in pending_bullets:
                if bullet not in accepted_bullets:
                    new_pending.append(bullet)
            
            pending_bullets = new_pending
            failed_feedback = {k: v for k, v in failed_feedback.items() if any(b.bullet_id == k for b in pending_bullets)}
            
            # Clean up
            gc.collect()
        
        # Step 4: Compile final result
        logger.info("Compiling optimized resume...")
        current_latex = _fix_latex_issues(current_latex)
        final_compile = compile_latex(current_latex)
        
        if not final_compile.success:
            # Try one more time with fixes
            current_latex = _fix_latex_issues(current_latex)
            final_compile = compile_latex(current_latex)
            
            if not final_compile.success:
                logger.error(f"Final compilation failed: {final_compile.error_message}")
                # Return original if compilation fails
                return OptimizationResult(
                    success=False,
                    original_latex=resume_latex,
                    optimized_latex=current_latex,
                    pdf_bytes=original_compile.pdf_bytes,
                    page_count=original_compile.page_count,
                    iterations=self.max_iterations,
                    error_message=f"Final compilation failed: {final_compile.error_message}",
                    filename=None,
                )
        
        # Step 5: Verify line counts are preserved
        logger.info("Verifying line counts are preserved...")
        line_count_failures = _verify_line_counts(
            constraints_to_optimize,
            final_compile.pdf_bytes,
            current_latex,
        )
        
        if line_count_failures:
            logger.warning(f"Line count changed for {len(line_count_failures)} bullets: {line_count_failures}")
            # Note: We could revert these, but for now just log the warning
        
        # Quality check
        quality_result = check_quality(
            pdf_bytes=final_compile.pdf_bytes,
            target_pages=self.target_pages,
            max_bullet_lines=self.max_bullet_lines,
            latex=current_latex,
        )
        
        total_iterations = min(self.max_iterations, len([b for b in constraints_to_optimize if b.attempts > 0]) + 1)
        
        logger.info(
            f"Optimization complete: {len(accepted_bullets)}/{len(constraints_to_optimize)} bullets optimized, "
            f"{len(pending_bullets)} failed after {total_iterations} iterations"
        )
        
        return OptimizationResult(
            success=quality_result.passes,
            original_latex=resume_latex,
            optimized_latex=current_latex,
            pdf_bytes=final_compile.pdf_bytes,
            page_count=final_compile.page_count,
            iterations=total_iterations,
            error_message=(
                f"Quality issues remain: {quality_result.issues_summary}"
                if not quality_result.passes else None
            ),
            filename=None,
        )


def configure_dspy(
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> None:
    """Re-export from llm_runtime for backward compatibility. Prefer tailor_tom.llm_runtime.configure_dspy."""
    _configure_dspy(
        model_name=model_name,
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def optimize_resume(
    resume_latex: str,
    job_description: str,
    max_iterations: Optional[int] = None,
    target_pages: Optional[int] = None,
    max_bullet_lines: Optional[int] = None,
    job_id: Optional[str] = None,
) -> OptimizationResult:
    """Convenience function to optimize a resume.

    This is a high-level function that handles DSPy configuration
    and runs the optimization pipeline.

    Args:
        resume_latex: Original resume in LaTeX format.
        job_description: Job description to optimize for.
        max_iterations: Maximum iterations (default: 3).
        target_pages: Target page count (default: 1).
        max_bullet_lines: Maximum lines per bullet point (default: 2).
        job_id: Optional job ID for status updates (only set status to "processing" when work actually starts).

    Returns:
        OptimizationResult with optimized resume.
    """
    # Note: configure_dspy() must be called in the same thread before calling this function
    # DSPy settings are thread-local, so each thread needs its own configuration.
    # This function assumes DSPy is already configured in the current thread.

    # Create and run pipeline
    pipeline = ResumeOptimizerPipeline(
        max_iterations=max_iterations,
        target_pages=target_pages,
        max_bullet_lines=max_bullet_lines,
        job_id=job_id,  # Pass job_id to pipeline for status updates
    )

    return pipeline(resume_latex, job_description)
