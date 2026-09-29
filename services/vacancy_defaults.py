"""Shared fallback values for vacancy presentation."""

from __future__ import annotations

DEFAULT_SPHERE = "не указана"
DEFAULT_SALARY = "не указано"
DEFAULT_SCHEDULE = "не указан"
DEFAULT_WORK_FORMAT = "не указан"
DEFAULT_EMPLOYMENT_FORMAT = "не указан"
DEFAULT_DESCRIPTION = "сюда не завезли"
DEFAULT_FEATURE = "Особеная компания для тебя"


def present_value(value: str | None, default: str) -> str:
    """Return a trimmed value or a user-facing fallback."""
    normalized = (value or "").strip()
    return normalized or default


def present_features(*values: str | None) -> list[str]:
    """Return trimmed features or a single default item when all are missing."""
    features = [(value or "").strip() for value in values if (value or "").strip()]
    return features or [DEFAULT_FEATURE]
