"""Settings endpoint for saving user resumes."""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.resume_storage import save_user_resume, delete_user_resume, get_resume_by_user_id

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for API endpoints
router = APIRouter()


class SaveResumeRequest(BaseModel):
    """Request model for saving resume from settings."""
    first_name: str
    last_name: str
    user_id: str  # User's unique identifier (UUID)
    latex: str


@router.post("/settings/resume")
async def save_resume_from_settings(request: SaveResumeRequest):
    """Save user's resume LaTeX from settings page to Redis.
    
    This endpoint is called when users save their LaTeX template in the settings page.
    """
    try:
        # Validate that names are provided
        if not request.first_name.strip() or not request.last_name.strip():
            raise HTTPException(
                status_code=400,
                detail="First name and last name are required",
            )
        
        # Validate that user_id is provided
        if not request.user_id.strip():
            raise HTTPException(
                status_code=400,
                detail="User ID is required",
            )
        
        # Validate that LaTeX is provided
        if not request.latex.strip():
            raise HTTPException(
                status_code=400,
                detail="LaTeX content is required",
            )
        
        # Save to Redis
        resume_id = save_user_resume(
            first_name=request.first_name.strip(),
            last_name=request.last_name.strip(),
            user_id=request.user_id.strip(),
            latex=request.latex,
        )
        
        return {
            "success": True,
            "resume_id": resume_id,
            "message": "Resume saved successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to save resume: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save resume: {str(e)}",
        )


class DeleteResumeRequest(BaseModel):
    """Request model for deleting resume from settings."""
    user_id: str  # User's unique identifier (UUID)


@router.delete("/settings/resume")
async def delete_resume_from_settings(request: DeleteResumeRequest):
    """Delete user's resume from Redis.
    
    This endpoint allows users to delete their own resume from the backend.
    The resume is identified by the user_id.
    """
    try:
        # Validate that user_id is provided
        if not request.user_id.strip():
            raise HTTPException(
                status_code=400,
                detail="User ID is required",
            )
        
        # Find resume by user_id
        resume = get_resume_by_user_id(request.user_id.strip())
        if not resume:
            # Resume doesn't exist - return success (idempotent operation)
            return {
                "success": True,
                "message": "Resume deleted successfully (or did not exist)",
            }
        
        # Delete from Redis
        resume_id = resume.get("resume_id")
        if resume_id:
            deleted = delete_user_resume(resume_id)
            if deleted:
                return {
                    "success": True,
                    "message": "Resume deleted successfully from Redis",
                }
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to delete resume from Redis",
                )
        else:
            raise HTTPException(
                status_code=500,
                detail="Resume ID not found",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to delete resume: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete resume: {str(e)}",
        )

