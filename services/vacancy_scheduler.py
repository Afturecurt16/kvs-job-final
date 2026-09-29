"""Daily background scheduler for vacancy sync and card generation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from config import (
    VACANCY_SYNC_HOUR,
    VACANCY_SYNC_MINUTE,
    VACANCY_SYNC_SCHEDULE_ENABLED,
    VACANCY_SYNC_TIMEZONE,
)
from database.db import async_session_maker
from database.models import Vacancy, VacancySyncState
from services.google_sheets import sync_vacancies_to_db_with_stats

logger = logging.getLogger(__name__)


MSK_FIXED_TIMEZONE = timezone(timedelta(hours=3), name="MSK")


def get_vacancy_sync_timezone() -> tzinfo:
    """Resolve the configured timezone with a safe fallback."""
    try:
        return ZoneInfo(VACANCY_SYNC_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning(
            "Timezone %r is unavailable. Falling back to fixed MSK (UTC+3).",
            VACANCY_SYNC_TIMEZONE,
        )
        return MSK_FIXED_TIMEZONE


def get_next_vacancy_sync_run(now: datetime, *, hour: int, minute: int) -> datetime:
    """Return the next scheduled run after the given timezone-aware datetime."""
    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_today:
        return scheduled_today
    return scheduled_today + timedelta(days=1)


async def _save_sync_state(status: str, **values) -> None:
    """Persist scheduler state separately from the vacancy transaction."""
    async with async_session_maker() as session:
        state = await session.get(VacancySyncState, 1)
        if state is None:
            state = VacancySyncState(id=1)
            session.add(state)
        state.status = status
        for field, value in values.items():
            setattr(state, field, value)
        await session.commit()


async def run_vacancy_sync_job() -> int:
    """Apply one source snapshot, preserving the current DB on any failure."""
    started_at = datetime.now(timezone.utc)
    await _save_sync_state(
        "syncing",
        started_at=started_at,
        error_message=None,
    )
    logger.info("Starting vacancy sync")

    try:
        async with async_session_maker() as session:
            try:
                stats = await sync_vacancies_to_db_with_stats(session)
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        await _save_sync_state(
            "failed",
            error_message=str(exc)[:2000],
        )
        logger.exception("Vacancy sync failed; previous database snapshot remains active")
        raise

    await _save_sync_state(
        "ready",
        completed_at=datetime.now(timezone.utc),
        error_message=None,
        source_count=stats["source"],
        added_count=stats["added"],
        updated_count=stats["updated"],
        deleted_count=stats["deleted"],
    )
    logger.info("Vacancy sync finished: %s", stats)
    return stats["source"]


async def _database_needs_initial_sync() -> bool:
    async with async_session_maker() as session:
        count = (await session.execute(select(func.count(Vacancy.id)))).scalar() or 0
    return count == 0


async def run_daily_vacancy_sync_scheduler() -> None:
    """Run vacancy sync every day at the configured Moscow time."""
    if not VACANCY_SYNC_SCHEDULE_ENABLED:
        logger.info("Daily vacancy sync scheduler is disabled")
        return

    timezone = get_vacancy_sync_timezone()
    logger.info(
        "Daily vacancy sync scheduler enabled at %02d:%02d (%s)",
        VACANCY_SYNC_HOUR,
        VACANCY_SYNC_MINUTE,
        getattr(timezone, "key", None) or timezone.tzname(None) or str(timezone),
    )

    try:
        # An empty installation is filled in the background. FastAPI and the
        # bot can start accepting requests immediately instead of waiting for
        # Google Sheets and image generation on their critical startup path.
        try:
            if await _database_needs_initial_sync():
                logger.info("Vacancy database is empty; starting background initial sync")
                await run_vacancy_sync_job()
        except Exception:
            logger.exception("Initial vacancy sync failed; scheduler will retry at the next run")

        while True:
            now = datetime.now(timezone)
            next_run = get_next_vacancy_sync_run(
                now,
                hour=VACANCY_SYNC_HOUR,
                minute=VACANCY_SYNC_MINUTE,
            )
            sleep_seconds = max(1.0, (next_run - now).total_seconds())
            logger.info("Next vacancy sync scheduled for %s", next_run.isoformat())
            await asyncio.sleep(sleep_seconds)

            try:
                await run_vacancy_sync_job()
            except Exception:
                logger.exception("Scheduled vacancy sync failed")
    except asyncio.CancelledError:
        logger.info("Daily vacancy sync scheduler stopped")
        raise
