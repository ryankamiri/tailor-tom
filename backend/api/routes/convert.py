"""Convert endpoint for DOCX to LaTeX conversion.

POST /api/convert/docx  -- validate, extract content, enqueue, return conversion_id
GET  /api/convert/docx/{conversion_id}  -- poll for result
"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File

from api.conversion_storage import CONVERSION_KEY_PREFIX, CONVERSION_TTL, get_redis_client
from api.db_models import User
from api.deps import get_optional_current_user
from worker.tasks import convert_docx_task
from tailor_tom.docx_converter import extract_content_from_docx

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for API endpoints
router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/convert/docx", status_code=202)
async def start_docx_conversion(
    file: UploadFile = File(...),
    target_pages: int = Form(1),
    current_user: User | None = Depends(get_optional_current_user),
):
    """Start a DOCX-to-LaTeX conversion job.

    Validates the file, extracts structured content (fast), stores it in
    Redis, and enqueues a Celery task on the dedicated ``docx`` queue.
    Returns immediately with a ``conversion_id`` for polling.
    """
    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="File must be a .docx file")

    # Read and validate file size
    docx_bytes = await file.read()
    if len(docx_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds maximum of {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )
    if len(docx_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Extract structured content synchronously (fast, ~50ms) so we can
    # validate up-front and avoid storing large docx bytes in Redis.
    try:
        structured_content = extract_content_from_docx(docx_bytes)
    except Exception as e:
        logger.exception("Failed to extract content from .docx: %s", e)
        raise HTTPException(status_code=400, detail="Failed to parse .docx file")

    if not structured_content.get("elements"):
        raise HTTPException(status_code=400, detail="No content found in .docx file")

    # Generate a conversion id
    conversion_id = uuid.uuid4().hex[:16]

    # Store structured content in Redis for the worker to pick up
    rc = get_redis_client()
    payload = json.dumps({
        "status": "pending",
        "structured_content": structured_content,
        "target_pages": target_pages,
        "user_id": str(current_user.id) if current_user else None,
        "user_email": current_user.email if current_user else None,
        "user_first_name": current_user.first_name if current_user else None,
        "user_last_name": current_user.last_name if current_user else None,
    })
    rc.setex(f"{CONVERSION_KEY_PREFIX}{conversion_id}", CONVERSION_TTL, payload)

    # Enqueue conversion task (same queue as optimization; priority=0 so DOCX runs first)
    try:
        convert_docx_task.apply_async(
            kwargs={"conversion_id": conversion_id},
            priority=0,  # highest priority so DOCX is picked before pending optimizations
        )
    except Exception as e:
        logger.exception("Failed to enqueue DOCX conversion: %s", e)
        raise HTTPException(status_code=500, detail="Failed to start conversion")

    return {"conversion_id": conversion_id}


@router.get("/convert/docx/{conversion_id}")
async def get_docx_conversion_status(conversion_id: str):
    """Poll for DOCX conversion result.

    Returns:
        - ``{"status": "pending"}``
        - ``{"status": "processing"}``
        - ``{"status": "completed", "latex": "...", "compiled_pdf": "..."}``
        - ``{"status": "failed", "error_message": "..."}``
    """
    rc = get_redis_client()
    raw = rc.get(f"{CONVERSION_KEY_PREFIX}{conversion_id}")

    if not raw:
        raise HTTPException(status_code=404, detail="Conversion not found or expired")

    data: dict = json.loads(raw)
    status = data.get("status", "pending")

    if status == "completed":
        return {
            "status": "completed",
            "latex": data.get("latex", ""),
            "compiled_pdf": data.get("compiled_pdf", ""),
        }

    if status == "failed":
        return {
            "status": "failed",
            "error_message": data.get("error_message", "Conversion failed"),
        }

    # pending or processing
    return {"status": status}
