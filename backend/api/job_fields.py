"""Constants for job data field names in Redis storage.

This module centralizes all field names used for job storage to ensure
consistency across the codebase and make maintenance easier.
"""

# Required fields that must be present when creating a job
# These are verified after job creation to ensure data integrity
JOB_REQUIRED_FIELDS = [
    "job_description",
    "max_bullet_lines",
    "first_name",
    "last_name",
    "original_latex",
]

# Required fields for re-enqueuing orphaned jobs
# These fields are needed to successfully re-enqueue a job after worker restart
JOB_REENQUEUE_REQUIRED_FIELDS = [
    "original_latex",
    "job_description",
    "target_pages",
    "max_bullet_lines",
    "first_name",
    "last_name",
]

# Optional string fields that can be None
# These fields are stored as empty strings in Redis and converted back to None when retrieved
JOB_OPTIONAL_STRING_FIELDS = [
    "result",
    "completed_at",
    "error_message",
    "last_restart_time",
]

# Restart tracking fields
JOB_RESTART_COUNT_FIELD = "restart_count"
JOB_LAST_RESTART_TIME_FIELD = "last_restart_time"

# Redis keys for global job stats (counters)
JOBS_STATS_PROCESSED_KEY = "tailortom:jobs:processed"
JOBS_STATS_COMPLETED_KEY = "tailortom:jobs:completed"
JOBS_STATS_FAILED_KEY = "tailortom:jobs:failed"

