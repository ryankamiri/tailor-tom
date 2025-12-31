"""Redis-based resume storage for user templates."""

import json
import logging
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from api.storage import get_redis_client

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors


def _get_resume_key(resume_id: str) -> str:
    """Get Redis key for a resume."""
    return f"resume:{resume_id}"


def _generate_resume_id(first_name: str, last_name: str, user_id: str) -> str:
    """Generate resume ID from firstname_lastname_useruuid.
    
    Args:
        first_name: User's first name
        last_name: User's last name
        user_id: User's unique identifier (UUID)
        
    Returns:
        Resume ID string: firstname_lastname_useruuid
    """
    # Clean names (remove special chars, lowercase)
    first_clean = re.sub(r'[^\w]', '', first_name).lower() if first_name else "unknown"
    last_clean = re.sub(r'[^\w]', '', last_name).lower() if last_name else "unknown"
    
    # Remove hyphens from user_id for cleaner ID
    user_id_clean = user_id.replace('-', '')
    
    return f"{first_clean}_{last_clean}_{user_id_clean}"


def _generate_filename(first_name: str, last_name: str, user_id: str) -> str:
    """Generate filename in format FIRSTNAME_LASTNAME_UUID_resume.pdf.
    
    Args:
        first_name: User's first name
        last_name: User's last name
        user_id: User's unique identifier (UUID)
        
    Returns:
        Filename string in Title_Case format
    """
    # Clean names for filename (remove special chars, title case)
    first_clean = re.sub(r'[^\w]', '', first_name).title() if first_name else "Unknown"
    last_clean = re.sub(r'[^\w]', '', last_name).title() if last_name else "Unknown"
    
    # Use first 8 chars of user_id for shorter filename
    user_id_short = user_id.replace('-', '')[:8]
    
    return f"{first_clean}_{last_clean}_{user_id_short}_resume.pdf"


def save_user_resume(first_name: str, last_name: str, user_id: str, latex: str) -> str:
    """Save user's resume LaTeX to Redis.
    
    Uses firstname_lastname_useruuid as the resume_id, ensuring one resume per user.
    Latest save overwrites previous resume for the same user.
    
    Args:
        first_name: User's first name
        last_name: User's last name
        user_id: User's unique identifier (UUID)
        latex: LaTeX content of the resume
        
    Returns:
        resume_id: Unique identifier for the saved resume (firstname_lastname_useruuid)
    """
    client = get_redis_client()
    
    # Generate resume ID from user identity (ensures one resume per user)
    resume_id = _generate_resume_id(first_name, last_name, user_id)
    key = _get_resume_key(resume_id)
    
    # Generate filename
    filename = _generate_filename(first_name, last_name, user_id)
    
    # Prepare data
    created_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    resume_data = {
        "resume_id": resume_id,
        "user_id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        "latex": latex,
        "created_at": created_at,
        "filename": filename,
    }
    
    # Store as hash (no TTL - these are user templates, keep until admin deletes)
    # Using hset will overwrite if resume_id already exists (one resume per user)
    client.hset(key, mapping=resume_data)
    
    return resume_id


def get_resume(resume_id: str) -> Optional[Dict[str, Any]]:
    """Get a resume from Redis by ID.
    
    Args:
        resume_id: Unique resume identifier
        
    Returns:
        Resume data dictionary or None if not found
    """
    client = get_redis_client()
    key = _get_resume_key(resume_id)
    
    resume_data = client.hgetall(key)
    if not resume_data:
        return None
    
    return resume_data


def list_all_resumes() -> List[Dict[str, Any]]:
    """List all saved resumes from Redis.
    
    Returns:
        List of resume dictionaries, sorted by created_at (newest first)
    """
    client = get_redis_client()
    
    # Scan for all resume keys
    resumes = []
    cursor = 0
    
    while True:
        cursor, keys = client.scan(cursor, match="resume:*", count=100)
        for key in keys:
            resume_data = client.hgetall(key)
            if resume_data:
                resumes.append(resume_data)
        if cursor == 0:
            break
    
    # Sort by created_at (newest first)
    resumes.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return resumes


def get_resume_by_user_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get a resume by user_id.
    
    Args:
        user_id: User's unique identifier (UUID)
        
    Returns:
        Resume data dictionary or None if not found
    """
    client = get_redis_client()
    
    # Scan for resume with matching user_id
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor, match="resume:*", count=100)
        for key in keys:
            resume_data = client.hgetall(key)
            if resume_data.get("user_id") == user_id:
                return resume_data
        if cursor == 0:
            break
    
    return None


def delete_resume(resume_id: str) -> bool:
    """Delete a resume from Redis.
    
    Args:
        resume_id: Unique resume identifier
        
    Returns:
        True if resume was deleted, False if it didn't exist
    """
    client = get_redis_client()
    key = _get_resume_key(resume_id)
    
    deleted = client.delete(key)
    return deleted > 0


def delete_user_resume(resume_id: str) -> bool:
    """Delete a resume from Redis (alias for delete_resume for clarity).
    
    Args:
        resume_id: Unique resume identifier
        
    Returns:
        True if resume was deleted, False if it didn't exist
    """
    return delete_resume(resume_id)

