"""Lingxing-first reporting dashboard, rolling metrics, notes, and Word reports."""

from .dashboard_db import DB_PATH, init_dashboard_db

__all__ = ["DB_PATH", "init_dashboard_db"]
