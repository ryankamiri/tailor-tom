"""TailorTom - ATS Resume Optimizer

A DSPy-powered tool to optimize LaTeX resumes for Applicant Tracking Systems.
"""

from tailor_tom.config import settings
from tailor_tom.optimizer import ResumeOptimizerPipeline, OptimizationResult
from tailor_tom.latex_compiler import compile_latex, CompileResult
from tailor_tom.diff_utils import (
    generate_unified_diff,
    generate_pdf_diff_html,
    save_and_open_pdfs_side_by_side,
    generate_pdf_image_comparison_html,
    generate_annotated_pdf_comparison_html,
    create_annotated_diff_pdfs,
)

__version__ = "0.1.0"
__all__ = [
    "settings",
    "ResumeOptimizerPipeline",
    "OptimizationResult",
    "compile_latex",
    "CompileResult",
    "generate_unified_diff",
    "generate_pdf_diff_html",
    "save_and_open_pdfs_side_by_side",
    "generate_pdf_image_comparison_html",
    "generate_annotated_pdf_comparison_html",
    "create_annotated_diff_pdfs",
]

