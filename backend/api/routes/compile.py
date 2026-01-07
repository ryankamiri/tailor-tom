"""Compile endpoint for compiling LaTeX to PDF."""

import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from tailor_tom.latex_compiler import compile_latex

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for API endpoints
router = APIRouter()


class ValidateRequest(BaseModel):
    """Request model for LaTeX validation."""
    latex: str


class CompileRequest(BaseModel):
    """Request model for general LaTeX compilation."""
    latex: str
    filename: str = "resume.pdf"


@router.post("/compile/validate")
async def validate_latex_compile(request: ValidateRequest):
    """Validate LaTeX by attempting to compile it (without returning PDF).
    
    This endpoint is useful for validating LaTeX syntax before saving,
    without requiring a job ID.
    """
    try:
        compile_result = compile_latex(request.latex)
        
        if not compile_result.success:
            error_msg = compile_result.error_message or "LaTeX compilation failed"
            logger.error(f"LaTeX validation failed: {error_msg}")
            raise HTTPException(
                status_code=400,
                detail=error_msg,
            )
        
        return {"valid": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in validate_latex_compile: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error during validation: {str(e)}",
        )


@router.post("/compile")
async def compile_latex_to_pdf(request: CompileRequest):
    """Compile LaTeX to PDF (general endpoint, no job ID required).
    
    This endpoint is useful for compiling LaTeX that may have been edited
    or when the job no longer exists in the backend.
    """
    try:
        compile_result = compile_latex(request.latex)
        
        if not compile_result.success:
            error_msg = compile_result.error_message or "LaTeX compilation failed"
            logger.error(f"LaTeX compilation failed: {error_msg}")
            raise HTTPException(
                status_code=400,
                detail=error_msg,
            )
        
        # Return PDF as response
        return Response(
            content=compile_result.pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{request.filename}"',
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in compile_latex_to_pdf: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error during compilation: {str(e)}",
        )



