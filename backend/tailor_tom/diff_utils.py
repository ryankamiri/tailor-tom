"""Diff utilities for comparing resume versions.

Provides functions to generate unified diffs and HTML-formatted diffs
for displaying changes between original and optimized resumes.
"""

import base64
import difflib
import logging
import os
import platform
import re
import subprocess
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import fitz  # PyMuPDF
from pdf2image import convert_from_bytes
from PyPDF2 import PdfReader


class DiffChange(NamedTuple):
    """Represents a single change between documents."""

    line_number: int
    change_type: str  # 'added', 'removed', 'modified'
    original_text: str
    modified_text: str


def generate_unified_diff(
    original: str,
    modified: str,
    original_name: str = "original.tex",
    modified_name: str = "optimized.tex",
    context_lines: int = 3,
) -> str:
    """Generate a unified diff between two LaTeX documents.

    Args:
        original: Original document content.
        modified: Modified document content.
        original_name: Label for the original file.
        modified_name: Label for the modified file.
        context_lines: Number of context lines around changes.

    Returns:
        Unified diff as a string.
    """
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=original_name,
        tofile=modified_name,
        n=context_lines,
    )

    return "".join(diff)


def extract_changes(
    original: str,
    modified: str,
) -> List[DiffChange]:
    """Extract a structured list of changes between documents.

    Useful for programmatic analysis of what changed.

    Args:
        original: Original document content.
        modified: Modified document content.

    Returns:
        List of DiffChange objects describing each change.
    """
    changes = []
    original_lines = original.splitlines()
    modified_lines = modified.splitlines()

    matcher = difflib.SequenceMatcher(None, original_lines, modified_lines)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        elif tag == "delete":
            for i in range(i1, i2):
                changes.append(
                    DiffChange(
                        line_number=i + 1,
                        change_type="removed",
                        original_text=original_lines[i],
                        modified_text="",
                    )
                )
        elif tag == "insert":
            for j in range(j1, j2):
                changes.append(
                    DiffChange(
                        line_number=j + 1,
                        change_type="added",
                        original_text="",
                        modified_text=modified_lines[j],
                    )
                )
        elif tag == "replace":
            # Match up lines for replacement
            orig_chunk = original_lines[i1:i2]
            mod_chunk = modified_lines[j1:j2]

            max_len = max(len(orig_chunk), len(mod_chunk))
            for idx in range(max_len):
                orig_text = orig_chunk[idx] if idx < len(orig_chunk) else ""
                mod_text = mod_chunk[idx] if idx < len(mod_chunk) else ""

                if orig_text and mod_text:
                    changes.append(
                        DiffChange(
                            line_number=i1 + idx + 1,
                            change_type="modified",
                            original_text=orig_text,
                            modified_text=mod_text,
                        )
                    )
                elif orig_text:
                    changes.append(
                        DiffChange(
                            line_number=i1 + idx + 1,
                            change_type="removed",
                            original_text=orig_text,
                            modified_text="",
                        )
                    )
                else:
                    changes.append(
                        DiffChange(
                            line_number=j1 + idx + 1,
                            change_type="added",
                            original_text="",
                            modified_text=mod_text,
                        )
                    )

    return changes


def summarize_changes(original: str, modified: str) -> str:
    """Generate a human-readable summary of changes.

    Args:
        original: Original document content.
        modified: Modified document content.

    Returns:
        Summary string describing the changes.
    """
    changes = extract_changes(original, modified)

    added = sum(1 for c in changes if c.change_type == "added")
    removed = sum(1 for c in changes if c.change_type == "removed")
    modified_count = sum(1 for c in changes if c.change_type == "modified")

    original_lines = len(original.splitlines())
    modified_lines = len(modified.splitlines())

    summary = [
        f"📊 Change Summary:",
        f"  • Lines: {original_lines} → {modified_lines} ({modified_lines - original_lines:+d})",
        f"  • Added: {added} lines",
        f"  • Removed: {removed} lines",
        f"  • Modified: {modified_count} lines",
    ]

    # Character count comparison
    orig_chars = len(original)
    mod_chars = len(modified)
    char_diff = mod_chars - orig_chars
    char_pct = (char_diff / orig_chars * 100) if orig_chars > 0 else 0

    summary.append(f"  • Characters: {orig_chars:,} → {mod_chars:,} ({char_pct:+.1f}%)")

    return "\n".join(summary)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text content from a PDF.
    
    Args:
        pdf_bytes: PDF file as bytes.
        
    Returns:
        Extracted text content.
    """
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n".join(text_parts)
    except Exception as e:
        return f"[Error extracting text: {e}]"


def generate_pdf_diff_html(
    original_pdf_bytes: bytes,
    optimized_pdf_bytes: bytes,
    original_label: str = "Original Resume",
    optimized_label: str = "Optimized Resume",
) -> str:
    """Generate a side-by-side HTML diff view of two PDFs.
    
    Similar to the image shown - a clean side-by-side comparison interface.
    
    Args:
        original_pdf_bytes: Original PDF as bytes.
        optimized_pdf_bytes: Optimized PDF as bytes.
        original_label: Label for the original PDF.
        optimized_label: Label for the optimized PDF.
        
    Returns:
        HTML string with side-by-side PDF text comparison.
    """
    # Extract text from both PDFs
    original_text = extract_pdf_text(original_pdf_bytes)
    optimized_text = extract_pdf_text(optimized_pdf_bytes)
    
    # Split into lines for comparison
    original_lines = original_text.splitlines()
    optimized_lines = optimized_text.splitlines()
    
    # Use difflib to find differences
    differ = difflib.SequenceMatcher(None, original_lines, optimized_lines)
    
    # Build HTML with side-by-side view
    html_parts = ["""
    <style>
        .pdf-diff-container {
            display: flex;
            gap: 20px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 12px;
            background-color: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            border-radius: 8px;
        }
        .pdf-diff-panel {
            flex: 1;
            background-color: #252526;
            border: 1px solid #3e3e42;
            border-radius: 4px;
            overflow: hidden;
        }
        .pdf-diff-header {
            background-color: #2d2d30;
            padding: 10px 15px;
            border-bottom: 1px solid #3e3e42;
            font-weight: bold;
            color: #cccccc;
        }
        .pdf-diff-content {
            padding: 15px;
            max-height: 600px;
            overflow-y: auto;
            line-height: 1.6;
            white-space: pre-wrap;
        }
        .pdf-diff-line {
            padding: 2px 4px;
            margin: 1px 0;
        }
        .pdf-diff-line.added {
            background-color: #264f41;
            color: #b5cea8;
        }
        .pdf-diff-line.removed {
            background-color: #5a1d1d;
            color: #f48771;
        }
        .pdf-diff-line.modified {
            background-color: #5a4a1d;
            color: #dcdcaa;
        }
        .pdf-diff-line.unchanged {
            color: #d4d4d4;
        }
        .pdf-diff-line-number {
            display: inline-block;
            width: 40px;
            color: #858585;
            text-align: right;
            margin-right: 10px;
            user-select: none;
        }
    </style>
    <div class="pdf-diff-container">
        <div class="pdf-diff-panel">
            <div class="pdf-diff-header">""" + escape(original_label) + """</div>
            <div class="pdf-diff-content">
    """]
    
    # Original side
    orig_line_num = 1
    for tag, i1, i2, j1, j2 in differ.get_opcodes():
        if tag == 'equal':
            for line in original_lines[i1:i2]:
                html_parts.append(
                    f'<div class="pdf-diff-line unchanged">'
                    f'<span class="pdf-diff-line-number">{orig_line_num}</span>'
                    f'{escape(line)}</div>'
                )
                orig_line_num += 1
        elif tag == 'delete':
            for line in original_lines[i1:i2]:
                html_parts.append(
                    f'<div class="pdf-diff-line removed">'
                    f'<span class="pdf-diff-line-number">{orig_line_num}</span>'
                    f'{escape(line)}</div>'
                )
                orig_line_num += 1
        elif tag == 'replace':
            for line in original_lines[i1:i2]:
                html_parts.append(
                    f'<div class="pdf-diff-line modified">'
                    f'<span class="pdf-diff-line-number">{orig_line_num}</span>'
                    f'{escape(line)}</div>'
                )
                orig_line_num += 1
    
    html_parts.append("""
            </div>
        </div>
        <div class="pdf-diff-panel">
            <div class="pdf-diff-header">""" + escape(optimized_label) + """</div>
            <div class="pdf-diff-content">
    """)
    
    # Optimized side
    opt_line_num = 1
    for tag, i1, i2, j1, j2 in differ.get_opcodes():
        if tag == 'equal':
            for line in optimized_lines[j1:j2]:
                html_parts.append(
                    f'<div class="pdf-diff-line unchanged">'
                    f'<span class="pdf-diff-line-number">{opt_line_num}</span>'
                    f'{escape(line)}</div>'
                )
                opt_line_num += 1
        elif tag == 'insert':
            for line in optimized_lines[j1:j2]:
                html_parts.append(
                    f'<div class="pdf-diff-line added">'
                    f'<span class="pdf-diff-line-number">{opt_line_num}</span>'
                    f'{escape(line)}</div>'
                )
                opt_line_num += 1
        elif tag == 'replace':
            for line in optimized_lines[j1:j2]:
                html_parts.append(
                    f'<div class="pdf-diff-line modified">'
                    f'<span class="pdf-diff-line-number">{opt_line_num}</span>'
                    f'{escape(line)}</div>'
                )
                opt_line_num += 1
    
    html_parts.append("""
            </div>
        </div>
    </div>
    """)
    
    return "".join(html_parts)


def save_and_open_pdfs_side_by_side(
    original_pdf_bytes: bytes,
    optimized_pdf_bytes: bytes,
    output_dir: str = "output",
) -> tuple[str, str]:
    """Save both PDFs and open them for side-by-side comparison.
    
    Args:
        original_pdf_bytes: Original PDF as bytes.
        optimized_pdf_bytes: Optimized PDF as bytes.
        output_dir: Directory to save PDFs.
        
    Returns:
        Tuple of (original_path, optimized_path).
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    original_path = output_path / "original_resume.pdf"
    optimized_path = output_path / "optimized_resume.pdf"
    
    original_path.write_bytes(original_pdf_bytes)
    optimized_path.write_bytes(optimized_pdf_bytes)
    
    # Open both PDFs with system viewer
    system = platform.system()
    
    if system == "Darwin":  # macOS
        # Open both files - Preview can show them side by side
        subprocess.run(["open", str(original_path)], check=False)
        subprocess.run(["open", str(optimized_path)], check=False)
    elif system == "Windows":
        subprocess.run(["start", "", str(original_path)], shell=True, check=False)
        subprocess.run(["start", "", str(optimized_path)], shell=True, check=False)
    else:  # Linux
        subprocess.run(["xdg-open", str(original_path)], check=False)
        subprocess.run(["xdg-open", str(optimized_path)], check=False)
    
    return str(original_path), str(optimized_path)


def generate_pdf_image_comparison_html(
    original_pdf_bytes: bytes,
    optimized_pdf_bytes: bytes,
    dpi: int = 150,
) -> str:
    """Generate HTML with PDF pages rendered as images and color-coded text diff.
    
    Requires pdf2image library: pip install pdf2image
    Also requires poppler: brew install poppler (macOS)
    
    Args:
        original_pdf_bytes: Original PDF as bytes.
        optimized_pdf_bytes: Optimized PDF as bytes.
        dpi: Resolution for rendering.
        
    Returns:
        HTML string with side-by-side image comparison and text diff.
    """
    try:
        # Convert PDFs to images
        original_images = convert_from_bytes(original_pdf_bytes, dpi=dpi)
        optimized_images = convert_from_bytes(optimized_pdf_bytes, dpi=dpi)
        
        # Extract text for diff comparison
        original_text = extract_pdf_text(original_pdf_bytes)
        optimized_text = extract_pdf_text(optimized_pdf_bytes)
        
        # Generate the color-coded text diff
        text_diff_html = _generate_inline_text_diff(original_text, optimized_text)
        
        html_parts = ["""
        <style>
            .pdf-comparison-container {
                background: #1e1e1e;
                padding: 20px;
                border-radius: 8px;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            .pdf-comparison {
                display: flex;
                gap: 20px;
                margin-bottom: 30px;
            }
            .pdf-panel {
                flex: 1;
                background: #252526;
                border: 1px solid #3e3e42;
                border-radius: 4px;
                overflow: hidden;
            }
            .pdf-panel-header {
                background: #2d2d30;
                padding: 10px 15px;
                font-weight: bold;
                color: #cccccc;
                border-bottom: 1px solid #3e3e42;
            }
            .pdf-panel-content {
                padding: 10px;
                text-align: center;
            }
            .pdf-panel-content img {
                max-width: 100%;
                border: 1px solid #3e3e42;
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            }
            .text-diff-section {
                margin-top: 20px;
            }
            .text-diff-header {
                background: #2d2d30;
                padding: 12px 15px;
                font-weight: bold;
                color: #cccccc;
                border-radius: 4px 4px 0 0;
                border: 1px solid #3e3e42;
                border-bottom: none;
            }
            .text-diff-content {
                display: flex;
                border: 1px solid #3e3e42;
                border-radius: 0 0 4px 4px;
                overflow: hidden;
            }
            .diff-panel {
                flex: 1;
                background: #1e1e1e;
                overflow-x: auto;
            }
            .diff-panel:first-child {
                border-right: 2px solid #3e3e42;
            }
            .diff-panel-header {
                background: #252526;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: bold;
                color: #888;
                border-bottom: 1px solid #3e3e42;
            }
            .diff-panel-header.original { color: #f97583; }
            .diff-panel-header.optimized { color: #85e89d; }
            .diff-lines {
                padding: 10px;
                font-family: 'SF Mono', Monaco, 'Courier New', monospace;
                font-size: 11px;
                line-height: 1.5;
                white-space: pre-wrap;
                word-break: break-word;
            }
            .diff-line {
                padding: 2px 8px;
                margin: 1px 0;
                border-radius: 3px;
            }
            .diff-line-number {
                display: inline-block;
                width: 35px;
                color: #6e7681;
                text-align: right;
                margin-right: 10px;
                user-select: none;
            }
            .diff-removed {
                background: rgba(248, 81, 73, 0.15);
                color: #f97583;
            }
            .diff-added {
                background: rgba(63, 185, 80, 0.15);
                color: #85e89d;
            }
            .diff-unchanged {
                color: #c9d1d9;
            }
            .diff-highlight-removed {
                background: rgba(248, 81, 73, 0.4);
                padding: 1px 2px;
                border-radius: 2px;
            }
            .diff-highlight-added {
                background: rgba(63, 185, 80, 0.4);
                padding: 1px 2px;
                border-radius: 2px;
            }
            .diff-legend {
                display: flex;
                gap: 20px;
                padding: 10px 15px;
                background: #252526;
                border-top: 1px solid #3e3e42;
                font-size: 12px;
            }
            .legend-item {
                display: flex;
                align-items: center;
                gap: 6px;
            }
            .legend-color {
                width: 14px;
                height: 14px;
                border-radius: 3px;
            }
            .legend-removed { background: rgba(248, 81, 73, 0.4); }
            .legend-added { background: rgba(63, 185, 80, 0.4); }
        </style>
        <div class="pdf-comparison-container">
            <div class="pdf-comparison">
                <div class="pdf-panel">
                    <div class="pdf-panel-header">📄 Original Resume</div>
                    <div class="pdf-panel-content">
        """]
        
        # Add original PDF pages
        for i, img in enumerate(original_images):
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            html_parts.append(f'<img src="data:image/png;base64,{img_base64}" alt="Original Page {i+1}"><br>')
        
        html_parts.append("""
                    </div>
                </div>
                <div class="pdf-panel">
                    <div class="pdf-panel-header">✨ Optimized Resume</div>
                    <div class="pdf-panel-content">
        """)
        
        # Add optimized PDF pages
        for i, img in enumerate(optimized_images):
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            html_parts.append(f'<img src="data:image/png;base64,{img_base64}" alt="Optimized Page {i+1}"><br>')
        
        html_parts.append(f"""
                    </div>
                </div>
            </div>
            
            <div class="text-diff-section">
                <div class="text-diff-header">📝 Text Changes (Color-Coded Diff)</div>
                {text_diff_html}
                <div class="diff-legend">
                    <div class="legend-item">
                        <div class="legend-color legend-removed"></div>
                        <span style="color: #f97583;">Removed text</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color legend-added"></div>
                        <span style="color: #85e89d;">Added text</span>
                    </div>
                </div>
            </div>
        </div>
        """)
        
        return "".join(html_parts)
        
    except Exception as e:
        return f"""
        <div style="padding: 20px; background: #2d2d30; color: #ff6b6b; border-radius: 8px;">
            <strong>Error rendering PDFs:</strong> {escape(str(e))}<br>
            Make sure poppler is installed: <code>brew install poppler</code> (macOS)
        </div>
        """


def _generate_inline_text_diff(original_text: str, optimized_text: str) -> str:
    """Generate side-by-side HTML diff with line-by-line color coding.
    
    Args:
        original_text: Original text content.
        optimized_text: Modified text content.
        
    Returns:
        HTML string with color-coded diff panels.
    """
    # Split into lines and clean up
    original_lines = original_text.strip().split('\n')
    optimized_lines = optimized_text.strip().split('\n')
    
    # Use difflib to get operations
    matcher = difflib.SequenceMatcher(None, original_lines, optimized_lines)
    
    left_html = []
    right_html = []
    left_line_num = 1
    right_line_num = 1
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Unchanged lines
            for line in original_lines[i1:i2]:
                safe_line = escape(line) if line.strip() else '&nbsp;'
                left_html.append(
                    f'<div class="diff-line diff-unchanged">'
                    f'<span class="diff-line-number">{left_line_num}</span>{safe_line}</div>'
                )
                right_html.append(
                    f'<div class="diff-line diff-unchanged">'
                    f'<span class="diff-line-number">{right_line_num}</span>{safe_line}</div>'
                )
                left_line_num += 1
                right_line_num += 1
                
        elif tag == 'replace':
            # Changed lines - show removed on left, added on right
            # First, add all removed lines
            for line in original_lines[i1:i2]:
                safe_line = escape(line) if line.strip() else '&nbsp;'
                left_html.append(
                    f'<div class="diff-line diff-removed">'
                    f'<span class="diff-line-number">{left_line_num}</span>'
                    f'<span class="diff-highlight-removed">{safe_line}</span></div>'
                )
                left_line_num += 1
            
            # Pad right side with empty lines to align
            for _ in range(i2 - i1):
                right_html.append('<div class="diff-line" style="opacity:0.3;">&nbsp;</div>')
            
            # Then add all new lines
            for line in optimized_lines[j1:j2]:
                safe_line = escape(line) if line.strip() else '&nbsp;'
                right_html.append(
                    f'<div class="diff-line diff-added">'
                    f'<span class="diff-line-number">{right_line_num}</span>'
                    f'<span class="diff-highlight-added">{safe_line}</span></div>'
                )
                right_line_num += 1
            
            # Pad left side with empty lines to align
            for _ in range(j2 - j1):
                left_html.append('<div class="diff-line" style="opacity:0.3;">&nbsp;</div>')
                
        elif tag == 'delete':
            # Lines only in original (removed)
            for line in original_lines[i1:i2]:
                safe_line = escape(line) if line.strip() else '&nbsp;'
                left_html.append(
                    f'<div class="diff-line diff-removed">'
                    f'<span class="diff-line-number">{left_line_num}</span>'
                    f'<span class="diff-highlight-removed">{safe_line}</span></div>'
                )
                right_html.append('<div class="diff-line" style="opacity:0.3;">&nbsp;</div>')
                left_line_num += 1
                
        elif tag == 'insert':
            # Lines only in optimized (added)
            for line in optimized_lines[j1:j2]:
                safe_line = escape(line) if line.strip() else '&nbsp;'
                left_html.append('<div class="diff-line" style="opacity:0.3;">&nbsp;</div>')
                right_html.append(
                    f'<div class="diff-line diff-added">'
                    f'<span class="diff-line-number">{right_line_num}</span>'
                    f'<span class="diff-highlight-added">{safe_line}</span></div>'
                )
                right_line_num += 1
    
    return f"""
    <div class="text-diff-content">
        <div class="diff-panel">
            <div class="diff-panel-header original">− Original</div>
            <div class="diff-lines">{''.join(left_html)}</div>
        </div>
        <div class="diff-panel">
            <div class="diff-panel-header optimized">+ Optimized</div>
            <div class="diff-lines">{''.join(right_html)}</div>
        </div>
    </div>
    """


# =============================================================================
# Improved Diff Algorithm - Comprehensive text extraction and word-level diff
# =============================================================================


def _strip_latex_to_text(latex: str) -> str:
    """Extract ALL text content from LaTeX, removing commands but preserving content.
    
    This is a comprehensive extractor that handles:
    - Section headers
    - Company names, titles, dates
    - Bullet points
    - Skills and other text
    
    Args:
        latex: Raw LaTeX source.
        
    Returns:
        Clean text with all content preserved.
    """
    text = latex
    
    # Remove comments (lines starting with %)
    text = re.sub(r'(?m)^%.*$', '', text)
    text = re.sub(r'(?<!\\)%.*$', '', text, flags=re.MULTILINE)
    
    # Remove preamble (everything before \begin{document})
    if '\\begin{document}' in text:
        text = text.split('\\begin{document}', 1)[1]
    if '\\end{document}' in text:
        text = text.split('\\end{document}', 1)[0]
    
    # Remove common structural commands
    structural_commands = [
        r'\\documentclass\{[^}]*\}',
        r'\\usepackage(?:\[[^\]]*\])?\{[^}]*\}',
        r'\\newlength\{[^}]*\}',
        r'\\setlength\{[^}]*\}\{[^}]*\}',
        r'\\definecolor\{[^}]*\}\{[^}]*\}\{[^}]*\}',
        r'\\hypersetup\{[^}]*\}',
        r'\\pagestyle\{[^}]*\}',
        r'\\thispagestyle\{[^}]*\}',
        r'\\newcommand\{[^}]*\}(?:\[[^\]]*\])?\{[^}]*\}',
        r'\\renewcommand\{[^}]*\}\{[^}]*\}',
        r'\\begin\{[^}]*\}',
        r'\\end\{[^}]*\}',
        r'\\vspace\*?\{[^}]*\}',
        r'\\hspace\*?\{[^}]*\}',
        r'\\vfill',
        r'\\hfill',
        r'\\noindent',
        r'\\centering',
        r'\\raggedright',
        r'\\raggedleft',
        r'\\par\b',
        r'\\\\',  # Line breaks
        r'\\newpage',
        r'\\clearpage',
        r'\\smallskip',
        r'\\medskip',
        r'\\bigskip',
        r'\\item\s*',
        r'\\kill\b',
    ]
    
    for pattern in structural_commands:
        text = re.sub(pattern, ' ', text)
    
    # Extract content from formatting commands (keep the text inside)
    formatting_commands = [
        (r'\\textbf\{([^}]*)\}', r'\1'),
        (r'\\textit\{([^}]*)\}', r'\1'),
        (r'\\underline\{([^}]*)\}', r'\1'),
        (r'\\emph\{([^}]*)\}', r'\1'),
        (r'\\textsc\{([^}]*)\}', r'\1'),
        (r'\\textsf\{([^}]*)\}', r'\1'),
        (r'\\texttt\{([^}]*)\}', r'\1'),
        (r'\\href\{[^}]*\}\{([^}]*)\}', r'\1'),
        (r'\\url\{([^}]*)\}', r'\1'),
        (r'\\section\*?\{([^}]*)\}', r'\1'),
        (r'\\subsection\*?\{([^}]*)\}', r'\1'),
        (r'\\subsubsection\*?\{([^}]*)\}', r'\1'),
    ]
    
    for pattern, replacement in formatting_commands:
        text = re.sub(pattern, replacement, text)
    
    # Handle tabbing environment markers
    text = re.sub(r'\\[=>]', ' ', text)  # \= and \> in tabbing
    text = re.sub(r'\\<', ' ', text)
    text = re.sub(r"\\['`]", '', text)  # Accent commands
    
    # Replace escaped special characters
    text = text.replace('\\&', '&')
    text = text.replace('\\%', '%')
    text = text.replace('\\$', '$')
    text = text.replace('\\#', '#')
    text = text.replace('\\_', '_')
    text = text.replace('\\{', '{')
    text = text.replace('\\}', '}')
    text = text.replace('~', ' ')  # Non-breaking space
    text = text.replace('$|$', '|')  # Pipe in math mode
    
    # Remove any remaining LaTeX commands (single backslash followed by letters)
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\{[^}]*\})*', ' ', text)
    
    # Remove braces
    text = text.replace('{', '').replace('}', '')
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text


def _tokenize_text(text: str) -> List[str]:
    """Tokenize text into words for comparison.
    
    Args:
        text: Text to tokenize.
        
    Returns:
        List of word tokens.
    """
    # Split on whitespace and punctuation, but keep punctuation as separate tokens
    # This helps with more accurate diff
    tokens = re.findall(r'\b\w+\b|[^\w\s]', text)
    return tokens


def _join_tokens_smartly(tokens: List[str]) -> str:
    """Join tokens back into text, handling punctuation spacing correctly.
    
    Args:
        tokens: List of tokens (words and punctuation).
        
    Returns:
        Joined text with correct spacing (no space before punctuation).
    """
    if not tokens:
        return ""
    
    # Punctuation that should NOT have space before OR after (connects words)
    connecting_punct = set(['-', '/'])  # Hyphens and slashes connect words
    
    # Punctuation that should NOT have space before it (most punctuation)
    no_space_before = set([')', ']', '}', ',', '.', ';', ':', '!', '?', '%', "'", '"'])
    # Punctuation that should NOT have space after it (opening brackets)
    no_space_after = set(['(', '[', '{', '/'])  # Slashes also shouldn't have space after
    
    result = []
    for i, token in enumerate(tokens):
        if i == 0:
            result.append(token)
        else:
            prev_token = tokens[i-1]
            # Check if current token is punctuation
            is_punctuation = bool(re.match(r'^[^\w\s]$', token))
            # Check if previous token is punctuation
            prev_is_punctuation = bool(re.match(r'^[^\w\s]$', prev_token))
            
            # Check if previous token is a digit (for numbers like "3,000" or "0.1")
            prev_is_digit = bool(re.match(r'^\d+$', prev_token))
            # Check if current token is a digit
            curr_is_digit = bool(re.match(r'^\d+$', token))
            # Check if current token is a word (for contractions like "Shopify's")
            curr_is_word = bool(re.match(r'^[a-zA-Z]+$', token))
            
            # Determine if we need a space before current token
            need_space = True
            
            if is_punctuation:
                if token in connecting_punct:
                    # Connecting punctuation (hyphens, slashes) - no space before or after
                    need_space = False
                elif token == "'" and prev_token and not prev_is_punctuation:
                    # Apostrophe after a word (e.g., "Shopify's") - no space
                    need_space = False
                elif token in [',', '.'] and prev_is_digit:
                    # Comma or period after a digit (e.g., "3,000" or "0.1") - no space
                    need_space = False
                elif token in no_space_before:
                    # Closing punctuation - no space before
                    need_space = False
                elif token in no_space_after:
                    # Opening brackets can have space before them (but slashes don't)
                    if token == '/':
                        need_space = False
                    else:
                        need_space = True
            
            if prev_is_punctuation:
                if prev_token in connecting_punct:
                    # After connecting punctuation - no space
                    need_space = False
                elif prev_token == "'" and (curr_is_digit or curr_is_word):
                    # Apostrophe before digit or word (e.g., "Shopify's", "don't") - no space
                    need_space = False
                elif prev_token in [',', '.'] and curr_is_digit:
                    # Comma or period before a digit (e.g., "3,000" or "0.1") - no space
                    need_space = False
                elif prev_token in no_space_after:
                    # After opening brackets/quotes/slashes - no space
                    need_space = False
            
            if need_space:
                result.append(' ')
            result.append(token)
    
    joined = ''.join(result)
    # Clean up any double spaces that might have been created
    joined = re.sub(r' +', ' ', joined)
    return joined.strip()


def compute_diff(original_latex: str, optimized_latex: str):
    """Compute diff between two LaTeX strings.
    
    This is a pure function that can be used for any two LaTeX strings.
    Returns a DiffResponse with item-level word changes.
    """
    # Import here to avoid circular imports at module level
    from api.models import DiffResponse, DiffItem, DiffItemChanges, DiffItemChange, DiffSummary
    from tailor_tom.layout_analyzer import extract_items_from_latex
    
    # Extract items from both versions
    original_items = extract_items_from_latex(original_latex)
    optimized_items = extract_items_from_latex(optimized_latex)
    
    item_diffs = []
    
    # Debug logging
    import logging
    logger = logging.getLogger(__name__)
    
    # Match items by content similarity using optimal matching
    # Strategy: Compute all similarities, then match by highest similarity while preferring positional matches
    # when they're reasonably good (within 80% of best match)
    matches = {}  # orig_idx -> (opt_idx, similarity)
    used_opt_indices = set()
    
    # Compute all similarities first
    similarity_matrix = {}  # (orig_idx, opt_idx) -> similarity
    
    for orig_idx, orig_item in enumerate(original_items):
        orig_text = re.sub(r'\s+', ' ', orig_item["text"].strip())
        orig_words = _tokenize_text(orig_text)
        
        for opt_idx, opt_item in enumerate(optimized_items):
            opt_text = re.sub(r'\s+', ' ', opt_item["text"].strip())
            opt_words = _tokenize_text(opt_text)
            
            matcher = difflib.SequenceMatcher(None, orig_words, opt_words)
            similarity = matcher.ratio()
            similarity_matrix[(orig_idx, opt_idx)] = similarity
    
    # Match items optimally: for each original item, find best match
    # Prefer positional matches if they're reasonably good (at least 80% of best match, or best match is poor)
    for orig_idx in range(len(original_items)):
        # Find best match overall
        best_match_idx = None
        best_similarity = 0.0
        
        for opt_idx in range(len(optimized_items)):
            similarity = similarity_matrix.get((orig_idx, opt_idx), 0.0)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match_idx = opt_idx
        
        # Check positional match (same index)
        positional_similarity = similarity_matrix.get((orig_idx, orig_idx), 0.0) if orig_idx < len(optimized_items) else 0.0
        
        # Prefer positional match if:
        # 1. It's reasonably good (> 0.5 to be more conservative)
        # 2. It's significantly better than the best match (at least 0.1 better), OR both are very good (> 0.7)
        # AND the positional index is not already used
        # We're more conservative to avoid incorrect positional matches
        use_positional = False
        if (orig_idx < len(optimized_items) and 
            orig_idx not in used_opt_indices and
            positional_similarity > 0.5 and  # Higher threshold
            (positional_similarity >= best_similarity + 0.1 or (positional_similarity > 0.7 and best_similarity > 0.7))):
            use_positional = True
            matches[orig_idx] = (orig_idx, positional_similarity)
            used_opt_indices.add(orig_idx)
        elif best_similarity > 0.25 and best_match_idx is not None:
            # Use best match, but only if it's not already used
            if best_match_idx not in used_opt_indices:
                matches[orig_idx] = (best_match_idx, best_similarity)
                used_opt_indices.add(best_match_idx)
            else:
                # Best match is already used - check if we should "steal" it
                # Find which original item is currently using it
                current_user = None
                current_user_similarity = 0.0
                for o_idx, (o_opt_idx, o_sim) in matches.items():
                    if o_opt_idx == best_match_idx:
                        current_user = o_idx
                        current_user_similarity = o_sim
                        break
                
                # If our similarity is close to the current user's similarity (within 0.1), consider stealing
                # This handles cases where items are very close in similarity but one is slightly better
                # We're more lenient here because positional matches can be wrong
                should_steal = (current_user is not None and 
                               best_similarity >= current_user_similarity - 0.1 and
                               best_similarity > 0.25)
                
                if should_steal:
                    # Steal the match
                    # Remove old match
                    del matches[current_user]
                    used_opt_indices.remove(best_match_idx)
                    # Assign to current item
                    matches[orig_idx] = (best_match_idx, best_similarity)
                    used_opt_indices.add(best_match_idx)
                    # Now find a new match for the original user
                    best_unused_for_user = None
                    best_unused_sim_for_user = 0.0
                    for opt_idx in range(len(optimized_items)):
                        if opt_idx in used_opt_indices:
                            continue
                        similarity = similarity_matrix.get((current_user, opt_idx), 0.0)
                        if similarity > best_unused_sim_for_user:
                            best_unused_sim_for_user = similarity
                            best_unused_for_user = opt_idx
                    if best_unused_sim_for_user > 0.25 and best_unused_for_user is not None:
                        matches[current_user] = (best_unused_for_user, best_unused_sim_for_user)
                        used_opt_indices.add(best_unused_for_user)
                else:
                    # Don't steal - find best unused match
                    best_unused_idx = None
                    best_unused_similarity = 0.0
                    for opt_idx in range(len(optimized_items)):
                        if opt_idx in used_opt_indices:
                            continue
                        similarity = similarity_matrix.get((orig_idx, opt_idx), 0.0)
                        if similarity > best_unused_similarity:
                            best_unused_similarity = similarity
                            best_unused_idx = opt_idx
                    
                    if best_unused_similarity > 0.25 and best_unused_idx is not None:
                        matches[orig_idx] = (best_unused_idx, best_unused_similarity)
                        used_opt_indices.add(best_unused_idx)
    
    # Now process all matches
    for orig_idx, orig_item in enumerate(original_items):
        orig_text = re.sub(r'\s+', ' ', orig_item["text"].strip())
        
        if orig_idx in matches:
            opt_idx, similarity = matches[orig_idx]
            opt_item = optimized_items[opt_idx]
            opt_text = re.sub(r'\s+', ' ', opt_item["text"].strip())
        else:
            # Original item was deleted - no match in optimized
            opt_item = {"text": "", "latex": ""}
            opt_text = ""
        
        # Process this pair
        if orig_text == opt_text:
            # Unchanged item - add it with no changes
            item_diffs.append(DiffItem(
                index=orig_idx,
                original=orig_item,
                optimized=opt_item,
                changes=None,
            ))
            continue
        
        # Handle deleted items (original exists but optimized doesn't)
        if not opt_text:
            orig_words = _tokenize_text(orig_text)
            word_changes_list = [DiffItemChange(
                type="removed",
                text=_join_tokens_smartly(orig_words),
                position=0,
            )]
            removed_phrases, added_phrases = _get_diff_phrases(orig_text, "")
            changes = DiffItemChanges(
                removed_phrases=removed_phrases,
                added_phrases=added_phrases,
                word_changes=word_changes_list,
            )
            item_diffs.append(DiffItem(
                index=orig_idx,
                original=orig_item,
                optimized=opt_item,
                changes=changes,
            ))
            continue
        
        # Word-level diff
        orig_words = _tokenize_text(orig_text)
        opt_words = _tokenize_text(opt_text)
        
        matcher = difflib.SequenceMatcher(None, orig_words, opt_words)
        
        # Use stored similarity ratio if available (from matching phase), otherwise calculate it
        if orig_idx in matches:
            similarity_ratio = matches[orig_idx][1]
        else:
            similarity_ratio = matcher.ratio()
        
        # If similarity is very low (< 0.3), treat as complete replacement
        # This avoids matching common words that appear in different contexts
        if similarity_ratio < 0.3:
            # Treat as complete replacement: all original is removed, all optimized is added
            word_changes_list: list = [
                DiffItemChange(
                    type="removed",
                    text=_join_tokens_smartly(orig_words),
                    position=0,
                ),
                DiffItemChange(
                    type="added",
                    text=_join_tokens_smartly(opt_words),
                    position=0,
                ),
            ]
        else:
            removed_phrases, added_phrases = _get_diff_phrases(orig_text, opt_text)
            
            # Build word-level changes array
            word_changes_list: list = []
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == 'equal':
                    joined_text = _join_tokens_smartly(orig_words[i1:i2])
                    word_changes_list.append(DiffItemChange(
                        type="unchanged",
                        text=joined_text,
                        position=i1,
                    ))
                elif tag == 'delete':
                    joined_text = _join_tokens_smartly(orig_words[i1:i2])
                    word_changes_list.append(DiffItemChange(
                        type="removed",
                        text=joined_text,
                        position=i1,
                    ))
                elif tag == 'insert':
                    joined_text = _join_tokens_smartly(opt_words[j1:j2])
                    word_changes_list.append(DiffItemChange(
                        type="added",
                        text=joined_text,
                        position=j1,
                    ))
                elif tag == 'replace':
                    removed_joined = _join_tokens_smartly(orig_words[i1:i2])
                    added_joined = _join_tokens_smartly(opt_words[j1:j2])
                    word_changes_list.append(DiffItemChange(
                        type="removed",
                        text=removed_joined,
                        position=i1,
                    ))
                    word_changes_list.append(DiffItemChange(
                        type="added",
                        text=added_joined,
                        position=j1,
                    ))
        
        # Compute phrases for compatibility (needed for DiffItemChanges)
        removed_phrases, added_phrases = _get_diff_phrases(orig_text, opt_text)
        changes = DiffItemChanges(
            removed_phrases=removed_phrases,
            added_phrases=added_phrases,
            word_changes=word_changes_list,
        )
        
        item_diffs.append(DiffItem(
            index=orig_idx,
            original=orig_item,
            optimized=opt_item,
            changes=changes,
        ))
    
    # Handle any remaining optimized items (new items that don't match any original)
    for opt_idx, opt_item in enumerate(optimized_items):
        if opt_idx not in used_opt_indices:
            # New item in optimized version
            orig_item = {"text": "", "latex": ""}
            orig_text = ""
            opt_text = re.sub(r'\s+', ' ', opt_item["text"].strip())
            
            # Add as a new item
            opt_words = _tokenize_text(opt_text)
            word_changes_list = [DiffItemChange(
                type="added",
                text=_join_tokens_smartly(opt_words),
                position=0,
            )]
            removed_phrases, added_phrases = _get_diff_phrases(orig_text, opt_text)
            changes = DiffItemChanges(
                removed_phrases=removed_phrases,
                added_phrases=added_phrases,
                word_changes=word_changes_list,
            )
            item_diffs.append(DiffItem(
                index=len(original_items) + len([d for d in item_diffs if d.index >= len(original_items)]),
                original=orig_item,
                optimized=opt_item,
                changes=changes,
            ))
    
    # Sort by index to maintain order
    item_diffs.sort(key=lambda x: x.index)
    
    # Calculate summary
    original_word_count = sum(len(item["text"].split()) for item in original_items)
    optimized_word_count = sum(len(item["text"].split()) for item in optimized_items)
    word_change_percent = (
        ((optimized_word_count - original_word_count) / original_word_count) * 100
        if original_word_count > 0
        else 0
    )
    
    return DiffResponse(
        items=item_diffs,
        summary=DiffSummary(
            total_items=len(original_items),
            changed_items=sum(1 for item in item_diffs if item.changes is not None),
            original_word_count=original_word_count,
            optimized_word_count=optimized_word_count,
            word_change_percent=round(word_change_percent, 1),
        ),
    )


def _get_diff_phrases(original_text: str, modified_text: str) -> Tuple[List[str], List[str]]:
    """Get phrases that were removed from original and added to modified.
    
    Uses word-level diff on the full text for accuracy.
    
    Args:
        original_text: Original text content.
        modified_text: Modified text content.
        
    Returns:
        Tuple of (removed_phrases, added_phrases).
    """
    original_words = _tokenize_text(original_text)
    modified_words = _tokenize_text(modified_text)
    
    matcher = difflib.SequenceMatcher(None, original_words, modified_words)
    
    removed_phrases = []
    added_phrases = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        elif tag == 'delete':
            phrase = " ".join(original_words[i1:i2])
            phrase = _clean_phrase(phrase)
            if phrase and len(phrase) >= 3:
                removed_phrases.append(phrase)
        elif tag == 'insert':
            phrase = " ".join(modified_words[j1:j2])
            phrase = _clean_phrase(phrase)
            if phrase and len(phrase) >= 3:
                added_phrases.append(phrase)
        elif tag == 'replace':
            removed = " ".join(original_words[i1:i2])
            added = " ".join(modified_words[j1:j2])
            removed = _clean_phrase(removed)
            added = _clean_phrase(added)
            if removed and len(removed) >= 3:
                removed_phrases.append(removed)
            if added and len(added) >= 3:
                added_phrases.append(added)
    
    return removed_phrases, added_phrases


def _clean_phrase(phrase: str) -> str:
    """Clean a phrase for display and searching.
    
    Args:
        phrase: Raw phrase from diff.
        
    Returns:
        Cleaned phrase.
    """
    # Remove leading/trailing punctuation
    phrase = phrase.strip()
    phrase = re.sub(r'^[^\w]+', '', phrase)
    phrase = re.sub(r'[^\w]+$', '', phrase)
    # Normalize internal whitespace
    phrase = re.sub(r'\s+', ' ', phrase)
    return phrase.strip()


def _highlight_in_pdf(doc: fitz.Document, phrase: str, color: Tuple[float, float, float]) -> int:
    """Highlight a phrase in a PDF document with multiple fallback strategies.
    
    Uses multiple search strategies to find text even if formatting differs slightly.
    Searches case-insensitively and handles punctuation variations.
    
    Args:
        doc: PyMuPDF document.
        phrase: Text to highlight.
        color: RGB color tuple (0-1 range).
        
    Returns:
        Number of highlights added.
    """
    if not phrase or len(phrase.strip()) < 2:  # Allow 2+ character phrases
        return 0
    
    count = 0
    phrase = phrase.strip()
    phrase_lower = phrase.lower()
    # Clean phrase for matching (remove punctuation, normalize whitespace)
    phrase_clean = re.sub(r'[^\w\s]', '', phrase_lower)
    phrase_clean = re.sub(r'\s+', ' ', phrase_clean).strip()
    
    for page in doc:
        rects = []
        
        # Strategy 1: Try exact phrase (case-sensitive)
        rects = page.search_for(phrase)
        
        # Strategy 2: Try case-insensitive search by iterating through text spans
        if not rects:
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if "lines" not in block:
                    continue
                for line in block.get("lines", []):
                    if "spans" not in line:
                        continue
                    for span in line.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if not span_text:
                            continue
                        
                        span_text_lower = span_text.lower()
                        span_text_clean = re.sub(r'[^\w\s]', '', span_text_lower)
                        span_text_clean = re.sub(r'\s+', ' ', span_text_clean).strip()
                        
                        # Check if phrase matches this span (exact match or contains)
                        # For single words, do exact word match
                        if len(phrase_clean.split()) == 1:
                            # Single word: check if it matches any word in the span
                            span_words = span_text_clean.split()
                            phrase_word = phrase_clean
                            if phrase_word in span_words:
                                # Found exact word match - get its bbox
                                bbox = span.get("bbox", [])
                                if len(bbox) == 4:
                                    rects.append(fitz.Rect(bbox))
                        else:
                            # Multi-word phrase: check if phrase appears in span text
                            if phrase_clean in span_text_clean:
                                bbox = span.get("bbox", [])
                                if len(bbox) == 4:
                                    rects.append(fitz.Rect(bbox))
        
        # Strategy 3: For multi-word phrases, try searching word-by-word and combining
        if not rects and len(phrase.split()) > 1:
            words = [w.strip() for w in phrase.split() if len(w.strip()) >= 2]
            if words:
                # Try searching for each word and see if we can find them together
                all_word_rects = []
                for word in words:
                    word_rects = page.search_for(word)
                    if word_rects:
                        all_word_rects.extend(word_rects)
                # If we found all words, use the first occurrence of each
                if len(all_word_rects) >= len(words):
                    # Sort by position (top to bottom, left to right)
                    all_word_rects.sort(key=lambda r: (r.y0, r.x0))
                    # Use the first N rects (one per word)
                    rects = all_word_rects[:len(words)]
        
        # Deduplicate rectangles (overlapping)
        seen_rects = []
        for rect in rects:
            is_duplicate = False
            for seen in seen_rects:
                # Check if rectangles overlap significantly (more than 50%)
                intersection = rect & seen
                if intersection.get_area() > 0:
                    # Calculate overlap percentage
                    min_area = min(rect.get_area(), seen.get_area())
                    if min_area > 0:
                        overlap_ratio = intersection.get_area() / min_area
                        if overlap_ratio > 0.5:
                            is_duplicate = True
                            break
            if not is_duplicate:
                seen_rects.append(rect)
        
        # Apply highlights
        for rect in seen_rects:
            try:
                # Only highlight if rectangle has reasonable size
                if rect.width > 0 and rect.height > 0:
                    highlight = page.add_highlight_annot(rect)
                    highlight.set_colors(stroke=color)
                    highlight.update()
                    count += 1
            except Exception:
                pass
    
    return count


def _extract_pdf_text_with_positions(
    spans: List[Dict],
    page: fitz.Page,
) -> Tuple[str, List[Dict]]:
    """Extract text from PDF spans in reading order and build position-to-bbox mapping.
    
    Args:
        spans: List of span dictionaries with "text" and "bbox" keys.
        page: PyMuPDF page object (for reference, not currently used but kept for consistency).
        
    Returns:
        Tuple of (full_text: str, position_map: List[Dict]) where position_map maps
        character positions to bboxes. Each entry in position_map has:
        {
            "start_char": int,  # Starting character position in full_text
            "end_char": int,    # Ending character position (exclusive)
            "bbox": fitz.Rect,  # Bounding box for this text range
        }
    """
    full_text = ""
    position_map = []
    
    # Process spans in order (they should already be in reading order from _fuzzy_match_text_in_pdf)
    for i, span in enumerate(spans):
        span_text = span.get("text", "").strip()
        if not span_text:
            continue
        
        span_bbox_list = span.get("bbox", [])
        if len(span_bbox_list) != 4:
            continue
        
        span_bbox = fitz.Rect(span_bbox_list)
        
        # Add space before span if not first span
        if full_text:
            full_text += " "
        
        start_char = len(full_text)
        full_text += span_text
        end_char = len(full_text)
        
        # Add position mapping for this span
        position_map.append({
            "start_char": start_char,
            "end_char": end_char,
            "bbox": span_bbox,
        })
    
    return full_text, position_map


def _get_bbox_from_position_range(
    start_pos: int,
    end_pos: int,
    position_map: List[Dict],
) -> Optional[fitz.Rect]:
    """Get bounding box for a text range using position map.
    
    Args:
        start_pos: Start character position in full text.
        end_pos: End character position (exclusive) in full text.
        position_map: Position mapping from _extract_pdf_text_with_positions.
        
    Returns:
        Bounding box (fitz.Rect) for the text range, or None if not found.
    """
    if not position_map or start_pos >= end_pos:
        return None
    
    # Find spans that overlap with the position range
    overlapping_rects = []
    
    for pos_entry in position_map:
        pos_start = pos_entry["start_char"]
        pos_end = pos_entry["end_char"]
        pos_bbox = pos_entry["bbox"]
        
        # Check if this position entry overlaps with the requested range
        if start_pos < pos_end and end_pos > pos_start:
            # Calculate the portion of this span that's within the range
            overlap_start = max(start_pos, pos_start)
            overlap_end = min(end_pos, pos_end)
            
            # Calculate how much of this span is included
            span_length = pos_end - pos_start
            if span_length > 0:
                overlap_start_ratio = (overlap_start - pos_start) / span_length
                overlap_end_ratio = (overlap_end - pos_start) / span_length
                
                # Calculate bbox for the overlapping portion
                span_width = pos_bbox.width
                overlap_x0 = pos_bbox.x0 + (overlap_start_ratio * span_width)
                overlap_x1 = pos_bbox.x0 + (overlap_end_ratio * span_width)
                
                overlap_rect = fitz.Rect(overlap_x0, pos_bbox.y0, overlap_x1, pos_bbox.y1)
                overlapping_rects.append(overlap_rect)
    
    if not overlapping_rects:
        return None
    
    # Combine all overlapping rectangles into a single bbox
    if len(overlapping_rects) == 1:
        return overlapping_rects[0]
    
    # Multiple rectangles: only combine if they're on the same line (similar y-coordinates)
    # Group by line (y-coordinate within tolerance)
    line_groups = {}
    y_tolerance = 2.0  # Points - spans on same line should have y within 2pt
    
    for rect in overlapping_rects:
        y_center = (rect.y0 + rect.y1) / 2
        # Find existing line group or create new one
        matched_line = None
        for line_y in line_groups:
            if abs(y_center - line_y) < y_tolerance:
                matched_line = line_y
                break
        
        if matched_line is None:
            matched_line = y_center
            line_groups[matched_line] = []
        
        line_groups[matched_line].append(rect)
    
    # Combine rectangles within each line group, but only if they're close together horizontally
    combined_rects = []
    x_gap_max = 20.0  # Points - max horizontal gap between spans to combine them (conservative to avoid huge bboxes)
    
    for line_rects in line_groups.values():
        if len(line_rects) == 1:
            combined_rects.append(line_rects[0])
        else:
            # Sort by x0 (left to right)
            line_rects_sorted = sorted(line_rects, key=lambda r: r.x0)
            
            # Group rectangles that are close together horizontally
            groups = []
            current_group = [line_rects_sorted[0]]
            
            for rect in line_rects_sorted[1:]:
                # Check if this rect is close to the last rect in current group
                last_rect = current_group[-1]
                gap = rect.x0 - last_rect.x1
                
                if gap <= x_gap_max:
                    # Close enough - add to current group
                    current_group.append(rect)
                else:
                    # Too far - start new group (but we'll only use the first group to avoid huge bboxes)
                    # For now, just add the first group and ignore the rest
                    break
            
            # Only combine the first group (closest rectangles)
            if len(current_group) == 1:
                combined_rects.append(current_group[0])
            else:
                x0 = min(rect.x0 for rect in current_group)
                y0 = min(rect.y0 for rect in current_group)
                x1 = max(rect.x1 for rect in current_group)
                y1 = max(rect.y1 for rect in current_group)
                combined_rects.append(fitz.Rect(x0, y0, x1, y1))
    
    # If we have only one combined rect, return it
    if len(combined_rects) == 1:
        return combined_rects[0]
    elif len(combined_rects) > 1:
        # Multiple separate highlights - return the first one to avoid huge bounding boxes
        # (Ideally we'd return all and create multiple highlights, but for now this prevents the "entire line" issue)
        return combined_rects[0]
    else:
        return None


def _highlight_text_at_position(
    page: fitz.Page,
    start_pos: int,
    end_pos: int,
    position_map: List[Dict],
    color: Tuple[float, float, float],
) -> bool:
    """Highlight text at a specific position range using the position map.
    
    Args:
        page: PyMuPDF page object.
        start_pos: Start character position in full text.
        end_pos: End character position (exclusive) in full text.
        position_map: Position mapping from _extract_pdf_text_with_positions.
        color: RGB color tuple (0-1 range).
        
    Returns:
        True if highlight was added, False otherwise.
    """
    bbox = _get_bbox_from_position_range(start_pos, end_pos, position_map)
    if not bbox:
        return False
    if bbox.width <= 0 or bbox.height <= 0:
        return False
    
    try:
        highlight = page.add_highlight_annot(bbox)
        highlight.set_colors(stroke=color)
        highlight.update()
        return True
    except Exception:
        return False


def create_annotated_diff_pdfs(
    original_pdf_bytes: bytes,
    optimized_pdf_bytes: bytes,
    original_latex: str = None,
    optimized_latex: str = None,
) -> Tuple[bytes, bytes]:
    """Create annotated PDFs highlighting word-level differences.
    
    Uses the text diff results directly (from compute_diff) and maps them onto the PDF.
    Processes word_changes sequentially to match the text diff exactly.
    Only highlights changes in \\item content (since only items can be edited).
    
    Args:
        original_pdf_bytes: Original PDF as bytes.
        optimized_pdf_bytes: Optimized PDF as bytes.
        original_latex: Original LaTeX source (required for accurate item-based diff).
        optimized_latex: Optimized LaTeX source (required for accurate item-based diff).
        
    Returns:
        Tuple of (annotated_original_bytes, annotated_optimized_bytes).
    """
    if not original_latex or not optimized_latex:
        raise ValueError("Both original_latex and optimized_latex must be provided")
    
    # Use compute_diff to get the exact same word-level changes as text diff
    diff_result = compute_diff(original_latex, optimized_latex)
    
    # Open documents
    original_doc = fitz.open(stream=original_pdf_bytes, filetype="pdf")
    optimized_doc = fitz.open(stream=optimized_pdf_bytes, filetype="pdf")
    
    # Colors (RGB, 0-1 range) - toned down for better readability
    RED = (1.0, 0.85, 0.85)    # Softer light red for removed
    GREEN = (0.85, 1.0, 0.85)  # Softer light green for added
    
    from tailor_tom.layout_analyzer import _fuzzy_match_text_in_pdf
    
    # Process each item's diff sequentially
    for item_diff in diff_result.items:
        if not item_diff.changes:
            continue
        
        original_item = item_diff.original
        optimized_item = item_diff.optimized
        original_item_text = original_item.get("text", "")
        optimized_item_text = optimized_item.get("text", "")
        
        if not original_item_text and not optimized_item_text:
            continue
        
        # Find item locations in PDFs
        original_spans = None
        original_page = None
        original_page_num = None
        if original_item_text:
            search_text = original_item_text[:150] if len(original_item_text) > 150 else original_item_text
            original_matches = _fuzzy_match_text_in_pdf(original_doc, search_text, threshold=0.7)
            if original_matches:
                best_match = original_matches[0]
                if best_match.get("similarity", 0) >= 0.7:
                    original_spans = best_match.get("spans", [])
                    original_page_num = best_match.get("page", 0)
                    if original_spans and original_page_num < len(original_doc):
                        original_page = original_doc[original_page_num]
        
        optimized_spans = None
        optimized_page = None
        optimized_page_num = None
        if optimized_item_text:
            search_text = optimized_item_text[:150] if len(optimized_item_text) > 150 else optimized_item_text
            optimized_matches = _fuzzy_match_text_in_pdf(optimized_doc, search_text, threshold=0.7)
            if optimized_matches:
                best_match = optimized_matches[0]
                if best_match.get("similarity", 0) >= 0.7:
                    optimized_spans = best_match.get("spans", [])
                    optimized_page_num = best_match.get("page", 0)
                    if optimized_spans and optimized_page_num < len(optimized_doc):
                        optimized_page = optimized_doc[optimized_page_num]
        
        # Extract PDF text with position mapping
        original_text = ""
        original_pos_map = []
        if original_spans and original_page:
            original_text, original_pos_map = _extract_pdf_text_with_positions(original_spans, original_page)
        
        optimized_text = ""
        optimized_pos_map = []
        if optimized_spans and optimized_page:
            optimized_text, optimized_pos_map = _extract_pdf_text_with_positions(optimized_spans, optimized_page)
        
        # Process word_changes sequentially - just map the text diffs onto the PDF
        orig_pos = 0
        opt_pos = 0
        
        for idx, word_change in enumerate(item_diff.changes.word_changes):
            change_text = word_change.text.strip()
            if not change_text:
                continue
            
            if word_change.type == "removed":
                if not original_text or not original_page:
                    continue
                
                # Build simple regex pattern: escape text and allow flexible whitespace
                pattern = re.escape(change_text).replace(r'\ ', r'\s+')
                
                # Search sequentially from current position
                search_text = original_text[orig_pos:]
                match = re.search(pattern, search_text, re.IGNORECASE)
                if match:
                    match_pos = orig_pos + match.start()
                    match_end = orig_pos + match.end()
                    _highlight_text_at_position(original_page, match_pos, match_end, original_pos_map, RED)
                    orig_pos = match_end
                else:
                    orig_pos = min(orig_pos + len(change_text), len(original_text))
            
            elif word_change.type == "added":
                if not optimized_text or not optimized_page:
                    continue
                
                # Build simple regex pattern: escape text and allow flexible whitespace
                pattern = re.escape(change_text).replace(r'\ ', r'\s+')
                
                # Search sequentially from current position
                search_text = optimized_text[opt_pos:]
                match = re.search(pattern, search_text, re.IGNORECASE)
                if match:
                    match_pos = opt_pos + match.start()
                    match_end = opt_pos + match.end()
                    _highlight_text_at_position(optimized_page, match_pos, match_end, optimized_pos_map, GREEN)
                    opt_pos = match_end
                else:
                    opt_pos = min(opt_pos + len(change_text), len(optimized_text))
            
            elif word_change.type == "unchanged":
                # Advance positions by finding the text sequentially
                if original_text and orig_pos < len(original_text):
                    pattern = re.escape(change_text).replace(r'\ ', r'\s+')
                    match = re.search(pattern, original_text[orig_pos:], re.IGNORECASE)
                    if match:
                        orig_pos = orig_pos + match.end()
                    else:
                        orig_pos = min(orig_pos + len(change_text), len(original_text))
                
                if optimized_text and opt_pos < len(optimized_text):
                    pattern = re.escape(change_text).replace(r'\ ', r'\s+')
                    match = re.search(pattern, optimized_text[opt_pos:], re.IGNORECASE)
                    if match:
                        opt_pos = opt_pos + match.end()
                    else:
                        opt_pos = min(opt_pos + len(change_text), len(optimized_text))
    
    # Save
    original_annotated = original_doc.tobytes()
    optimized_annotated = optimized_doc.tobytes()
    
    original_doc.close()
    optimized_doc.close()
    
    return original_annotated, optimized_annotated


def generate_annotated_pdf_comparison_html(
    original_pdf_bytes: bytes,
    optimized_pdf_bytes: bytes,
    original_latex: str = None,
    optimized_latex: str = None,
    dpi: int = 150,
) -> str:
    """Generate HTML with annotated PDFs showing diff highlights.
    
    Creates annotated PDFs with:
    - Red highlights on original for removed/changed text
    - Green highlights on optimized for added/changed text
    
    Then renders them as images for side-by-side comparison.
    
    Args:
        original_pdf_bytes: Original PDF as bytes.
        optimized_pdf_bytes: Optimized PDF as bytes.
        original_latex: Original LaTeX source (for accurate diff).
        optimized_latex: Optimized LaTeX source (for accurate diff).
        dpi: Resolution for rendering.
        
    Returns:
        HTML string with side-by-side annotated PDF comparison.
    """
    try:
        # Create annotated PDFs (use LaTeX source for accurate comparison)
        annotated_original, annotated_optimized = create_annotated_diff_pdfs(
            original_pdf_bytes, optimized_pdf_bytes,
            original_latex=original_latex,
            optimized_latex=optimized_latex,
        )
        
        # Convert annotated PDFs to images
        original_images = convert_from_bytes(annotated_original, dpi=dpi)
        optimized_images = convert_from_bytes(annotated_optimized, dpi=dpi)
        
        html_parts = ["""
        <style>
            .annotated-pdf-container {
                background: #1e1e1e;
                padding: 20px;
                border-radius: 8px;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            .annotated-pdf-header {
                text-align: center;
                color: #cccccc;
                margin-bottom: 15px;
                font-size: 14px;
            }
            .annotated-pdf-comparison {
                display: flex;
                gap: 20px;
            }
            .annotated-pdf-panel {
                flex: 1;
                background: #252526;
                border: 1px solid #3e3e42;
                border-radius: 4px;
                overflow: hidden;
            }
            .annotated-pdf-panel-header {
                padding: 12px 15px;
                font-weight: bold;
                border-bottom: 1px solid #3e3e42;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .annotated-pdf-panel-header.original {
                background: linear-gradient(90deg, rgba(248,81,73,0.2) 0%, #2d2d30 100%);
                color: #f97583;
            }
            .annotated-pdf-panel-header.optimized {
                background: linear-gradient(90deg, rgba(63,185,80,0.2) 0%, #2d2d30 100%);
                color: #85e89d;
            }
            .annotated-pdf-panel-content {
                padding: 10px;
                text-align: center;
                background: #1e1e1e;
            }
            .annotated-pdf-panel-content img {
                max-width: 100%;
                border: 1px solid #3e3e42;
                box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            }
            .annotated-pdf-legend {
                display: flex;
                justify-content: center;
                gap: 30px;
                padding: 15px;
                background: #252526;
                border-radius: 4px;
                margin-top: 15px;
            }
            .legend-item {
                display: flex;
                align-items: center;
                gap: 8px;
                color: #cccccc;
                font-size: 13px;
            }
            .legend-swatch {
                width: 20px;
                height: 14px;
                border-radius: 2px;
                border: 1px solid rgba(255,255,255,0.2);
            }
            .legend-swatch.removed {
                background: rgba(255, 200, 200, 0.9);
            }
            .legend-swatch.added {
                background: rgba(200, 255, 200, 0.9);
            }
        </style>
        <div class="annotated-pdf-container">
            <div class="annotated-pdf-header">
                📊 Annotated PDF Comparison — Highlights show text differences
            </div>
            <div class="annotated-pdf-comparison">
                <div class="annotated-pdf-panel">
                    <div class="annotated-pdf-panel-header original">
                        <span>📄</span> Original Resume
                        <span style="font-weight: normal; font-size: 12px; opacity: 0.7;">(removed text highlighted)</span>
                    </div>
                    <div class="annotated-pdf-panel-content">
        """]
        
        # Add original PDF pages
        for i, img in enumerate(original_images):
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            html_parts.append(f'<img src="data:image/png;base64,{img_base64}" alt="Original Page {i+1}"><br>')
        
        html_parts.append("""
                    </div>
                </div>
                <div class="annotated-pdf-panel">
                    <div class="annotated-pdf-panel-header optimized">
                        <span>✨</span> Optimized Resume
                        <span style="font-weight: normal; font-size: 12px; opacity: 0.7;">(added text highlighted)</span>
                    </div>
                    <div class="annotated-pdf-panel-content">
        """)
        
        # Add optimized PDF pages
        for i, img in enumerate(optimized_images):
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            html_parts.append(f'<img src="data:image/png;base64,{img_base64}" alt="Optimized Page {i+1}"><br>')
        
        html_parts.append("""
                    </div>
                </div>
            </div>
            <div class="annotated-pdf-legend">
                <div class="legend-item">
                    <div class="legend-swatch removed"></div>
                    <span>Removed / Changed text (in original)</span>
                </div>
                <div class="legend-item">
                    <div class="legend-swatch added"></div>
                    <span>Added / Changed text (in optimized)</span>
                </div>
            </div>
        </div>
        """)
        
        return "".join(html_parts)
        
    except Exception as e:
        return f"""
        <div style="padding: 20px; background: #2d2d30; color: #ff6b6b; border-radius: 8px;">
            <strong>Error creating annotated PDFs:</strong> {escape(str(e))}<br>
            Make sure pymupdf and poppler are installed.
        </div>
        """

