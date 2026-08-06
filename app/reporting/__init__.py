"""Lingxing-first reporting dashboard, targets, notes, and Word reports."""

from .dashboard_db import DB_PATH, init_dashboard_db
from . import targets as _targets
from .target_evaluation import targets_for_period

# Keep the original public import path while using listing-aware evaluation.
_targets.targets_for_period = targets_for_period

__all__ = ["DB_PATH", "init_dashboard_db", "targets_for_period"]
