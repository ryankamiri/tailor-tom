"""Pydantic models for API requests and responses."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class OptimizationRequest(BaseModel):
    """Request to create a new optimization job."""
    
    resume_latex: str = Field(..., description="Resume LaTeX source")
    job_description: str = Field(..., description="Job description to optimize for")
    target_pages: int = Field(1, ge=1, le=3, description="Target number of pages")
    first_name: str = Field(..., description="First name for filename generation")
    last_name: str = Field(..., description="Last name for filename generation")
    company_name: str = Field(..., description="Company name for this job application")
    max_iterations: Optional[int] = Field(3, ge=2, le=5, description="Maximum iterations (default: 3, min: 2, max: 5)")
    max_bullet_lines: int = Field(2, ge=1, le=3, description="Maximum lines per bullet point (default: 2, min: 1, max: 3)")


class OptimizationResponse(BaseModel):
    """Response after creating an optimization job."""
    
    job_id: str
    status: str
    created_at: str


class JobStatusResponse(BaseModel):
    """Response for job status check."""
    
    job_id: str
    status: str  # pending, processing, completed, failed
    created_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    company_name: Optional[str] = None
    result: Optional[dict] = None  # {optimized_latex, filename}


class DiffItemChange(BaseModel):
    """Word-level change in a diff item."""
    
    type: str  # removed, added, unchanged
    text: str
    position: int


class DiffItemChanges(BaseModel):
    """Changes in a single item."""
    
    removed_phrases: list[str]
    added_phrases: list[str]
    word_changes: list[DiffItemChange]


class DiffItem(BaseModel):
    """A single item in the diff."""
    
    index: int
    original: dict[str, str]  # {text, latex}
    optimized: dict[str, str]  # {text, latex}
    changes: Optional[DiffItemChanges] = None


class DiffSummary(BaseModel):
    """Summary statistics for the diff."""
    
    total_items: int
    changed_items: int
    original_word_count: int
    optimized_word_count: int
    word_change_percent: float


class DiffResponse(BaseModel):
    """Response for diff endpoint."""
    
    items: list[DiffItem]
    summary: DiffSummary

