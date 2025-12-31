"""DSPy-based resume optimization for ATS.

This module implements a two-phase optimization pipeline:
1. Phase 1: ATS keyword optimization (word-level changes, no content addition/removal)
2. Phase 2: Page reduction (condensing qualifying bullets, content removal allowed)
"""

import dspy
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple
import logging

import fitz  # PyMuPDF

from tailor_tom.config import settings
from tailor_tom.latex_compiler import compile_latex, CompileResult, validate_latex
from tailor_tom.layout_analyzer import analyze_layout, check_quality, QualityResult, extract_line_metrics

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
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
    # Match & that is NOT preceded by \
    fixed = re.sub(r'(?<!\\)&', r'\\&', fixed)
    
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
    
    # Any remaining items in open_stack are unclosed environments
    # Add their closing tags before \end{document}
    if open_stack:
        end_doc_pos = fixed.find('\\end{document}')
        if end_doc_pos == -1:
            end_doc_pos = len(fixed)
        
        # Insert closing tags in reverse order (LIFO - last opened, first closed)
        closing_tags = '\n'.join([f'\\end{{{env}}}' for env in reversed(open_stack)])
        fixed = fixed[:end_doc_pos] + '\n' + closing_tags + '\n' + fixed[end_doc_pos:]
    
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


def _extract_non_item_latex(latex: str) -> str:
    """Extract LaTeX structure excluding \\item content.
    
    Replaces all \\item content with placeholders to compare structure.
    
    Args:
        latex: LaTeX source code.
        
    Returns:
        LaTeX with \\item content replaced by placeholders.
    """
    # Replace \item {content} and \item content with \item {PLACEHOLDER}
    pattern = r'\\item\s*(?:\{[^}]*\}|[^\n\\]+)'
    replaced = re.sub(pattern, r'\\item{PLACEHOLDER}', latex)
    return replaced


def _validate_latex_structure(optimized_latex: str, original_latex: str) -> Tuple[bool, str]:
    """Validate that only \\item content was changed, not LaTeX structure.
    
    Args:
        optimized_latex: Optimized LaTeX source.
        original_latex: Original LaTeX source.
        
    Returns:
        Tuple of (is_valid, error_message). is_valid is True if structure preserved.
    """
    # Extract non-item LaTeX (structure only)
    original_structure = _extract_non_item_latex(original_latex)
    optimized_structure = _extract_non_item_latex(optimized_latex)
    
    if original_structure != optimized_structure:
        return False, "LaTeX structure was modified (only \\item content should change)"
    
    return True, ""


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


def _filter_qualifying_bullets(layout_analysis: dict, current_pages: int, target_pages: int) -> List[dict]:
    """Filter bullets that meet Phase 2 criteria for condensation.
    
    If over target pages, all multi-line bullets qualify (more aggressive).
    Otherwise, only multi-line bullets with <15% utilization qualify.
    
    Args:
        layout_analysis: Dictionary containing bullets data.
        current_pages: Current page count.
        target_pages: Target page count.
        
    Returns:
        List of bullet dictionaries that meet the criteria.
    """
    bullets = layout_analysis.get("bullets", [])
    
    qualifying = []
    over_target = current_pages > target_pages
    
    for bullet in bullets:
        line_count = bullet.get("line_count", 0)
        utilization = bullet.get("last_line_utilization_percent", 100)
        
        # If over target pages, condense ALL multi-line bullets (more aggressive)
        if over_target:
            if line_count >= 2:
                qualifying.append(bullet)
        else:
            # Normal criteria: multi-line (2+) AND low utilization (<15%)
            if line_count >= 2 and (utilization is None or utilization < 15):
                qualifying.append(bullet)
    
    return qualifying


def _format_qualifying_bullets(bullets: List[dict], current_pages: int, target_pages: int) -> str:
    """Format qualifying bullets for LLM consumption with actual line-by-line breakdown.
    
    Shows bullets with their actual rendered line breaks (where LaTeX automatically wraps)
    so the LLM can see the multi-line structure clearly.
    
    Args:
        bullets: List of bullet dictionaries from layout analysis (must have 'lines_text' field).
        current_pages: Current page count.
        target_pages: Target page count.
        
    Returns:
        Formatted string showing each bullet with its line-by-line breakdown and context.
    """
    lines = []
    over_target = current_pages > target_pages
    
    lines.append("=" * 80)
    lines.append("QUALIFYING BULLETS FOR CONDENSATION")
    lines.append("=" * 80)
    if over_target:
        lines.append(f"Resume is {current_pages} pages (target: {target_pages}). ALL multi-line bullets must be condensed.")
    else:
        lines.append("These bullets are multi-line (2+ lines) with low last-line utilization (<15%).")
    lines.append("You must condense these bullets to n-1 lines by removing words/content.")
    lines.append("")
    lines.append("IMPORTANT: Each bullet below shows its ACTUAL rendered line breaks.")
    lines.append("LaTeX automatically wraps text at word boundaries - these are the actual line breaks in the PDF.")
    lines.append("To reduce line count, you must remove enough words so the text no longer wraps to the last line.")
    lines.append("")
    
    for i, bullet in enumerate(bullets, 1):
        text_preview = bullet.get("text_preview", "")
        line_count = bullet.get("line_count", 0)
        utilization = bullet.get("last_line_utilization_percent", 0)
        target_lines = max(1, line_count - 1)
        
        # Estimate word count target based on line count
        # Rough estimate: ~15-20 words per line for typical resume bullets
        # To reduce from n lines to n-1, need to remove approximately 15-25 words
        if line_count == 2:
            word_target = "15-20 words"
        elif line_count == 3:
            word_target = "20-30 words"
        else:
            word_target = f"{15 * (line_count - 1)}-{25 * (line_count - 1)} words"
        
        lines.append(f"--- Bullet {i} ({line_count} lines -> target {target_lines} line(s), utilization: {utilization:.1f}%) ---")
        lines.append(f"TARGET: Remove approximately {word_target} to reduce line count")
        lines.append("")
        
        # Show line-by-line breakdown with actual rendered lines
        lines_text = bullet.get("lines_text", [])
        if lines_text and len(lines_text) > 1:
            lines.append("ACTUAL RENDERED LINE BREAKDOWN (this is how it appears in the PDF):")
            for line_idx, line_text in enumerate(lines_text, 1):
                word_count = len(line_text.split())
                # Show full line text (not truncated) so LLM can see exactly where breaks happen
                lines.append(f"  Line {line_idx} ({word_count} words): {line_text}")
            
            # Also show the full text as it would appear in LaTeX (for context)
            latex_source = bullet.get("latex_source", "")
            if latex_source:
                lines.append("")
                lines.append("LaTeX source context (for reference when editing):")
                # Truncate if very long, but show enough to see the structure
                if len(latex_source) > 200:
                    lines.append(f"  {latex_source[:200]}...")
                else:
                    lines.append(f"  {latex_source}")
        else:
            # Fallback: show text preview if lines_text not available
            lines.append("Full text:")
            lines.append(f"  {text_preview}")
        
        lines.append("")
        lines.append(f"ACTION REQUIRED: Remove {word_target} to reduce this bullet from {line_count} lines to {target_lines} line(s).")
        lines.append("Focus on the last line(s) - removing words there will most effectively reduce line count.")
        lines.append("")
        lines.append("")
    
    return "\n".join(lines)


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
# DSPy Signatures
# =============================================================================


class OptimizeATSKeywords(dspy.Signature):
    r"""Optimize resume for ATS by integrating job-relevant keywords through word-level changes.
    
    YOUR GOAL: Integrate keywords from the job description into the resume by REPLACING WORDS,
    not by adding or removing content. The content (achievements, metrics, experiences) must
    remain exactly the same - only the wording changes.
    
    ================================================================================
    CRITICAL CONSTRAINTS (HIGHEST PRIORITY):
    ================================================================================
    
    CONTENT PRESERVATION:
    - PRESERVE ALL CONTENT: Keep all achievements, metrics, experiences, technologies exactly the same
    - DO NOT add new achievements, metrics, or experiences
    - DO NOT remove any achievements, metrics, or experiences
    - DO NOT combine multiple bullets into one - each bullet must remain separate
    - DO NOT merge content from different bullets - preserve the exact bullet structure
    - Only change WORD CHOICES - replace generic words with job-specific keywords
    - Example: "built a database system" -> "developed a PostgreSQL database system" (replaced "built" with "developed", added "PostgreSQL" to replace generic "database")
    - Example: "worked on data" -> "analyzed datasets" (replaced "worked on data" with "analyzed datasets" - same content, different wording)
    - BAD: "built a database" -> "built a PostgreSQL database and optimized queries" (ADDED content - FORBIDDEN)
    - BAD: "built a database system" -> "built system" (REMOVED content - FORBIDDEN)
    - BAD: Combining two bullets into one - FORBIDDEN
    
    LaTeX RESTRICTIONS:
    - ONLY edit \\item content - no other LaTeX commands, environments, or structure can be changed
    - DO NOT modify: \\begin{}, \\end{}, \\textbf{}, \\textit{}, \\section{}, etc.
    - DO NOT modify: section environments, formatting commands, preamble
    - DO NOT modify: Skills section LaTeX structure (nospacetabbing, \\=, \\\\, \\>, \\underline)
    - ONLY change the text within \\item{} commands
    
    SECTION RESTRICTIONS:
    - SKILLS SECTION: Do NOT edit, modify, or change in ANY way - leave EXACTLY as-is
    - EDUCATION SECTION: Do NOT edit, modify, or change in ANY way - leave EXACTLY as-is (including coursework, GPA, dates)
    - EDitable sections: Work Experience, Personal Projects, Certifications, and other sections
    - When editing Work Experience or Projects: Only edit \\item content, not company names, titles, dates, or section structure
    
    KEYWORD INTEGRATION STRATEGY:
    - Read the job description carefully and extract ALL relevant keywords:
      * Technologies (e.g., "PostgreSQL", "React", "Kubernetes", "DSPy")
      * Skills (e.g., "machine learning", "data analysis", "API development")
      * Action verbs (e.g., "developed", "architected", "optimized", "deployed")
      * Domain terms (e.g., "microservices", "distributed systems", "CI/CD")
    - Replace generic terms with specific keywords:
      * "built" -> "developed" or "architected" (if appropriate)
      * "database" -> "PostgreSQL" or "MongoDB" (if specific technology used)
      * "AI system" -> "LLM pipeline" or "ML model" (if appropriate)
      * "worked on" -> "analyzed" or "implemented" (be specific)
    - Use both full terms and acronyms appropriately:
      * "Machine Learning" -> "ML" (if context allows)
      * "Large Language Model" -> "LLM" (if context allows)
      * But maintain clarity - don't over-abbreviate
    - Make MANY keyword changes throughout editable sections (aim for 10-20+ keyword integrations)
    - Maintain semantic meaning - the content must remain truthful and accurate
    
    WORD COUNT:
    - Keep word count approximately the same (minor variations OK, but no significant expansion)
    - If you add a specific keyword, try to remove a more generic word to balance
    - Example: "worked on database systems" -> "architected PostgreSQL databases" (added "PostgreSQL", removed "worked on", changed "systems" to "databases")
    
    FORMATTING - PRESERVE ALL LaTeX STRUCTURE EXACTLY:
    - Preserve LaTeX structure EXACTLY: \\begin{}, \\end{}, \\textbf{}, etc.
    - Keep ALL special characters: $|$ (pipe), \\& (ampersand), etc.
    - DO NOT remove LaTeX comments (lines starting with %)
    - DO NOT remove whitespace or reformat LaTeX code
    - DO NOT simplify or "clean up" LaTeX structure
    - ONLY change the text content inside \\item{} commands, NOT the commands themselves
    - Preserve ALL LaTeX environments, formatting, preamble, and structure exactly as-is
    - HEADER: Keep header (name, contact info) on SAME LINE - do not split across lines
    """
    
    resume_latex: str = dspy.InputField(desc="Resume in LaTeX format")
    job_description: str = dspy.InputField(desc="Job description - extract keywords and integrate them through word replacement")
    target_pages: int = dspy.InputField(desc="Target page count (keep in mind when making changes, but prioritize keyword integration)")
    optimized_latex: str = dspy.OutputField(desc="Resume with ATS keywords integrated through word-level replacements. Content preserved exactly, only wording changed. Only \\item content modified. Skills and Education sections unchanged. Bullet structure preserved - do not combine bullets.")


class ReducePageCount(dspy.Signature):
    r"""Reduce resume page count by condensing qualifying bullets.
    
    YOUR GOAL: Condense qualifying bullets to reduce page count. This is the ONLY time content removal is allowed.
    Follow the word removal targets specified for each bullet closely - these are estimates of how many words
    need to be removed to reduce the bullet from n lines to n-1 lines.
    
    ================================================================================
    CRITICAL CONSTRAINTS (HIGHEST PRIORITY):
    ================================================================================
    
    QUALIFYING BULLETS ONLY:
    - ONLY edit bullets that are listed in qualifying_bullets
    - ALL other bullets must remain EXACTLY unchanged
    - Do NOT edit single-line bullets
    - If resume is over target pages, ALL multi-line bullets are qualifying (more aggressive condensation needed)
    
    CONTENT REMOVAL ALLOWED:
    - This is the ONLY time content removal is allowed
    - For qualifying bullets, you CAN remove words and content to reduce from n lines to n-1 lines
    - Goal: Reduce each qualifying bullet from its current line count to (line_count - 1) lines
    - Each bullet has a specific word removal target (e.g., "Remove 15-20 words") - follow these targets closely
    - Example: 3-line bullet -> reduce to 2 lines, 2-line bullet -> reduce to 1 line
    
    DO NOT COMBINE BULLETS:
    - DO NOT combine multiple bullets into one - each bullet must remain separate
    - DO NOT merge content from different bullets - preserve the exact bullet structure
    - Preserve the same number of bullets - if there were 5 bullets, there must still be 5 bullets
    - Only condense individual bullets, do not merge them together
    
    LaTeX RESTRICTIONS:
    - ONLY edit \\item content for qualifying bullets
    - DO NOT modify any other LaTeX: \\begin{}, \\end{}, \\textbf{}, etc.
    - DO NOT modify section structure, formatting, or environments
    - ONLY change text within \\item{} commands for qualifying bullets
    
    SECTION RESTRICTIONS:
    - EDUCATION SECTION: Do NOT edit any bullets in Education section (even if they qualify)
    - Other sections: Can edit qualifying bullets
    
    CONDENSATION STRATEGY:
    - Follow the word removal targets specified for each bullet (e.g., "Remove 15-20 words")
    - Use abbreviations aggressively: "operational" -> "ops", "production-grade" -> "prod", "Machine Learning" -> "ML", "Large Language Model" -> "LLM"
    - Replace long phrases with shorter synonyms: "utilizing" -> "using", "demonstrated" -> "showed", "infrastructure" -> "infra"
    - Remove less critical details or parenthetical information
    - Remove redundant qualifiers: "successfully", "effectively" (if truly redundant)
    - Shorten phrases: "a team of 4" -> "4-person team", "improving operational success" -> "improving ops success"
    - Look at the line-by-line breakdown provided - target the longest lines for the most word removal
    - Remember: LaTeX breaks lines automatically when compiled - the only way to reduce lines is to remove words
    - Be AGGRESSIVE - remove the full word count target (or close to it) to ensure the bullet actually reduces in line count
    
    FORMATTING - PRESERVE ALL LaTeX STRUCTURE EXACTLY:
    - Preserve LaTeX structure EXACTLY: \\begin{}, \\end{}, \\textbf{}, etc.
    - Keep ALL special characters: $|$ (pipe), \\& (ampersand), etc.
    - DO NOT remove LaTeX comments (lines starting with %)
    - DO NOT remove whitespace or reformat LaTeX code
    - DO NOT simplify or "clean up" LaTeX structure
    - ONLY change the text content inside \\item{} commands for qualifying bullets, NOT the commands themselves
    - Preserve ALL LaTeX environments, formatting, preamble, and structure exactly as-is
    """
    
    resume_latex: str = dspy.InputField(desc="Resume in LaTeX format")
    target_pages: int = dspy.InputField(desc="Target number of pages")
    current_pages: int = dspy.InputField(desc="Current page count")
    qualifying_bullets: str = dspy.InputField(desc="Detailed breakdown of qualifying bullets with their ACTUAL rendered line breaks (showing where LaTeX wraps text). Each bullet shows its multi-line structure with line-by-line text, word counts, and removal targets.")
    optimized_latex: str = dspy.OutputField(desc="Resume with qualifying bullets condensed to n-1 lines. Only qualifying bullets modified. All LaTeX structure preserved except \\item content for qualifying bullets. Bullet structure preserved - do not combine bullets.")


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
    """Main pipeline for optimizing resumes with two-phase approach.

    Phase 1: ATS Keyword Integration
    Phase 2: Page Reduction (if needed)
    """

    def __init__(
        self,
        max_iterations: Optional[int] = None,
        target_pages: Optional[int] = None,
        max_bullet_lines: Optional[int] = None,
    ):
        """Initialize the optimizer pipeline.

        Args:
            max_iterations: Maximum iterations for Phase 2 (length reduction) (default: 3).
            target_pages: Target number of pages for the resume (default: 1).
            max_bullet_lines: Maximum lines per bullet point (default: 2).
        """
        super().__init__()
        # Use provided values or defaults (no longer fallback to settings since these come from frontend)
        self.max_iterations = max_iterations if max_iterations is not None else 3
        self.target_pages = target_pages if target_pages is not None else 1
        self.max_bullet_lines = max_bullet_lines if max_bullet_lines is not None else 2

        # Two separate optimizers for two-phase approach
        # Using ChainOfThought for better quality: improved keyword integration, professional language, and job description alignment
        self.ats_optimizer = dspy.ChainOfThought(OptimizeATSKeywords)
        self.page_reducer = dspy.ChainOfThought(ReducePageCount)

    def forward(
        self,
        resume_latex: str,
        job_description: str,
    ) -> OptimizationResult:
        """Run the optimization pipeline with two-phase approach.

        Args:
            resume_latex: Original resume in LaTeX format.
            job_description: Job description to optimize for.

        Returns:
            OptimizationResult with optimized LaTeX and PDF.
        """
        # Phase 1: ATS Keyword Optimization
        try:
            ats_result = self.ats_optimizer(
                resume_latex=resume_latex,
                job_description=job_description,
                target_pages=self.target_pages,
            )
            
            phase1_latex = _fix_latex_issues(ats_result.optimized_latex)
            
        except Exception as e:
            error_type = type(e).__name__
            error_details = str(e)
            logger.error(
                f"Phase 1 (ATS keyword optimization) failed: {error_type}: {error_details}",
                exc_info=True
            )
            # Log additional context for common errors
            if "API" in error_type or "openai" in error_details.lower():
                logger.error("Phase 1: This appears to be an OpenAI API error. Check API key and rate limits.")
            elif "timeout" in error_details.lower():
                logger.error("Phase 1: Request timed out. Model may be overloaded or response too long.")
            elif "token" in error_details.lower():
                logger.error("Phase 1: Token limit exceeded. Resume or job description may be too long.")
            
            return OptimizationResult(
                success=False,
                original_latex=resume_latex,
                optimized_latex=resume_latex,
                iterations=0,
                error_message=f"Phase 1 (ATS keyword optimization) failed: {error_type}: {error_details}",
                filename=None,
            )

        # Validate Phase 1 result
        is_valid, validation_error = validate_latex(phase1_latex)
        if not is_valid:
            logger.warning(f"Phase 1 LaTeX validation failed: {validation_error}")
            phase1_latex = _fix_latex_issues(phase1_latex)

        # Validate LaTeX structure (only \item content should change)
        structure_valid, structure_error = _validate_latex_structure(phase1_latex, resume_latex)
        if not structure_valid:
            logger.warning(f"Phase 1 LaTeX structure validation failed: {structure_error}")

        # Validate Skills and Education sections unchanged
        skills_preserved = _validate_section_preservation(phase1_latex, resume_latex, "Skills")
        education_preserved = _validate_section_preservation(phase1_latex, resume_latex, "Education")
        
        if not skills_preserved or not education_preserved:
            logger.warning("Phase 1: Skills or Education section was modified (should remain unchanged)")
        
        phase1_compile = compile_latex(phase1_latex)
        
        if not phase1_compile.success:
            logger.warning(f"Phase 1 compilation failed: {phase1_compile.error_message}")
            phase1_latex = _fix_latex_issues(phase1_latex)
            phase1_compile = compile_latex(phase1_latex)
            
            if not phase1_compile.success:
                logger.error(f"Phase 1 compilation still failed after fixes: {phase1_compile.error_message}")
                return OptimizationResult(
                    success=False,
                    original_latex=resume_latex,
                    optimized_latex=phase1_latex,
                    iterations=1,
                    error_message=f"Phase 1 compilation failed: {phase1_compile.error_message}",
                    filename=None,
                )

        # Phase 2: Page Reduction (only if needed)
        if phase1_compile.page_count <= self.target_pages:
            final_quality = check_quality(
                pdf_bytes=phase1_compile.pdf_bytes,
                target_pages=self.target_pages,
                max_bullet_lines=self.max_bullet_lines,
                latex=phase1_latex,
            )
            
            return OptimizationResult(
                success=final_quality.passes,
                original_latex=resume_latex,
                optimized_latex=phase1_latex,
                pdf_bytes=phase1_compile.pdf_bytes,
                page_count=final_quality.page_count,
                iterations=1,
                error_message=(
                    f"Quality issues remain: {final_quality.issues_summary}"
                    if not final_quality.passes else None
                ),
                filename=None,
            )

        # Phase 2: Length Reduction
        current_latex = phase1_latex
        current_compile = phase1_compile
        last_valid_latex = phase1_latex
        last_valid_pdf = phase1_compile.pdf_bytes
        last_quality_result = None

        # Phase 2: Length Reduction
        logger.info(f"Starting Phase 2: Page reduction (max {self.max_iterations} iterations)")
        for iteration in range(self.max_iterations):
            logger.info(f"Phase 2 iteration {iteration + 1}/{self.max_iterations}")

            # Get layout analysis
            current_pages = current_compile.page_count
            logger.info(f"Current page count: {current_pages} (target: {self.target_pages})")
            
            # Get bullets data with utilization calculated
            # Extract bullets and calculate utilization using same logic as analyze_layout
            bullet_metrics = extract_line_metrics(current_compile.pdf_bytes, latex=current_latex)
            bullets_data = bullet_metrics.get("bullets", [])
            
            # Calculate utilization for bullets (same logic as analyze_layout)
            doc = fitz.open(stream=current_compile.pdf_bytes, filetype="pdf")
            try:
                if len(doc) > 0:
                    page = doc[0]
                    text_dict = page.get_text("dict")
                    page_rect = page.rect
                    
                    # Find content boundaries
                    content_left = None
                    content_right = None
                    
                    for block in text_dict.get("blocks", []):
                        if "lines" in block:
                            for line in block["lines"]:
                                if "spans" in line:
                                    line_text = " ".join([span.get("text", "") for span in line.get("spans", [])]).strip()
                                    if len(line_text) > 3:
                                        for span in line["spans"]:
                                            if "text" in span and span["text"].strip():
                                                bbox = span.get("bbox", [])
                                                if len(bbox) == 4:
                                                    line_width = bbox[2] - bbox[0]
                                                    if line_width > 20:
                                                        if content_left is None or bbox[0] < content_left:
                                                            content_left = bbox[0]
                                                        if content_right is None or bbox[2] > content_right:
                                                            content_right = bbox[2]
                    
                    # Fallback to typical margins
                    if content_left is None:
                        content_left = page_rect.x0 + 36
                    if content_right is None:
                        content_right = page_rect.x1 - 36
                    
                    available_width = content_right - content_left
                    
                    # Calculate utilization for each bullet
                    for bullet in bullets_data:
                        last_line_x_end = bullet.get("last_line_x_end")
                        last_line_x_start = bullet.get("last_line_x_start")
                        if last_line_x_end is not None and last_line_x_start is not None:
                            used_width = last_line_x_end - last_line_x_start
                            utilization_percent = (used_width / available_width) * 100 if available_width > 0 else 0
                            bullet["last_line_utilization_percent"] = utilization_percent
                        else:
                            # No coordinates available - assume 100% utilization
                            bullet["last_line_utilization_percent"] = 100
            finally:
                doc.close()
            
            # Filter qualifying bullets (more aggressive if over target pages)
            qualifying_bullets_list = _filter_qualifying_bullets(
                {"bullets": bullets_data},
                current_pages=current_pages,
                target_pages=self.target_pages,
            )
            
            if not qualifying_bullets_list:
                logger.warning(f"No qualifying bullets found in iteration {iteration + 1}. Cannot reduce page count further.")
                logger.info(f"Phase 2 stopped early at iteration {iteration + 1}/{self.max_iterations} (no qualifying bullets)")
                break
            
            # Format qualifying bullets for LLM with word count targets
            qualifying_bullets_str = _format_qualifying_bullets(
                qualifying_bullets_list,
                current_pages=current_pages,
                target_pages=self.target_pages,
            )
            
            # Found qualifying bullets to condense (no log needed)
            
            # Call page reducer
            try:
                phase2_result = self.page_reducer(
                    resume_latex=current_latex,
                    target_pages=self.target_pages,
                    current_pages=current_pages,
                    qualifying_bullets=qualifying_bullets_str,
                )
                
                current_latex = _fix_latex_issues(phase2_result.optimized_latex)
                
            except Exception as e:
                error_type = type(e).__name__
                error_details = str(e)
                logger.error(
                    f"Phase 2 iteration {iteration + 1}: DSPy page reducer failed: {error_type}: {error_details}",
                    exc_info=True
                )
                # Log additional context for common errors
                if "API" in error_type or "openai" in error_details.lower():
                    logger.error(f"Phase 2 iteration {iteration + 1}: OpenAI API error. Check API key and rate limits.")
                elif "timeout" in error_details.lower():
                    logger.error(f"Phase 2 iteration {iteration + 1}: Request timed out.")
                elif "token" in error_details.lower():
                    logger.error(f"Phase 2 iteration {iteration + 1}: Token limit exceeded.")
                
                # Continue with last valid version
                logger.warning(f"Phase 2 iteration {iteration + 1}: Reverting to last valid version due to DSPy error")
                current_latex = last_valid_latex
                continue
            
            # Compile and validate
            # Compiling LaTeX to PDF (no log needed for each iteration)
            current_compile = compile_latex(current_latex)
            
            if not current_compile.success:
                logger.warning(f"Compilation failed in Phase 2 iteration {iteration + 1}")
                current_latex = _fix_latex_issues(current_latex)
                current_compile = compile_latex(current_latex)
                if not current_compile.success:
                    logger.error(f"Still failed after fixes, reverting to last valid")
                    current_latex = last_valid_latex
                    continue

            # Quality check
            quality_result = check_quality(
                pdf_bytes=current_compile.pdf_bytes,
                target_pages=self.target_pages,
                max_bullet_lines=self.max_bullet_lines,
                latex=current_latex,
            )
            
            if quality_result.passes:
                return OptimizationResult(
                    success=True,
                    original_latex=resume_latex,
                    optimized_latex=current_latex,
                    pdf_bytes=current_compile.pdf_bytes,
                    page_count=quality_result.page_count,
                    iterations=iteration + 2,  # Phase 1 (1) + Phase 2 iterations
                    filename=None,
                )
            
            # Store as last valid
            last_valid_latex = current_latex
            last_valid_pdf = current_compile.pdf_bytes
            last_quality_result = quality_result
            
            logger.warning(f"Phase 2 iteration {iteration + 1}: Quality issues remain: {quality_result.issues_summary}")

        # Max iterations reached - return best effort
        logger.warning(f"Phase 2 completed {self.max_iterations} iterations (max reached)")
        final_compile = compile_latex(current_latex)
        
        if final_compile.success:
            final_quality = check_quality(
                pdf_bytes=final_compile.pdf_bytes,
                target_pages=self.target_pages,
                max_bullet_lines=self.max_bullet_lines,
                latex=current_latex,
            )
            
            return OptimizationResult(
                success=final_quality.passes,
                original_latex=resume_latex,
                optimized_latex=current_latex,
                pdf_bytes=final_compile.pdf_bytes,
                page_count=final_quality.page_count,
                iterations=self.max_iterations + 1,  # Phase 1 (1) + Phase 2 max iterations
                error_message=(
                    f"Quality issues remain after Phase 2: {final_quality.issues_summary}"
                    if not final_quality.passes else None
                ),
                filename=None,
            )
        else:
            # Return last valid version
            return OptimizationResult(
                success=False,
                original_latex=resume_latex,
                optimized_latex=last_valid_latex,
                pdf_bytes=last_valid_pdf,
                page_count=last_quality_result.page_count if last_quality_result else 0,
                iterations=self.max_iterations + 1,
                error_message=f"Final compilation failed: {final_compile.error_message}",
                filename=None,
            )


def configure_dspy(
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> None:
    """Configure DSPy with the specified model.

    Args:
        model_name: Model identifier (e.g., "openai/gpt-5-mini").
        api_key: OpenAI API key. If not provided, uses settings.
        max_tokens: Maximum tokens for LLM responses. Defaults to settings.max_tokens.
        temperature: Temperature for generation. Defaults to settings.temperature.
    """
    model_name = model_name or settings.model_name
    api_key = api_key or settings.openai_api_key
    max_tokens = max_tokens or settings.max_tokens
    temperature = temperature or settings.temperature

    try:
        lm = dspy.LM(
            model=model_name,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            cache=False
        )
        dspy.configure(lm=lm)
    except Exception as e:
        error_type = type(e).__name__
        error_details = str(e)
        logger.error(f"Failed to configure DSPy: {error_type}: {error_details}", exc_info=True)
        raise


def optimize_resume(
    resume_latex: str,
    job_description: str,
    max_iterations: Optional[int] = None,
    target_pages: Optional[int] = None,
    max_bullet_lines: Optional[int] = None,
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
    )

    return pipeline(resume_latex, job_description)
