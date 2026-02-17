"""Diff endpoint for item-level comparison."""

import base64
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from api.models import DiffResponse
from tailor_tom.diff_utils import compute_diff, create_annotated_diff_pdfs
from tailor_tom.latex_compiler import compile_latex

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for API endpoints
router = APIRouter()


class DiffRequest(BaseModel):
    """Request model for general diff endpoint."""
    original_latex: str
    optimized_latex: str


# compute_diff is now imported from tailor_tom.diff_utils


@router.post("/diff", response_model=DiffResponse)
async def compute_latex_diff(request: DiffRequest):
    """Compute diff between two LaTeX strings.
    
    General-purpose endpoint that takes original and optimized LaTeX as input
    and returns the diff. Does not require a job to exist.
    """
    return compute_diff(request.original_latex, request.optimized_latex)


@router.post("/diff-pdfs")
async def get_annotated_diff_pdfs(request: DiffRequest):
    """Generate annotated PDFs with highlighted differences.
    
    Compiles both original and optimized LaTeX to PDFs, then highlights
    the differences. Returns both PDFs as base64-encoded strings.
    """
    try:
        # Compile original LaTeX to PDF
        original_compile = compile_latex(request.original_latex)
        if not original_compile.success:
            error_msg = f"Failed to compile original LaTeX: {original_compile.error_message}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=400,
                detail=error_msg,
            )
        
        # Compile optimized LaTeX to PDF
        optimized_compile = compile_latex(request.optimized_latex)
        if not optimized_compile.success:
            error_msg = f"Failed to compile optimized LaTeX: {optimized_compile.error_message}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=400,
                detail=error_msg,
            )
        
        # Create annotated PDFs with highlights
        annotated_original_bytes, annotated_optimized_bytes = create_annotated_diff_pdfs(
            original_pdf_bytes=original_compile.pdf_bytes,
            optimized_pdf_bytes=optimized_compile.pdf_bytes,
            original_latex=request.original_latex,
            optimized_latex=request.optimized_latex,
        )
        
        # Return both PDFs as base64-encoded strings
        return JSONResponse({
            "original_pdf": base64.b64encode(annotated_original_bytes).decode("utf-8"),
            "optimized_pdf": base64.b64encode(annotated_optimized_bytes).decode("utf-8"),
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in get_annotated_diff_pdfs: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Internal error generating diff PDFs",
        )



