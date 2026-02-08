"""Admin endpoints for viewing and managing saved resumes."""

import logging
import re
import secrets
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from api.resume_storage import list_all_resumes, get_resume, delete_resume
from api.storage import get_job_stats
from tailor_tom.config import settings
from tailor_tom.latex_compiler import compile_latex

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for API endpoints
router = APIRouter()

security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin password.
    
    Args:
        credentials: HTTP Basic Auth credentials
        
    Returns:
        Username (can be any string, password is what matters)
        
    Raises:
        HTTPException: If password is incorrect
    """
    if not settings.admin_password:
        raise HTTPException(
            status_code=500,
            detail="Admin password not configured. Set ADMIN_PASSWORD environment variable.",
        )
    
    # Compare password using constant-time comparison
    is_correct = secrets.compare_digest(credentials.password, settings.admin_password)
    if not is_correct:
        raise HTTPException(
            status_code=401,
            detail="Invalid admin password",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return credentials.username


@router.get("/admin/stats")
async def get_stats(username: str = Depends(verify_admin)):
    """Get global job statistics (admin only).
    
    Returns:
        processed: total jobs that reached a terminal state (completed or failed)
        completed: jobs that completed successfully
        failed: jobs that failed
    """
    try:
        return get_job_stats()
    except Exception as e:
        logger.exception(f"Failed to get job stats: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get job stats: {str(e)}",
        )


@router.get("/admin/resumes")
async def list_resumes(username: str = Depends(verify_admin)):
    """List all saved resumes (admin only).
    
    Returns:
        List of resumes with metadata (resume_id, first_name, last_name, created_at, filename)
    """
    try:
        resumes = list_all_resumes()
        
        # Return only metadata (exclude LaTeX content to reduce payload size)
        resume_list = []
        for resume in resumes:
            resume_list.append({
                "resume_id": resume.get("resume_id"),
                "first_name": resume.get("first_name"),
                "last_name": resume.get("last_name"),
                "created_at": resume.get("created_at"),
                "filename": resume.get("filename"),
            })
        
        return {
            "resumes": resume_list,
            "count": len(resume_list),
        }
    except Exception as e:
        logger.exception(f"Failed to list resumes: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list resumes: {str(e)}",
        )


@router.get("/admin/resumes/{resume_id}")
async def get_resume_detail(
    resume_id: str,
    username: str = Depends(verify_admin),
):
    """Get full resume data including LaTeX (admin only).
    
    Args:
        resume_id: Unique resume identifier
        
    Returns:
        Full resume data including LaTeX content
    """
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Ensure filename is always present - generate if missing
    if not resume.get("filename") or resume.get("filename") == "":
        # Generate filename from resume data
        first_name = resume.get("first_name", "Unknown")
        last_name = resume.get("last_name", "Unknown")
        user_id = resume.get("user_id", resume_id[:8])
        safe_first = re.sub(r'[^\w]', '', first_name).title() if first_name else "Unknown"
        safe_last = re.sub(r'[^\w]', '', last_name).title() if last_name else "Unknown"
        user_id_short = user_id.replace('-', '')[:8] if user_id else resume_id[:8]
        resume["filename"] = f"{safe_first}_{safe_last}_{user_id_short}_resume.pdf"
    
    return resume


@router.get("/admin/resumes/{resume_id}/download")
async def download_resume(
    resume_id: str,
    format: str = Query("pdf", regex="^(pdf|latex)$"),
    username: str = Depends(verify_admin),
):
    """Download a resume as PDF or LaTeX (admin only).
    
    Args:
        resume_id: Unique resume identifier
        format: Download format - "pdf" or "latex" (default: "pdf")
        
    Returns:
        File response with appropriate content type and filename
    """
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    filename_base = resume.get("filename", f"{resume_id}_resume")
    # Remove .pdf extension if present, we'll add the appropriate one
    if filename_base.endswith(".pdf"):
        filename_base = filename_base[:-4]
    
    if format == "pdf":
        # Compile LaTeX to PDF
        latex = resume.get("latex", "")
        if not latex:
            raise HTTPException(
                status_code=500,
                detail="Resume LaTeX content is missing",
            )
        
        compile_result = compile_latex(latex)
        if not compile_result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to compile LaTeX to PDF: {compile_result.error_message}",
            )
        
        filename = f"{filename_base}.pdf"
        return Response(
            content=compile_result.pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    else:  # format == "latex"
        # Return LaTeX file
        latex = resume.get("latex", "")
        if not latex:
            raise HTTPException(
                status_code=500,
                detail="Resume LaTeX content is missing",
            )
        
        filename = f"{filename_base}.tex"
        return Response(
            content=latex,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )


@router.delete("/admin/resumes/{resume_id}")
async def delete_resume_endpoint(
    resume_id: str,
    username: str = Depends(verify_admin),
):
    """Delete a resume from Redis (admin only).
    
    Args:
        resume_id: Unique resume identifier
        
    Returns:
        Success message
    """
    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    deleted = delete_resume(resume_id)
    if not deleted:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete resume",
        )
    
    return {
        "resume_id": resume_id,
        "message": "Resume deleted successfully",
    }

