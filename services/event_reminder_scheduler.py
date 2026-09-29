from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select

from config import (
    EVENT_REMINDER_POLL_SECONDS,
    EVENT_REMINDERS_ENABLED,
)
from database.db import async_session_maker
from database.models import MiniappEvent, MiniappEventRegistration, MiniappNotification

logger = logging.getLogger(__name__)


def _display_timezone():
    try:
        return ZoneInfo("Europe/Moscow")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=3))


def _day_reminder_window(now: datetime) -> tuple[datetime, datetime] | None:
    """UTC bounds for tomorrow's events once it is 19:00 in Moscow."""
    local_now = now.astimezone(_display_timezone())
    if local_now.time() < time(19):
        return None
    tomorrow = local_now.date() + timedelta(days=1)
    start = datetime.combine(tomorrow, time.min, tzinfo=_display_timezone())
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _reminder_text(event: MiniappEvent, kind: str) -> str:
    starts_at = event.starts_at
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    local_start = starts_at.astimezone(_display_timezone())
    heading = (
        "Завтра состоится мероприятие"
        if kind == "day"
        else "До мероприятия осталось меньше двух часов"
    )
    lines = [
        heading,
        "",
        event.title,
        f"{local_start:%d.%m.%Y в %H:%M} (МСК)",
    ]
    if event.place:
        lines.append(event.place)
    return "\n".join(lines)


async def _send_reminders(
    registrations: list[tuple[MiniappEventRegistration, MiniappEvent]],
    kind: str,
    sent_at: datetime,
) -> int:
    sent = 0
    marker = (
        "in_app_reminder_day_sent_at"
        if kind == "day"
        else "in_app_reminder_two_hours_sent_at"
    )
    async with async_session_maker() as session:
        for registration, event in registrations:
            db_registration = await session.get(MiniappEventRegistration, registration.id)
            if not db_registration or getattr(db_registration, marker):
                continue
            session.add(
                MiniappNotification(
                    event_id=event.id,
                    max_user_id=db_registration.max_user_id,
                    profile_email=db_registration.profile_email,
                    kind=f"reminder_{kind}",
                    event_title=event.title,
                    text=_reminder_text(event, kind),
                )
            )
            setattr(db_registration, marker, sent_at)
            await session.commit()
            sent += 1
    return sent


async def run_event_reminder_job(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    async with async_session_maker() as session:
        base = (
            select(MiniappEventRegistration, MiniappEvent)
            .join(MiniappEvent, MiniappEvent.id == MiniappEventRegistration.event_id)
            .where(
                MiniappEvent.is_active.is_(True),
                MiniappEventRegistration.status == "confirmed",
                or_(
                    MiniappEventRegistration.profile_email.is_not(None),
                    MiniappEventRegistration.max_user_id.is_not(None),
                ),
                MiniappEvent.starts_at.is_not(None),
                MiniappEvent.starts_at > now,
            )
        )
        day_window = _day_reminder_window(now)
        day_rows = []
        if day_window:
            day_rows = (
                await session.execute(
                    base.where(
                        MiniappEvent.starts_at >= day_window[0],
                        MiniappEvent.starts_at < day_window[1],
                        MiniappEventRegistration.in_app_reminder_day_sent_at.is_(None),
                    )
                )
            ).all()
        two_hour_rows = (
            await session.execute(
                base.where(
                    MiniappEvent.starts_at <= now + timedelta(hours=2),
                    MiniappEventRegistration.in_app_reminder_two_hours_sent_at.is_(None),
                )
            )
        ).all()

    day_sent = await _send_reminders(day_rows, "day", now)
    two_hour_sent = await _send_reminders(two_hour_rows, "two_hours", now)
    return {"day": day_sent, "twoHours": two_hour_sent}


async def run_event_reminder_scheduler() -> None:
    if not EVENT_REMINDERS_ENABLED:
        logger.info("Event reminder scheduler is disabled")
        return

    logger.info(
        "Event reminder scheduler enabled: poll every %s seconds",
        EVENT_REMINDER_POLL_SECONDS,
    )
    try:
        while True:
            try:
                result = await run_event_reminder_job()
                if result["day"] or result["twoHours"]:
                    logger.info("Event reminders sent: %s", result)
            except Exception:
                logger.exception("Event reminder scheduler iteration failed")
            await asyncio.sleep(EVENT_REMINDER_POLL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Event reminder scheduler stopped")
        raise
