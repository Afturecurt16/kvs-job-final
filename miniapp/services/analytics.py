from __future__ import annotations

import csv
import io
from datetime import datetime, time, timedelta

from sqlalchemy import Date, String, case, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import MiniappAction


def _period_start(days: int) -> datetime:
    first_day = datetime.utcnow().date() - timedelta(days=days - 1)
    return datetime.combine(first_day, time.min)


def _identity_expression():
    return case(
        (
            MiniappAction.max_user_id.is_not(None),
            func.concat("max:", cast(MiniappAction.max_user_id, String)),
        ),
        else_=func.concat("session:", MiniappAction.session_id),
    )


async def build_metrics_dashboard(session: AsyncSession, days: int) -> dict:
    start = _period_start(days)
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    identity = _identity_expression()
    period_filter = MiniappAction.created_at >= start

    summary_row = (
        await session.execute(
            select(
                func.count(MiniappAction.id).label("events"),
                func.count(MiniappAction.id)
                .filter(MiniappAction.event_type == "click")
                .label("clicks"),
                func.count(MiniappAction.id)
                .filter(MiniappAction.event_type == "page_view")
                .label("page_views"),
                func.count(func.distinct(identity)).label("unique_users"),
            ).where(period_filter)
        )
    ).one()

    active_today = (
        await session.execute(
            select(func.count(func.distinct(identity))).where(
                MiniappAction.created_at >= today_start
            )
        )
    ).scalar_one()

    day_value = cast(MiniappAction.created_at, Date).label("day")
    daily_rows = (
        await session.execute(
            select(
                day_value,
                func.count(MiniappAction.id).label("events"),
                func.count(MiniappAction.id)
                .filter(MiniappAction.event_type == "click")
                .label("clicks"),
                func.count(func.distinct(identity)).label("users"),
            )
            .where(period_filter)
            .group_by(day_value)
            .order_by(day_value)
        )
    ).all()
    daily_map = {
        row.day: {"events": row.events, "clicks": row.clicks, "users": row.users}
        for row in daily_rows
    }
    daily = []
    for offset in range(days):
        current = start.date() + timedelta(days=offset)
        values = daily_map.get(current, {"events": 0, "clicks": 0, "users": 0})
        daily.append({"date": current.isoformat(), **values})

    top_actions = (
        await session.execute(
            select(MiniappAction.action, func.count(MiniappAction.id).label("count"))
            .where(period_filter, MiniappAction.event_type == "click")
            .group_by(MiniappAction.action)
            .order_by(desc("count"), MiniappAction.action)
            .limit(8)
        )
    ).all()
    top_routes = (
        await session.execute(
            select(MiniappAction.route, func.count(MiniappAction.id).label("count"))
            .where(period_filter, MiniappAction.event_type == "page_view")
            .group_by(MiniappAction.route)
            .order_by(desc("count"), MiniappAction.route)
            .limit(8)
        )
    ).all()
    top_targets = (
        await session.execute(
            select(MiniappAction.target, func.count(MiniappAction.id).label("count"))
            .where(
                period_filter,
                MiniappAction.event_type == "click",
                MiniappAction.target.is_not(None),
                MiniappAction.target != "",
            )
            .group_by(MiniappAction.target)
            .order_by(desc("count"), MiniappAction.target)
            .limit(8)
        )
    ).all()

    unique_users = int(summary_row.unique_users or 0)
    clicks = int(summary_row.clicks or 0)
    return {
        "days": days,
        "generatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "summary": {
            "events": int(summary_row.events or 0),
            "clicks": clicks,
            "pageViews": int(summary_row.page_views or 0),
            "uniqueUsers": unique_users,
            "activeToday": int(active_today or 0),
            "clicksPerUser": round(clicks / unique_users, 1) if unique_users else 0,
        },
        "daily": daily,
        "topActions": [{"label": row.action, "count": row.count} for row in top_actions],
        "topRoutes": [{"label": row.route, "count": row.count} for row in top_routes],
        "topTargets": [{"label": row.target, "count": row.count} for row in top_targets],
    }


async def export_metrics_csv(session: AsyncSession, days: int) -> bytes:
    rows = (
        await session.execute(
            select(MiniappAction)
            .where(MiniappAction.created_at >= _period_start(days))
            .order_by(MiniappAction.created_at.desc(), MiniappAction.id.desc())
        )
    ).scalars().all()

    def csv_safe(value) -> str:
        text = str(value or "")
        return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text

    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Дата и время",
            "Тип события",
            "Действие",
            "Экран",
            "Цель",
            "MAX ID",
            "ID сессии",
        ]
    )
    for item in rows:
        writer.writerow(
            [
                item.created_at.isoformat(sep=" ", timespec="seconds"),
                csv_safe(item.event_type),
                csv_safe(item.action),
                csv_safe(item.route),
                csv_safe(item.target),
                item.max_user_id or "",
                item.session_id,
            ]
        )
    return ("\ufeff" + output.getvalue()).encode("utf-8")
