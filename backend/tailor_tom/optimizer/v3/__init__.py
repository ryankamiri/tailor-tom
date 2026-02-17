"""Optimizer V3: copy-and-extend of V1 with n-candidate generation, two-pass feasibility, and chooser authority."""

from tailor_tom.optimizer.v3.orchestrator import optimize_resume_v3
from tailor_tom.optimizer.v3.types import V3OptimizationResult

__all__ = ["optimize_resume_v3", "V3OptimizationResult"]
