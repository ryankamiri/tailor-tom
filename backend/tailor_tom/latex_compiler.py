"""LaTeX compilation utilities for TailorTom.

Provides functions to compile LaTeX documents to PDF and extract metadata
like page count for the feedback loop.
"""

import subprocess
import tempfile
import shutil
import glob
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from io import BytesIO

import fitz  # PyMuPDF
from PyPDF2 import PdfReader

from tailor_tom.config import settings


@dataclass
class CompileResult:
    """Result of a LaTeX compilation."""

    success: bool
    pdf_bytes: Optional[bytes] = None
    page_count: int = 0
    error_message: Optional[str] = None
    latex_log: Optional[str] = None
    layout_analysis: Optional[str] = None  # Formatted layout feedback for LLM


def _find_pdflatex() -> Optional[str]:
    """Find pdflatex executable on the system.
    
    Checks PATH first, then common TeX installation locations.
    
    Returns:
        Path to pdflatex executable, or None if not found.
    """
    # Check PATH first
    pdflatex_path = shutil.which("pdflatex")
    if pdflatex_path:
        return pdflatex_path
    
    # Check common macOS TeX paths
    common_paths = [
        "/Library/TeX/texbin/pdflatex",
        "/usr/local/texlive/*/bin/*/pdflatex",
        "/usr/texbin/pdflatex",
    ]
    
    for path_pattern in common_paths:
        if "*" in path_pattern:
            # Handle glob patterns
            matches = glob.glob(path_pattern)
            if matches:
                return matches[0]
        else:
            # Direct path check
            if Path(path_pattern).exists():
                return path_pattern
    
    return None


def _check_pdflatex_available() -> bool:
    """Check if pdflatex is available on the system."""
    return _find_pdflatex() is not None


def compile_latex(
    content: str,
    timeout: Optional[int] = None,
) -> CompileResult:
    """Compile LaTeX content to PDF and return the result.

    Args:
        content: LaTeX document content as a string.
        timeout: Compilation timeout in seconds. Defaults to settings.compile_timeout.

    Returns:
        CompileResult containing PDF bytes, page count, and any errors.
    """
    pdflatex_path = _find_pdflatex()
    if not pdflatex_path:
        return CompileResult(
            success=False,
            error_message=(
                "pdflatex not found in PATH. "
                "Install TeX Live: brew install --cask basictex\n"
                "Then add to PATH: export PATH=\"/Library/TeX/texbin:$PATH\"\n"
                "Or restart your terminal (BasicTeX installer usually does this automatically)."
            ),
        )

    timeout = timeout or settings.compile_timeout

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        tex_path = tmpdir_path / "document.tex"
        pdf_path = tmpdir_path / "document.pdf"
        log_path = tmpdir_path / "document.log"

        # Write LaTeX content to temp file
        tex_path.write_text(content, encoding="utf-8")

        try:
            # Run pdflatex twice to resolve references
            for _ in range(2):
                result = subprocess.run(
                    [
                        pdflatex_path,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-output-directory",
                        str(tmpdir_path),
                        str(tex_path),
                    ],
                    capture_output=True,
                    timeout=timeout,
                    cwd=tmpdir_path,
                )

            # Read log file if it exists
            latex_log = None
            if log_path.exists():
                latex_log = log_path.read_text(encoding="utf-8", errors="ignore")

            # Check if PDF was created
            if not pdf_path.exists():
                error_msg = result.stderr.decode("utf-8", errors="ignore")
                if not error_msg and latex_log:
                    # Extract error from log
                    error_lines = [
                        line for line in latex_log.split("\n") if "!" in line
                    ]
                    error_msg = "\n".join(error_lines) if error_lines else "Unknown compilation error"
                
                return CompileResult(
                    success=False,
                    error_message=error_msg or "PDF not generated",
                    latex_log=latex_log,
                )

            # Read PDF and count pages
            pdf_bytes = pdf_path.read_bytes()
            page_count = _count_pdf_pages(pdf_bytes)

            return CompileResult(
                success=True,
                pdf_bytes=pdf_bytes,
                page_count=page_count,
                latex_log=latex_log,
            )

        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                error_message=f"Compilation timed out after {timeout} seconds",
            )
        except Exception as e:
            return CompileResult(
                success=False,
                error_message=f"Compilation failed: {str(e)}",
            )


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Count the number of pages in a PDF.

    Args:
        pdf_bytes: PDF file content as bytes.

    Returns:
        Number of pages in the PDF.
    """
    try:
        if PdfReader is None:
            raise ImportError("PyPDF2 not available")
        reader = PdfReader(BytesIO(pdf_bytes))
        return len(reader.pages)
    except Exception:
        # Fallback: try to count /Page objects in PDF
        try:
            content = pdf_bytes.decode("latin-1")
            return content.count("/Type /Page") - content.count("/Type /Pages")
        except Exception:
            return 0


def validate_latex(content: str) -> tuple[bool, Optional[str]]:
    """Perform a quick validation of LaTeX syntax.

    This is a lightweight check that doesn't do full compilation.
    It checks for basic structural issues.

    Args:
        content: LaTeX document content.

    Returns:
        Tuple of (is_valid, error_message).
    """
    # Check for document class
    if "\\documentclass" not in content:
        return False, "Missing \\documentclass declaration"

    # Check for begin/end document
    if "\\begin{document}" not in content:
        return False, "Missing \\begin{document}"
    if "\\end{document}" not in content:
        return False, "Missing \\end{document}"

    # Check for balanced braces (simple check)
    open_braces = content.count("{")
    close_braces = content.count("}")
    if open_braces != close_braces:
        return False, f"Unbalanced braces: {open_braces} open, {close_braces} close"

    # Check for balanced begin/end environments
    begins = content.count("\\begin{")
    ends = content.count("\\end{")
    if begins != ends:
        return False, f"Unbalanced environments: {begins} \\begin, {ends} \\end"

    return True, None


def save_pdf(pdf_bytes: bytes, output_path: str | Path) -> None:
    """Save PDF bytes to a file.

    Args:
        pdf_bytes: PDF content as bytes.
        output_path: Path to save the PDF file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)


def save_latex(content: str, output_path: str | Path) -> None:
    """Save LaTeX content to a file.

    Args:
        content: LaTeX document content.
        output_path: Path to save the .tex file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

