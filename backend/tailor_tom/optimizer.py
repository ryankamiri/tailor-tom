"""DSPy-based resume optimization for ATS.

This module implements a two-phase optimization pipeline:
1. Phase 1: ATS keyword optimization (word-level changes, no content addition/removal)
2. Phase 2: Page reduction (condensing qualifying bullets, content removal allowed)
"""

import gc
import logging
import os
import re
import sys
import tracemalloc
from dataclasses import dataclass
from typing import Optional, List, Tuple

import dspy
import fitz  # PyMuPDF
import psutil

from tailor_tom.config import settings
from tailor_tom.latex_compiler import compile_latex, CompileResult, validate_latex
from tailor_tom.layout_analyzer import analyze_layout, check_quality, QualityResult, extract_line_metrics
from api.storage import update_job_status

logger = logging.getLogger(__name__)


def _get_memory_mb() -> float:
    """Get current memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def _log_memory_snapshot(label: str, job_id: Optional[str] = None, threshold_mb: float = 400.0) -> None:
    """Log detailed memory snapshot with tracemalloc statistics.
    
    Args:
        label: Label for this memory snapshot (e.g., "after LLM call")
        job_id: Optional job ID for logging context
        threshold_mb: Memory threshold in MB to trigger warnings (default: 400MB)
    """
    current_memory = _get_memory_mb()
    
    # Log basic memory info
    job_prefix = f"Job {job_id} " if job_id else ""
    logger.error(f"[MEMORY] [{label}] {job_prefix}{current_memory:.1f} MB")
    
    # Check threshold
    if current_memory > threshold_mb:
        logger.error(f"[MEMORY] [WARNING] {job_prefix}memory ({current_memory:.1f} MB) exceeds threshold ({threshold_mb:.1f} MB) at {label}")
    
    # Get tracemalloc statistics if available
    if tracemalloc.is_tracing():
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')
        
        # Log top 10 memory allocations
        logger.error(f"[MEMORY] [TRACEMALLOC] [{label}] {job_prefix}Top 10 allocations:")
        for index, stat in enumerate(top_stats[:10], 1):
            traceback_line = stat.traceback.format()[-1] if stat.traceback else "unknown"
            logger.error(f"[MEMORY] [TRACEMALLOC] #{index}: {traceback_line}: {stat.size / 1024 / 1024:.2f} MB ({stat.count} blocks)")
        
        # Get current vs peak memory
        current, peak = tracemalloc.get_traced_memory()
        logger.error(f"[MEMORY] [TRACEMALLOC] [{label}] {job_prefix}Traced: {current / 1024 / 1024:.2f} MB current, {peak / 1024 / 1024:.2f} MB peak")


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
    Also preserves command definitions (\\newcommand, \\renewcommand) exactly.
    Handles both raw \\item and custom item commands like \\resumeItem.
    
    Args:
        latex: LaTeX source code.
        
    Returns:
        LaTeX with \\item content replaced by placeholders, but command definitions preserved.
    """
    # FIRST: Normalize whitespace BEFORE extraction to ensure consistent structure comparison
    # This handles cases where LLM only changes whitespace (blank lines, spacing between items)
    # We normalize here so that structural differences are only detected if actual LaTeX commands/structure change
    normalized_latex = re.sub(r'[ \t]+', ' ', latex)  # Multiple spaces/tabs -> single space
    normalized_latex = re.sub(r'[ \t]*\n[ \t]*', '\n', normalized_latex)  # Normalize newlines (remove spaces around them)
    normalized_latex = re.sub(r'\n\n\n+', '\n\n', normalized_latex)  # Multiple blank lines -> double newline max
    normalized_latex = re.sub(r'[ \t]+$', '', normalized_latex, flags=re.MULTILINE)  # Remove trailing spaces on lines
    
    # Extract command definitions and replace with placeholders
    command_defs = _extract_command_definitions(normalized_latex)
    
    # Find all commands that produce items (like \resumeItem)
    # Parse command definitions to find commands that expand to \item
    item_producing_commands = set(['item'])  # Always include raw \item
    
    for cmd_def in command_defs:
        # Extract command name and definition
        # Pattern: \newcommand{\command}[args]{definition} or \renewcommand{\command}[args]{definition}
        # Handle multi-line definitions by matching braces properly
        cmd_match = re.search(r'\\(?:new|renew|provide)command\s*\{([^}]+)\}(?:\[[^\]]+\])?\s*\{', cmd_def)
        if cmd_match:
            cmd_name = cmd_match.group(1)
            # Check if definition contains \item (look for \item in the definition part)
            # The definition starts after the opening brace
            def_start = cmd_match.end()
            # Find matching closing brace
            brace_count = 1
            i = def_start
            while i < len(cmd_def) and brace_count > 0:
                if cmd_def[i] == '{':
                    brace_count += 1
                elif cmd_def[i] == '}':
                    brace_count -= 1
                i += 1
            if brace_count == 0:
                definition = cmd_def[def_start:i-1]  # Exclude closing brace
                if r'\item' in definition:
                    item_producing_commands.add(cmd_name)
    
    # Replace each command definition with a placeholder
    latex_with_placeholders = normalized_latex
    for i, cmd_def in enumerate(command_defs):
        placeholder = f"COMMAND_DEF_{i}"
        latex_with_placeholders = latex_with_placeholders.replace(cmd_def, placeholder, 1)
    
    # Replace all item commands (both raw \item and custom commands like \resumeItem)
    # CRITICAL: We need to find items and replace their ENTIRE content, which can span multiple lines
    # and contain nested commands. We'll find item positions and replace content up to the next item/environment boundary.
    
    # Find all item positions in the document
    item_positions = []
    
    # Find all item commands
    for cmd in item_producing_commands:
        escaped_cmd = re.escape(cmd)
        # Match \item (not part of another command) followed by whitespace
        # Items can be: \item{content} or \item content (without braces)
        pattern = rf'\\{escaped_cmd}(?![a-zA-Z])(?:\s*\{{|\s+)'
        for match in re.finditer(pattern, latex_with_placeholders):
            item_start = match.start()
            item_cmd_end = match.end()
            
            # Check if it's \item{...} or \item content
            content_start = item_cmd_end
            if latex_with_placeholders[match.end()-1] == '{':
                # It's \item{content} - find matching brace
                brace_depth = 1
                pos = match.end()
                while pos < len(latex_with_placeholders) and brace_depth > 0:
                    if latex_with_placeholders[pos] == '{':
                        brace_depth += 1
                    elif latex_with_placeholders[pos] == '}':
                        brace_depth -= 1
                    pos += 1
                if brace_depth == 0:
                    # Found matching brace - replace content inside
                    content_end = pos - 1  # Position of closing brace
                    item_positions.append({
                        'start': item_start,
                        'content_start': match.end(),  # After opening brace
                        'content_end': content_end,  # Before closing brace
                        'end': pos,  # After closing brace
                        'has_braces': True
                    })
                    continue
            
            # It's \item content (without braces) - find where content ends
            # Look for: next \item, \end{itemize}, \end{enumerate}, \end{subitems}, \end{resume_subsection}, \begin{resume_section}
            content_end = len(latex_with_placeholders)
            
            # Check for next item
            next_item_pattern = rf'\\item(?![a-zA-Z])(?:\s*\{{|\s+)'
            next_item_match = re.search(next_item_pattern, latex_with_placeholders[content_start:])
            if next_item_match:
                content_end = min(content_end, content_start + next_item_match.start())
            
            # Check for environment boundaries
            boundaries = [
                latex_with_placeholders.find('\\end{itemize}', content_start),
                latex_with_placeholders.find('\\end{enumerate}', content_start),
                latex_with_placeholders.find('\\end{subitems}', content_start),
                latex_with_placeholders.find('\\end{resume_subsection}', content_start),
                latex_with_placeholders.find('\\begin{resume_section}', content_start),
            ]
            valid_boundaries = [b for b in boundaries if b != -1 and b < content_end]
            if valid_boundaries:
                content_end = min(content_end, min(valid_boundaries))
            
            item_positions.append({
                'start': item_start,
                'content_start': content_start,
                'content_end': content_end,
                'end': content_end,
                'has_braces': False
            })
    
    # Sort by position (reverse order so we can replace from end to start without affecting positions)
    item_positions.sort(key=lambda x: x['start'], reverse=True)
    
    # Replace each item's content with PLACEHOLDER
    for idx, item_info in enumerate(item_positions):
        if item_info['has_braces']:
            # \item{content} -> \item{PLACEHOLDER}
            original_content = latex_with_placeholders[item_info['content_start']:item_info['content_end']]
            latex_with_placeholders = (
                latex_with_placeholders[:item_info['content_start']] +
                'PLACEHOLDER' +
                latex_with_placeholders[item_info['content_end']:]
            )
        else:
            # \item content -> \item{PLACEHOLDER}
            content = latex_with_placeholders[item_info['content_start']:item_info['content_end']].strip()
            if content:  # Only replace if there's content
                # Replace \item content with \item{PLACEHOLDER}
                latex_with_placeholders = (
                    latex_with_placeholders[:item_info['start']] +
                    '\\item{PLACEHOLDER}' +
                    latex_with_placeholders[item_info['end']:]
                )
    
    replaced = latex_with_placeholders
    
    # Restore command definitions
    for i, cmd_def in enumerate(command_defs):
        replaced = replaced.replace(f"COMMAND_DEF_{i}", cmd_def)
    
    # Final normalization pass to ensure consistent structure
    # This handles any edge cases where item replacement might have introduced inconsistencies
    replaced = re.sub(r'\n\n\n+', '\n\n', replaced)  # Multiple blank lines -> double newline max
    
    # Normalize trailing newlines - ensure both end with exactly one newline
    replaced = replaced.rstrip('\n')
    replaced = replaced + '\n'  # Add exactly one trailing newline
    
    return replaced


def _extract_command_definitions(latex: str) -> List[str]:
    """Extract all command definitions from LaTeX.
    
    Args:
        latex: LaTeX source code.
        
    Returns:
        List of command definition strings.
    """
    command_defs = []
    i = 0
    
    while i < len(latex):
        # Check for command definition start
        cmd_patterns = [
            r'\\newcommand\*?',
            r'\\renewcommand\*?',
            r'\\providecommand\*?',
            r'\\DeclareRobustCommand\*?',
        ]
        
        matched = False
        for pattern in cmd_patterns:
            match = re.match(pattern, latex[i:])
            if match:
                # Found a command definition start
                cmd_start = i
                cmd_text = match.group(0)
                i += len(cmd_text)
                
                # Skip whitespace
                while i < len(latex) and latex[i].isspace():
                    i += 1
                
                # Parse command name: {\command}
                if i < len(latex) and latex[i] == '{':
                    brace_depth = 1
                    i += 1
                    while i < len(latex) and brace_depth > 0:
                        if latex[i] == '{':
                            brace_depth += 1
                        elif latex[i] == '}':
                            brace_depth -= 1
                        i += 1
                    
                    # Skip whitespace
                    while i < len(latex) and latex[i].isspace():
                        i += 1
                    
                    # Parse optional parameter count: [num]
                    if i < len(latex) and latex[i] == '[':
                        brace_depth = 1
                        i += 1
                        while i < len(latex) and brace_depth > 0:
                            if latex[i] == '[':
                                brace_depth += 1
                            elif latex[i] == ']':
                                brace_depth -= 1
                            i += 1
                        
                        # Skip whitespace
                        while i < len(latex) and latex[i].isspace():
                            i += 1
                    
                    # Parse definition: {definition}
                    if i < len(latex) and latex[i] == '{':
                        brace_depth = 1
                        i += 1
                        while i < len(latex) and brace_depth > 0:
                            if latex[i] == '{':
                                brace_depth += 1
                            elif latex[i] == '}':
                                brace_depth -= 1
                            i += 1
                        
                        # Extract full command definition
                        cmd_def = latex[cmd_start:i]
                        command_defs.append(cmd_def)
                        matched = True
                        break
        
        if not matched:
            i += 1
    
    return command_defs


def _validate_latex_structure(optimized_latex: str, original_latex: str) -> Tuple[bool, str]:
    """Validate that only \\item content was changed, not LaTeX structure.
    
    Checks:
    1. Command definitions (\\newcommand, \\renewcommand, etc.) are unchanged
    2. Non-item LaTeX structure is unchanged
    
    Args:
        optimized_latex: Optimized LaTeX source.
        original_latex: Original LaTeX source.
        
    Returns:
        Tuple of (is_valid, error_message). is_valid is True if structure preserved.
    """
    
    # First, check command definitions separately (most critical)
    original_cmd_defs = sorted(_extract_command_definitions(original_latex))
    optimized_cmd_defs = sorted(_extract_command_definitions(optimized_latex))
    
    
    if original_cmd_defs != optimized_cmd_defs:
        logger.error("[STRUCTURE VALIDATION] Command definitions differ!")
        logger.error(f"[STRUCTURE VALIDATION] Original commands: {original_cmd_defs}")
        logger.error(f"[STRUCTURE VALIDATION] Optimized commands: {optimized_cmd_defs}")
        
        # Find which command was modified
        modified_commands = []
        original_set = set(original_cmd_defs)
        optimized_set = set(optimized_cmd_defs)
        
        added_commands = optimized_set - original_set
        removed_commands = original_set - optimized_set
        
        if added_commands:
            logger.error(f"[STRUCTURE VALIDATION] Added commands: {added_commands}")
        if removed_commands:
            logger.error(f"[STRUCTURE VALIDATION] Removed commands: {removed_commands}")
        
        for cmd in optimized_set - original_set:
            # Extract command name (first {command} after \newcommand, etc.)
            cmd_name_match = re.search(r'\{([^}]+)\}', cmd)
            if cmd_name_match:
                modified_commands.append(cmd_name_match.group(1))
        
        for cmd in original_set - optimized_set:
            cmd_name_match = re.search(r'\{([^}]+)\}', cmd)
            if cmd_name_match:
                modified_commands.append(cmd_name_match.group(1))
        
        if modified_commands:
            return False, f"Command definitions were modified: {', '.join(modified_commands)}. Command definitions (\\newcommand, \\renewcommand, etc.) must NEVER be changed."
        else:
            return False, "Command definitions were modified. Command definitions (\\newcommand, \\renewcommand, etc.) must NEVER be changed."
    
    # Extract non-item LaTeX (structure only)
    original_structure = _extract_non_item_latex(original_latex)
    optimized_structure = _extract_non_item_latex(optimized_latex)
    
    if original_structure != optimized_structure:
        logger.error("[STRUCTURE VALIDATION] LaTeX structure differs!")
        logger.error("=" * 80)
        logger.error("[STRUCTURE VALIDATION] ORIGINAL STRUCTURE (first 2000 chars):")
        logger.error(original_structure[:2000])
        logger.error("=" * 80)
        logger.error("[STRUCTURE VALIDATION] OPTIMIZED STRUCTURE (first 2000 chars):")
        logger.error(optimized_structure[:2000])
        logger.error("=" * 80)
        
        # Find the first difference
        import difflib
        diff = list(difflib.unified_diff(
            original_structure.splitlines(keepends=True),
            optimized_structure.splitlines(keepends=True),
            fromfile='original',
            tofile='optimized',
            lineterm='',
            n=3
        ))
        
        if diff:
            logger.error("[STRUCTURE VALIDATION] First differences found:")
            for line in diff[:50]:  # Show first 50 lines of diff
                logger.error(f"[STRUCTURE VALIDATION] {line.rstrip()}")
        
        # Also try to find character-level differences
        min_len = min(len(original_structure), len(optimized_structure))
        first_diff_pos = None
        for i in range(min_len):
            if original_structure[i] != optimized_structure[i]:
                first_diff_pos = i
                break
        
        if first_diff_pos is not None:
            logger.error(f"[STRUCTURE VALIDATION] First character difference at position {first_diff_pos}")
            start = max(0, first_diff_pos - 100)
            end = min(len(original_structure), first_diff_pos + 100)
            logger.error(f"[STRUCTURE VALIDATION] Original context (pos {start}-{end}):")
            logger.error(repr(original_structure[start:end]))
            logger.error(f"[STRUCTURE VALIDATION] Optimized context (pos {start}-{end}):")
            logger.error(repr(optimized_structure[start:end]))
        elif len(original_structure) != len(optimized_structure):
            logger.error(f"[STRUCTURE VALIDATION] Structures have different lengths: {len(original_structure)} vs {len(optimized_structure)}")
            logger.error(f"[STRUCTURE VALIDATION] Original repr (last 200): {repr(original_structure[-200:])}")
            logger.error(f"[STRUCTURE VALIDATION] Optimized repr (last 200): {repr(optimized_structure[-200:])}")
            if len(original_structure) < len(optimized_structure):
                logger.error(f"[STRUCTURE VALIDATION] Optimized has {len(optimized_structure) - len(original_structure)} extra characters at end")
                logger.error(f"[STRUCTURE VALIDATION] Extra content: {repr(optimized_structure[len(original_structure):len(original_structure)+200])}")
            else:
                logger.error(f"[STRUCTURE VALIDATION] Original has {len(original_structure) - len(optimized_structure)} extra characters at end")
                logger.error(f"[STRUCTURE VALIDATION] Missing content: {repr(original_structure[len(optimized_structure):len(optimized_structure)+200])}")
        
        logger.error("=" * 80)
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


def _filter_qualifying_bullets(
    layout_analysis: dict, 
    current_pages: int, 
    target_pages: int, 
    max_bullet_lines: int
) -> List[dict]:
    """Filter bullets that meet Phase 2 criteria for condensation.
    
    Bullets qualify if:
    1. They are too long (> max_bullet_lines), OR
    2. Resume is over target pages AND bullet is multi-line (2+), OR
    3. Resume is at/below target pages AND bullet is multi-line (2+) with low utilization (<15%)
    
    Args:
        layout_analysis: Dictionary containing bullets data.
        current_pages: Current page count.
        target_pages: Target page count.
        max_bullet_lines: Maximum allowed lines per bullet.
        
    Returns:
        List of bullet dictionaries that meet the criteria.
    """
    bullets = layout_analysis.get("bullets", [])
    
    qualifying = []
    over_target = current_pages > target_pages
    
    for bullet in bullets:
        line_count = bullet.get("line_count", 0)
        utilization = bullet.get("last_line_utilization_percent", 100)
        
        # Priority 1: Bullets that are too long (> max_bullet_lines) - always qualify
        if line_count > max_bullet_lines:
            qualifying.append(bullet)
        # Priority 2: If over target pages, condense ALL multi-line bullets (more aggressive)
        elif over_target and line_count >= 2:
            qualifying.append(bullet)
        # Priority 3: Normal criteria: multi-line (2+) AND low utilization (<15%)
        elif line_count >= 2 and (utilization is None or utilization < 15):
            qualifying.append(bullet)
    
    return qualifying


def _format_qualifying_bullets(
    bullets: List[dict], 
    current_pages: int, 
    target_pages: int, 
    max_bullet_lines: int
) -> str:
    """Format qualifying bullets for LLM consumption with actual line-by-line breakdown.
    
    Shows bullets with their actual rendered line breaks (where LaTeX automatically wraps)
    so the LLM can see the multi-line structure clearly.
    
    Args:
        bullets: List of bullet dictionaries from layout analysis (must have 'lines_text' field).
        current_pages: Current page count.
        target_pages: Target page count.
        max_bullet_lines: Maximum allowed lines per bullet.
        
    Returns:
        Formatted string showing each bullet with its line-by-line breakdown and context.
    """
    lines = []
    over_target = current_pages > target_pages
    
    lines.append("=" * 80)
    lines.append("QUALIFYING BULLETS FOR CONDENSATION")
    lines.append("=" * 80)
    
    # Identify why bullets qualify
    long_bullets = [b for b in bullets if b.get("line_count", 0) > max_bullet_lines]
    if long_bullets:
        lines.append(f"These bullets are TOO LONG (> {max_bullet_lines} lines) and must be condensed.")
    if over_target:
        lines.append(f"Resume is {current_pages} pages (target: {target_pages}). Multi-line bullets must be condensed to reduce page count.")
    if not long_bullets and not over_target:
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
    
    LaTeX RESTRICTIONS - CRITICAL: ONLY EDIT TEXT CONTENT:
    - ONLY edit the TEXT CONTENT within bullet points - identify bullet points by their structure (they may use \\item, \\resumeItem, or any custom command)
    - DO NOT modify ANY LaTeX commands, environments, or structure - ONLY the text words
    - DO NOT modify: \\begin{}, \\end{}, \\textbf{}, \\textit{}, \\section{}, \\item, \\resumeItem, or ANY commands
    - CRITICAL: NEVER remove or modify \\end{} tags - they MUST remain exactly as-is (e.g., \\end{resume_subsection}, \\end{resume_section}, \\end{subitems})
    - CRITICAL: NEVER uncomment commented sections - if a line starts with %, keep the % exactly as-is
    - CRITICAL: NEVER remove blank lines between sections - preserve all whitespace and line breaks exactly
    - DO NOT modify: section environments, formatting commands, preamble, custom commands, or ANY LaTeX structure
    - DO NOT modify: Skills section LaTeX structure (nospacetabbing, \\=, \\\\, \\>, \\underline)
    - DO NOT modify: tabular environments, table structures, or ANY formatting
    - CRITICAL - COMMAND DEFINITIONS: DO NOT modify ANY command definitions in the preamble:
      * DO NOT modify: \\newcommand{\\command}{...}, \\renewcommand{\\command}{...}, \\providecommand{\\command}{...}
      * DO NOT modify: ANY command definition, including \\contact, \\name, \\resumeItem, or ANY custom command
      * Command definitions (like \\newcommand{\\contact}[1]{...}) must remain EXACTLY as-is - changing them will break LaTeX compilation
      * Example of FORBIDDEN: \\newcommand{\\contact}[1]{...} -> \\newcommand{\\contact}[2]{...} (changed parameter count)
      * Example of FORBIDDEN: \\newcommand{\\contact}[1]{...} -> \\renewcommand{\\contact}[1]{...} (changed command type)
    - ONLY change the actual text words within bullet point content - preserve ALL LaTeX commands exactly as-is
    - Example: If bullet is "\\item{Built a database}" -> "\\item{Developed a PostgreSQL database}" (changed words, kept \\item{} exactly)
    - Example: If bullet is "\\resumeItem{Built a database}" -> "\\resumeItem{Developed a PostgreSQL database}" (changed words, kept \\resumeItem{} exactly)
    - BAD: "\\item{Built}" -> "\\textbf{\\item{Built}}" (added command - FORBIDDEN)
    - BAD: "\\item{Built}" -> "Built" (removed command - FORBIDDEN)
    
    SECTION RESTRICTIONS:
    - SKILLS SECTION: Do NOT edit, modify, or change in ANY way - leave EXACTLY as-is
    - EDUCATION SECTION: Do NOT edit, modify, or change in ANY way - leave EXACTLY as-is (including coursework, GPA, dates)
    - EDitable sections: Work Experience, Personal Projects, Certifications, and other sections
    - When editing Work Experience or Projects: Only edit \\item content, not company names, titles, dates, or section structure
    
    KEYWORD INTEGRATION STRATEGY - VARIETY OVER REPETITION:
    - Read the job description carefully and extract ALL relevant keywords and their synonyms:
      * Technologies (e.g., "PostgreSQL", "React", "Kubernetes", "DSPy")
      * Skills (e.g., "machine learning", "data analysis", "API development")
      * Action verbs (e.g., "developed", "architected", "optimized", "deployed")
      * Domain terms (e.g., "microservices", "distributed systems", "CI/CD")
    
    - CRITICAL: PRIORITIZE KEYWORD VARIETY - AVOID EXCESSIVE REPETITION:
      * DO NOT repeat the same keyword more than 2-3 times throughout the entire resume
      * Instead, use synonyms and related terms to show the same skills:
        - "RESTful APIs" -> also use "REST APIs", "web APIs", "API development", "API services"
        - "machine learning" -> also use "ML", "ML models", "predictive analytics", "data science"
        - "developed" -> also use "architected", "built", "engineered", "implemented", "created"
        - "database" -> also use "PostgreSQL", "MongoDB", "data store", "persistence layer"
      * Use semantic variations: "API" can become "RESTful services", "web services", "endpoints", "API endpoints"
      * Natural integration: Keywords should fit naturally in context, not feel forced
    
    - Replace generic terms with specific keywords (use variety):
      * "built" -> "developed", "architected", "engineered" (rotate these, don't always use the same one)
      * "database" -> "PostgreSQL", "MongoDB", "data store" (use different terms in different bullets)
      * "AI system" -> "LLM pipeline", "ML model", "AI solution" (vary the terminology)
      * "worked on" -> "analyzed", "implemented", "designed", "optimized" (use different action verbs)
    
    - Use both full terms and acronyms appropriately (but vary them):
      * "Machine Learning" -> use "ML" in some places, "machine learning" in others, "ML models" elsewhere
      * "Large Language Model" -> use "LLM" in some places, "language models" in others
      * "RESTful API" -> use "REST APIs", "RESTful services", "web APIs" - don't repeat the same phrase
    
    - Make MANY keyword changes throughout editable sections (aim for 10-20+ keyword integrations)
    - Maintain semantic meaning - the content must remain truthful and accurate
    - Natural language: The resume should read naturally to human reviewers, not like keyword stuffing
    
    WORD COUNT:
    - Keep word count approximately the same (minor variations OK, but no significant expansion)
    - If you add a specific keyword, try to remove a more generic word to balance
    - Example: "worked on database systems" -> "architected PostgreSQL databases" (added "PostgreSQL", removed "worked on", changed "systems" to "databases")
    
    FORMATTING - PRESERVE ALL LaTeX STRUCTURE EXACTLY:
    - Preserve ALL LaTeX structure EXACTLY: \\begin{}, \\end{}, \\textbf{}, \\item, \\resumeItem, or ANY commands
    - CRITICAL: NEVER remove or modify \\end{} tags - they MUST remain exactly as-is (e.g., \\end{resume_subsection}, \\end{resume_section}, \\end{subitems})
    - CRITICAL: NEVER uncomment commented sections - if a line starts with %, keep the % exactly as-is
    - CRITICAL: NEVER remove blank lines between sections - preserve all whitespace and line breaks exactly
    - Keep ALL special characters: $|$ (pipe), \\& (ampersand), etc.
    - DO NOT remove LaTeX comments (lines starting with %) - keep the % character exactly as-is
    - DO NOT remove whitespace or reformat LaTeX code
    - DO NOT simplify or "clean up" LaTeX structure
    - CRITICAL - COMMAND DEFINITIONS: DO NOT modify ANY command definitions in the preamble:
      * DO NOT modify: \\newcommand{\\command}{...}, \\renewcommand{\\command}{...}, \\providecommand{\\command}{...}
      * DO NOT modify: ANY command definition, including \\contact, \\name, \\resumeItem, or ANY custom command
      * Command definitions must remain EXACTLY as-is - changing them will break LaTeX compilation with "Illegal parameter number" errors
    - ONLY change the actual text words within bullet point content - identify bullets by their structure (may use \\item, \\resumeItem, or any custom command)
    - Preserve ALL LaTeX environments, formatting, preamble, custom commands, and structure exactly as-is
    - HEADER: Keep header (name, contact info) on SAME LINE - do not split across lines
    - REMEMBER: Different resumes use different bullet commands - work with whatever command is used, but ONLY edit the text content inside it
    """
    
    resume_latex: str = dspy.InputField(desc="Resume in LaTeX format")
    job_description: str = dspy.InputField(desc="Job description - extract keywords and integrate them through word replacement")
    target_pages: int = dspy.InputField(desc="Target page count (keep in mind when making changes, but prioritize keyword integration)")
    optimized_latex: str = dspy.OutputField(desc="Resume with ATS keywords integrated through word-level replacements with VARIETY. Use synonyms and related terms - avoid repeating the same keyword more than 2-3 times. Content preserved exactly, only wording changed. ONLY text content within bullet points modified (regardless of whether bullets use \\item, \\resumeItem, or any custom command). ALL LaTeX structure, commands, and formatting preserved exactly. Skills and Education sections unchanged. Bullet structure preserved - do not combine bullets. Natural language - should read well to human reviewers.")


class CondenseLongBullets(dspy.Signature):
    r"""Condense long bullets to improve resume quality and reduce page count.
    
    YOUR GOAL: Condense qualifying bullets that are too long (>max_bullet_lines) or need reduction for page count.
    This is the ONLY time content removal is allowed. Follow the word removal targets specified for each bullet closely - 
    these are estimates of how many words need to be removed to reduce the bullet from n lines to n-1 lines.
    
    ================================================================================
    CRITICAL CONSTRAINTS (HIGHEST PRIORITY):
    ================================================================================
    
    QUALIFYING BULLETS ONLY:
    - ONLY edit bullets that are listed in qualifying_bullets
    - ALL other bullets must remain EXACTLY unchanged
    - Do NOT edit single-line bullets
    - Bullets qualify if they are:
      * Too long (> max_bullet_lines), OR
      * Resume is over target pages AND bullet is multi-line (2+), OR
      * Resume is at/below target pages AND bullet is multi-line (2+) with low utilization (<15%)
    
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
    
    LaTeX RESTRICTIONS - CRITICAL: ONLY EDIT TEXT CONTENT:
    - ONLY edit the TEXT CONTENT within qualifying bullet points - identify bullets by their structure (they may use \\item, \\resumeItem, or any custom command)
    - DO NOT modify ANY LaTeX commands, environments, or structure - ONLY the text words
    - DO NOT modify: \\begin{}, \\end{}, \\textbf{}, \\item, \\resumeItem, or ANY commands
    - DO NOT modify section structure, formatting, environments, custom commands, or ANY LaTeX structure
    - CRITICAL - COMMAND DEFINITIONS: DO NOT modify ANY command definitions in the preamble:
      * DO NOT modify: \\newcommand{\\command}{...}, \\renewcommand{\\command}{...}, \\providecommand{\\command}{...}
      * DO NOT modify: ANY command definition, including \\contact, \\name, \\resumeItem, or ANY custom command
      * Command definitions (like \\newcommand{\\contact}[1]{...}) must remain EXACTLY as-is - changing them will break LaTeX compilation
      * Example of FORBIDDEN: \\newcommand{\\contact}[1]{...} -> \\newcommand{\\contact}[2]{...} (changed parameter count)
      * Example of FORBIDDEN: \\newcommand{\\contact}[1]{...} -> \\renewcommand{\\contact}[1]{...} (changed command type)
    - ONLY change the actual text words within qualifying bullet point content - preserve ALL LaTeX commands exactly as-is
    - Example: If bullet is "\\item{Built a database system}" -> "\\item{Built a PostgreSQL database}" (removed words, kept \\item{} exactly)
    - Example: If bullet is "\\resumeItem{Built a database system}" -> "\\resumeItem{Built a PostgreSQL database}" (removed words, kept \\resumeItem{} exactly)
    - BAD: "\\item{Built}" -> "\\textbf{\\item{Built}}" (added command - FORBIDDEN)
    - BAD: "\\item{Built}" -> "Built" (removed command - FORBIDDEN)
    - REMEMBER: Different resumes use different bullet commands - work with whatever command is used, but ONLY edit the text content inside it
    
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
    - Preserve ALL LaTeX structure EXACTLY: \\begin{}, \\end{}, \\textbf{}, \\item, \\resumeItem, or ANY commands
    - CRITICAL: NEVER remove or modify \\end{} tags - they MUST remain exactly as-is (e.g., \\end{resume_subsection}, \\end{resume_section}, \\end{subitems})
    - CRITICAL: NEVER uncomment commented sections - if a line starts with %, keep the % exactly as-is
    - CRITICAL: NEVER remove blank lines between sections - preserve all whitespace and line breaks exactly
    - Keep ALL special characters: $|$ (pipe), \\& (ampersand), etc.
    - DO NOT remove LaTeX comments (lines starting with %) - keep the % character exactly as-is
    - DO NOT remove whitespace or reformat LaTeX code
    - DO NOT simplify or "clean up" LaTeX structure
    - CRITICAL - COMMAND DEFINITIONS: DO NOT modify ANY command definitions in the preamble:
      * DO NOT modify: \\newcommand{\\command}{...}, \\renewcommand{\\command}{...}, \\providecommand{\\command}{...}
      * DO NOT modify: ANY command definition, including \\contact, \\name, \\resumeItem, or ANY custom command
      * Command definitions must remain EXACTLY as-is - changing them will break LaTeX compilation with "Illegal parameter number" errors
    - ONLY change the actual text words within qualifying bullet point content - identify bullets by their structure (may use \\item, \\resumeItem, or any custom command)
    - Preserve ALL LaTeX environments, formatting, preamble, custom commands, and structure exactly as-is
    - REMEMBER: Different resumes use different bullet commands - work with whatever command is used, but ONLY edit the text content inside it
    """
    
    resume_latex: str = dspy.InputField(desc="Resume in LaTeX format")
    target_pages: int = dspy.InputField(desc="Target number of pages")
    current_pages: int = dspy.InputField(desc="Current page count")
    qualifying_bullets: str = dspy.InputField(desc="Detailed breakdown of qualifying bullets with their ACTUAL rendered line breaks (showing where LaTeX wraps text). Each bullet shows its multi-line structure with line-by-line text, word counts, and removal targets.")
    optimized_latex: str = dspy.OutputField(desc="Resume with qualifying bullets condensed to n-1 lines. Only qualifying bullets modified. ONLY text content within qualifying bullet points modified (regardless of whether bullets use \\item, \\resumeItem, or any custom command). ALL LaTeX structure, commands, and formatting preserved exactly. Bullet structure preserved - do not combine bullets.")


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
    Phase 2: Bullet Condensation (if needed - for long bullets or page reduction)
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
            max_iterations: Maximum iterations for Phase 2 (bullet condensation) (default: 3).
            target_pages: Target number of pages for the resume (default: 1).
            max_bullet_lines: Maximum lines per bullet point (default: 2).
            job_id: Optional job ID for status updates (only set status to "processing" when work actually starts).
        """
        super().__init__()
        # Use provided values or defaults (no longer fallback to settings since these come from frontend)
        self.max_iterations = max_iterations if max_iterations is not None else 3
        self.target_pages = target_pages if target_pages is not None else 1
        self.max_bullet_lines = max_bullet_lines if max_bullet_lines is not None else 2
        self.job_id = job_id

        # Two separate optimizers for two-phase approach
        # Using ChainOfThought for better quality: improved keyword integration, professional language, and job description alignment
        self.ats_optimizer = dspy.ChainOfThought(OptimizeATSKeywords)
        self.bullet_condenser = dspy.ChainOfThought(CondenseLongBullets)

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
        # Update status to "processing" ONLY when actual work starts (Phase 1 LLM call)
        # This ensures jobs are only marked as processing when actively being worked on
        if self.job_id:
            update_job_status(self.job_id, "processing")
        
        # Phase 1: ATS Keyword Optimization
        phase1_start_memory = _get_memory_mb()
        logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Phase 1 start. Memory: {phase1_start_memory:.1f} MB")
        _log_memory_snapshot("phase1_start", self.job_id)
        
        try:
            logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Calling LLM for Phase 1 ATS optimization...")
            llm_call_start = _get_memory_mb()
            
            ats_result = self.ats_optimizer(
                resume_latex=resume_latex,
                job_description=job_description,
                target_pages=self.target_pages,
            )
            
            llm_call_end = _get_memory_mb()
            logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Phase 1 LLM call completed. Memory: {llm_call_end:.1f} MB (delta: {llm_call_end - llm_call_start:.1f} MB)")
            _log_memory_snapshot("phase1_after_llm", self.job_id)
            
            phase1_latex = _fix_latex_issues(ats_result.optimized_latex)
            after_fix_memory = _get_memory_mb()
            logger.error(f"[DEBUG] [ResumeOptimizerPipeline] After _fix_latex_issues. Memory: {after_fix_memory:.1f} MB")
            
            # Cleanup LLM result object
            del ats_result
            gc.collect()
            
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
            phase1_latex = _fix_latex_issues(phase1_latex)

        # Validate LaTeX structure (only \item content should change)
        structure_valid, structure_error = _validate_latex_structure(phase1_latex, resume_latex)
        if not structure_valid:
            logger.error(f"[Phase 1] LaTeX structure validation failed: {structure_error}")
            logger.error(f"[Phase 1] This is a critical error - the LLM modified LaTeX structure when it should only change \\item content")
            return OptimizationResult(
                success=False,
                original_latex=resume_latex,
                optimized_latex=phase1_latex,
                iterations=1,
                error_message=f"Phase 1 structure validation failed: {structure_error}",
                filename=None,
            )

        # Validate Skills and Education sections unchanged
        skills_preserved = _validate_section_preservation(phase1_latex, resume_latex, "Skills")
        education_preserved = _validate_section_preservation(phase1_latex, resume_latex, "Education")
        
        phase1_compile = compile_latex(phase1_latex)
        phase1_compile_memory = _get_memory_mb()
        if phase1_compile.success and phase1_compile.pdf_bytes:
            pdf_size_mb = len(phase1_compile.pdf_bytes) / 1024 / 1024
            logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Phase 1 compiled. Memory: {phase1_compile_memory:.1f} MB. PDF size: {pdf_size_mb:.1f} MB")
            _log_memory_snapshot("phase1_after_compile", self.job_id)
        else:
            logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Phase 1 compile failed. Memory: {phase1_compile_memory:.1f} MB")
        
        if not phase1_compile.success:
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

        # Phase 2: Bullet Condensation (check if needed)
        phase1_quality = check_quality(
            pdf_bytes=phase1_compile.pdf_bytes,
            target_pages=self.target_pages,
            max_bullet_lines=self.max_bullet_lines,
            latex=phase1_latex,
        )
        
        # Run Phase 2 if: (1) over target pages OR (2) has quality issues (e.g., long bullets)
        if phase1_compile.page_count <= self.target_pages and phase1_quality.passes:
            # Already at target pages and no quality issues - return early
            # Keep PDF bytes for result, but delete from compile result
            pdf_bytes = phase1_compile.pdf_bytes
            del phase1_compile.pdf_bytes
            gc.collect()
            return OptimizationResult(
                success=True,
                original_latex=resume_latex,
                optimized_latex=phase1_latex,
                pdf_bytes=pdf_bytes,
                page_count=phase1_quality.page_count,
                iterations=1,
                error_message=None,
                filename=None,
            )

        # Phase 2: Bullet Condensation
        # Delete Phase 1 PDF bytes - we only need LaTeX (text) for Phase 2
        del phase1_compile.pdf_bytes
        gc.collect()
        
        current_latex = phase1_latex
        current_compile = phase1_compile  # This no longer has pdf_bytes
        last_valid_latex = phase1_latex
        # DO NOT store: last_valid_pdf = phase1_compile.pdf_bytes
        last_quality_result = phase1_quality

        # Phase 2: Bullet Condensation
        phase2_iterations_completed = 0
        for iteration in range(self.max_iterations):
            # Compile current LaTeX to get PDF for analysis
            # Note: On first iteration, current_compile may not have pdf_bytes (deleted after Phase 1)
            if not hasattr(current_compile, 'pdf_bytes') or current_compile.pdf_bytes is None:
                current_compile = compile_latex(current_latex)
                if not current_compile.success:
                    current_latex = _fix_latex_issues(current_latex)
                    current_compile = compile_latex(current_latex)
                    if not current_compile.success:
                        logger.error(f"[Phase 2] Iteration {iteration + 1}: Compilation failed, reverting to last valid")
                        current_latex = last_valid_latex
                        continue
            
            # Get layout analysis
            current_pages = current_compile.page_count
            
            # Get bullets data with utilization calculated
            # Extract bullets and calculate utilization using same logic as analyze_layout
            bullet_metrics = extract_line_metrics(current_compile.pdf_bytes, latex=current_latex)
            bullets_data = bullet_metrics.get("bullets", [])
            
            # Calculate utilization for bullets (same logic as analyze_layout)
            before_doc_memory = _get_memory_mb()
            doc = fitz.open(stream=current_compile.pdf_bytes, filetype="pdf")
            after_doc_open_memory = _get_memory_mb()
            logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Phase 2 iteration {iteration + 1} opened PyMuPDF doc. Memory: {after_doc_open_memory:.1f} MB (delta: {after_doc_open_memory - before_doc_memory:.1f} MB)")
            
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
                del doc  # Explicitly delete doc reference
                after_doc_close_memory = _get_memory_mb()
                logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Phase 2 iteration {iteration + 1} closed PyMuPDF doc. Memory: {after_doc_close_memory:.1f} MB (freed: {after_doc_open_memory - after_doc_close_memory:.1f} MB)")
            
            # CRITICAL: Delete PDF bytes immediately after analysis
            # We only need the metrics, not the PDF bytes
            # Store page count before deleting PDF bytes
            current_pages = current_compile.page_count
            before_delete_memory = _get_memory_mb()
            if current_compile.pdf_bytes:
                pdf_size_mb = len(current_compile.pdf_bytes) / 1024 / 1024
                logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Phase 2 iteration {iteration + 1} deleting PDF. Size: {pdf_size_mb:.1f} MB. Memory before: {before_delete_memory:.1f} MB")
            del current_compile.pdf_bytes
            gc.collect()
            after_delete_memory = _get_memory_mb()
            logger.error(f"[DEBUG] [ResumeOptimizerPipeline] Phase 2 iteration {iteration + 1} after PDF delete. Memory: {after_delete_memory:.1f} MB (freed: {before_delete_memory - after_delete_memory:.1f} MB)")
            
            # Filter qualifying bullets (includes long bullets and page reduction candidates)
            qualifying_bullets_list = _filter_qualifying_bullets(
                {"bullets": bullets_data},
                current_pages=current_pages,
                target_pages=self.target_pages,
                max_bullet_lines=self.max_bullet_lines,
            )
            
            if not qualifying_bullets_list:
                phase2_iterations_completed = iteration + 1
                break
            
            # Format qualifying bullets for LLM with word count targets
            qualifying_bullets_str = _format_qualifying_bullets(
                qualifying_bullets_list,
                current_pages=current_pages,
                target_pages=self.target_pages,
                max_bullet_lines=self.max_bullet_lines,
            )
            
            # Call bullet condenser
            try:
                phase2_result = self.bullet_condenser(
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
                    f"Phase 2 iteration {iteration + 1}: DSPy bullet condenser failed: {error_type}: {error_details}",
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
                current_latex = last_valid_latex
                continue
            
            # Compile and validate
            current_compile = compile_latex(current_latex)
            
            if not current_compile.success:
                current_latex = _fix_latex_issues(current_latex)
                current_compile = compile_latex(current_latex)
                if not current_compile.success:
                    logger.error(f"[Phase 2] Iteration {iteration + 1}: Still failed after fixes, reverting to last valid")
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
                # Keep PDF bytes for result
                pdf_bytes = current_compile.pdf_bytes
                del current_compile.pdf_bytes
                gc.collect()
                return OptimizationResult(
                    success=True,
                    original_latex=resume_latex,
                    optimized_latex=current_latex,
                    pdf_bytes=pdf_bytes,
                    page_count=quality_result.page_count,
                    iterations=iteration + 2,  # Phase 1 (1) + Phase 2 iterations
                    filename=None,
                )
            
            # Store as last valid - ONLY LaTeX, NO PDF bytes!
            # If rollback needed, we can recompile from LaTeX
            last_valid_latex = current_latex
            # DO NOT store: last_valid_pdf = current_compile.pdf_bytes
            last_quality_result = quality_result
            phase2_iterations_completed = iteration + 1
            
            # Delete current PDF bytes before next iteration
            del current_compile.pdf_bytes
            gc.collect()

        # Completed all iterations, performing final compile and quality check
        final_compile = compile_latex(current_latex)
        
        if final_compile.success:
            final_quality = check_quality(
                pdf_bytes=final_compile.pdf_bytes,
                target_pages=self.target_pages,
                max_bullet_lines=self.max_bullet_lines,
                latex=current_latex,
            )
            
            # Keep final PDF bytes for result
            final_pdf_bytes = final_compile.pdf_bytes
            del final_compile.pdf_bytes
            
            # Clean up any remaining references
            if hasattr(current_compile, 'pdf_bytes'):
                del current_compile.pdf_bytes
            
            gc.collect()
            
            return OptimizationResult(
                success=final_quality.passes,
                original_latex=resume_latex,
                optimized_latex=current_latex,
                pdf_bytes=final_pdf_bytes,
                page_count=final_quality.page_count,
                iterations=self.max_iterations + 1,  # Phase 1 (1) + Phase 2 max iterations
                error_message=(
                    f"Quality issues remain after Phase 2: {final_quality.issues_summary}"
                    if not final_quality.passes else None
                ),
                filename=None,
            )
        else:
            # Return last valid version - recompile from LaTeX (no PDF bytes stored)
            # Recompile last valid LaTeX to get PDF bytes for result
            last_valid_compile = compile_latex(last_valid_latex)
            if last_valid_compile.success:
                return OptimizationResult(
                    success=False,
                    original_latex=resume_latex,
                    optimized_latex=last_valid_latex,
                    pdf_bytes=last_valid_compile.pdf_bytes,  # Recompiled, not stored
                    page_count=last_quality_result.page_count if last_quality_result else 0,
                    iterations=self.max_iterations + 1,
                    error_message=f"Final compilation failed: {final_compile.error_message}",
                    filename=None,
                )
            else:
                # Fallback: return without PDF bytes if recompilation fails
                return OptimizationResult(
                    success=False,
                    original_latex=resume_latex,
                    optimized_latex=last_valid_latex,
                    pdf_bytes=None,  # Could not recompile
                    page_count=last_quality_result.page_count if last_quality_result else 0,
                    iterations=self.max_iterations + 1,
                    error_message=(
                        f"Final compilation failed: {final_compile.error_message}. "
                        f"Recompilation of last valid version also failed: {last_valid_compile.error_message}"
                    ),
                    filename=None,
                )


def configure_dspy(
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> None:
    """Configure DSPy with the specified model.
    
    This function is idempotent - if DSPy is already configured, it will not reconfigure.
    This allows it to be called safely in each task execution.

    Args:
        model_name: Model identifier (e.g., "openai/gpt-5-mini").
        api_key: OpenAI API key. If not provided, uses settings.
        max_tokens: Maximum tokens for LLM responses. Defaults to settings.max_tokens.
        temperature: Temperature for generation. Defaults to settings.temperature.
    """
    # Check if DSPy is already configured
    # DSPy stores the LM in dspy.settings.lm - if it exists, we're already configured
    try:
        if hasattr(dspy.settings, 'lm') and dspy.settings.lm is not None:
            return  # Already configured, skip
    except (AttributeError, Exception):
        # If we can't check, proceed with configuration
        pass
    
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
