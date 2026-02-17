"""Pydantic models for API requests and responses."""

from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


class OptimizationRequest(BaseModel):
    """Request to create a new optimization job."""
    
    resume_latex: str = Field(..., description="Resume LaTeX source")
    job_description: str = Field(..., description="Job description to optimize for")
    target_pages: int = Field(1, ge=1, le=3, description="Target number of pages")
    first_name: str = Field(..., description="First name for filename generation")
    last_name: str = Field(..., description="Last name for filename generation")
    company_name: str = Field(..., description="Company name for this job application")
    max_iterations: Optional[int] = Field(3, ge=2, le=5, description="Optimization search budget (default: 3, min: 2, max: 5). Controls bundle pool and fine ATS evaluations.")
    max_bullet_lines: int = Field(2, ge=1, le=5, description="Maximum lines per bullet point (default: 2, min: 1, max: 5)")


class OptimizationResponse(BaseModel):
    """Response after creating an optimization job."""
    
    job_id: str
    status: str
    created_at: str


class V3TokenUsage(BaseModel):
    """V3 token and cost usage inside analysis."""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    usage_source: Optional[str] = None  # actual | estimated


class JobDetailAnalysis(BaseModel):
    """V3 analysis payload for job detail (from analysis_json)."""
    passes_done: Optional[int] = None
    quality_passes: Optional[bool] = None
    quality_issues_summary: Optional[str] = None
    diagnostics: Optional[dict[str, Any]] = None
    token_usage: Optional[V3TokenUsage] = None


class JobStatusResponse(BaseModel):
    """Response for job status check (detail view)."""
    
    job_id: str
    status: str  # pending, processing, completed, failed, cancelled
    created_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    company_name: Optional[str] = None
    result: Optional[dict] = None  # {optimized_latex, filename}
    original_latex: Optional[str] = None  # for diff view
    optimizer_version: Optional[int] = None
    llm_prompt_tokens: Optional[int] = None
    llm_completion_tokens: Optional[int] = None
    llm_estimated_cost_usd: Optional[float] = None
    llm_usage_source: Optional[str] = None
    analysis: Optional[JobDetailAnalysis] = None
    analysis_parse_failed: Optional[bool] = None


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

