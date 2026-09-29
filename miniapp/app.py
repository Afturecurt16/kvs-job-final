from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import sys
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

# This package is imported two different ways depending on how the server is
# launched: with kvs_career_bot/ itself as the working directory (main.py's
# own uvicorn.Config("miniapp.app:app", ...), and this repo's Bash-tested
# invocations), or from the project's parent directory via the top-level
# miniapp/app.py shim (`from kvs_career_bot.miniapp.app import app`). Only the
# first puts kvs_career_bot/ on sys.path automatically, so `config`,
# `database`, `services` (all top-level modules *inside* kvs_career_bot/)
# fail to resolve under the second. Adding it explicitly here makes both work.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import (
    ADMIN_EMAIL,
    MAX_BOT_TOKEN,
    MINIAPP_DEV_ADMIN_ENABLED,
)
from database.db import get_session
from database.models import (
    Company,
    Division,
    MiniappAction,
    MiniappEvent,
    MiniappNotification,
    MiniappEventRegistration,
    StudentProfile,
    Vacancy,
    VacancySyncState,
)
from services.event_reminder_scheduler import run_event_reminder_scheduler
from services.max_bot import MaxApiError, max_bot
from services.partner_defaults import KEPT_PARTNER, VK_ECOSYSTEM_PARTNERS, VK_PARTNER
from services.vacancy_scheduler import run_vacancy_sync_job, run_daily_vacancy_sync_scheduler

from .services.max_auth import extract_user_id, verify_init_data
from .services.analytics import build_metrics_dashboard, export_metrics_csv
from .services.vacancy_sheet import (
    build_categories,
    filter_vacancies,
    vacancy_from_db,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ASSETS_DIR = BASE_DIR.parent / "assets"
EVENT_UPLOAD_DIR = STATIC_DIR / "uploads" / "events"
EVENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="KVS Job Miniapp")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(OSError)
async def database_error_handler(request, exc: Exception):
    logging.getLogger(__name__).warning("Database request failed for %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database is temporarily unavailable"},
    )


@app.on_event("startup")
async def _ensure_db_ready() -> None:
    # The container/local launcher has already migrated and seeded the DB.
    # Standalone Uvicorn still initialises it here.
    if os.getenv("KVS_DB_INITIALIZED") == "1":
        return
    from database.db import init_db

    try:
        await init_db()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Database unavailable at startup (%s); database-backed sections "
            "will return a temporary-service response.",
            exc,
        )


@app.on_event("startup")
async def _start_vacancy_refresh_scheduler() -> None:
    app.state.vacancy_refresh_task = asyncio.create_task(
        run_daily_vacancy_sync_scheduler(),
        name="vacancy-db-sync",
    )


@app.on_event("startup")
async def _start_event_reminder_scheduler() -> None:
    app.state.event_reminder_task = asyncio.create_task(
        run_event_reminder_scheduler(),
        name="event-reminders",
    )


@app.on_event("shutdown")
async def _stop_event_reminder_scheduler() -> None:
    task = getattr(app.state, "event_reminder_task", None)
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@app.on_event("shutdown")
async def _stop_vacancy_refresh_scheduler() -> None:
    task = getattr(app.state, "vacancy_refresh_task", None)
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _is_local_request(request: Request) -> bool:
    hostname = request.url.hostname or ""
    client_host = request.client.host if request.client else ""
    try:
        client_ip = ipaddress.ip_address(client_host)
        client_is_loopback = client_ip.is_loopback
        # Docker Desktop forwards a browser request from the Windows host into
        # the container through its private bridge (normally 172.16/12), so
        # it is not reported as 127.0.0.1 inside Uvicorn.
        client_is_docker_bridge = client_ip in ipaddress.ip_network("172.16.0.0/12")
    except ValueError:
        client_is_loopback = client_host == "localhost"
        client_is_docker_bridge = False
    return (
        (client_is_loopback or client_is_docker_bridge)
        and hostname in {"localhost", "127.0.0.1", "::1"}
    )


async def require_admin(
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    x_admin_email: str = Header(default="", alias="X-Admin-Email"),
) -> int:
    """Educational admin gate using the configured profile email."""
    del request, x_max_init_data
    if ADMIN_EMAIL and x_admin_email.strip().casefold() == ADMIN_EMAIL:
        return 0
    raise HTTPException(status_code=401, detail="Invalid or missing admin email")


def _resolve_miniapp_user(request: Request, init_data: str) -> int | None:
    if MAX_BOT_TOKEN and init_data:
        parsed = verify_init_data(init_data, MAX_BOT_TOKEN)
        user_id = extract_user_id(parsed) if parsed else None
        if user_id:
            return user_id
    if MINIAPP_DEV_ADMIN_ENABLED and not init_data and _is_local_request(request):
        return 0
    return None


async def require_miniapp_user(
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
) -> int:
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    if user_id is None:
        logger = logging.getLogger(__name__)
        if not MAX_BOT_TOKEN:
            logger.error("MAX Mini App authorization failed: MAX_BOT_TOKEN is not configured")
            detail = "Авторизация MAX не настроена на сервере"
        elif not x_max_init_data:
            logger.warning("MAX Mini App authorization failed: X-Max-Init-Data is missing")
            detail = "MAX не передал данные авторизации. Закройте и заново откройте Mini App"
        else:
            logger.warning(
                "MAX Mini App authorization failed: initData signature, age, or user payload is invalid"
            )
            detail = (
                "Не удалось подтвердить авторизацию MAX. Перезапустите Mini App; "
                "если ошибка повторится, проверьте токен бота на сервере"
            )
        raise HTTPException(status_code=401, detail=detail)
    return user_id


def _normalize_profile_email(value: str) -> str | None:
    email = value.strip().casefold()
    return email if re.fullmatch(r"[a-z0-9._%+\-]+@edu\.fa\.ru", email) else None


def require_profile_email(
    x_profile_email: str = Header(default="", alias="X-Profile-Email"),
) -> str:
    email = _normalize_profile_email(x_profile_email)
    if email is None:
        raise HTTPException(
            status_code=401,
            detail="Нужно зарегистрироваться в профиле",
        )
    return email


def _registration_owner_filter(user_id: int | None, profile_email: str | None):
    conditions = []
    if user_id is not None:
        conditions.append(MiniappEventRegistration.max_user_id == user_id)
    if profile_email:
        conditions.append(MiniappEventRegistration.profile_email == profile_email)
    return or_(*conditions) if conditions else None


async def _backfill_registration_identity(
    registrations: list[MiniappEventRegistration],
    user_id: int | None,
    profile_email: str | None,
    session: AsyncSession,
) -> None:
    """Attach a verified MAX id to an earlier email-only registration."""
    changed = False
    for registration in registrations:
        if registration.max_user_id is None and user_id is not None:
            conflict = (
                await session.execute(
                    select(MiniappEventRegistration.id).where(
                        MiniappEventRegistration.event_id == registration.event_id,
                        MiniappEventRegistration.max_user_id == user_id,
                        MiniappEventRegistration.id != registration.id,
                    )
                )
            ).scalar_one_or_none()
            if conflict is None:
                registration.max_user_id = user_id
                changed = True
        if registration.profile_email is None and profile_email:
            conflict = (
                await session.execute(
                    select(MiniappEventRegistration.id).where(
                        MiniappEventRegistration.event_id == registration.event_id,
                        MiniappEventRegistration.profile_email == profile_email,
                        MiniappEventRegistration.id != registration.id,
                    )
                )
            ).scalar_one_or_none()
            if conflict is None:
                registration.profile_email = profile_email
                changed = True
    if changed:
        await session.commit()


class EventPayload(BaseModel):
    category: str = "Другое"
    format: str = "Офлайн"
    image: str = ""
    lead: str = ""
    title: str
    date: str = ""
    startsAt: datetime | None = None
    place: str = ""
    description: str = ""
    deadline: str = ""
    url: str = ""
    capacity: int = Field(default=0, ge=0, le=100000)
    isActive: bool = True


class EventMessagePayload(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    audience: Literal["all", "confirmed", "reserve"] = "all"


class DepartmentPayload(BaseModel):
    name: str = Field(max_length=200)
    description: str = ""


class PartnerPayload(BaseModel):
    name: str = Field(max_length=200)
    logo: str = ""
    description: str = ""
    achievements: str = ""
    parentId: int | None = None
    isActive: bool = True
    departments: list[DepartmentPayload] = Field(default_factory=list)


class MetricEventPayload(BaseModel):
    eventType: Literal["click", "page_view"]
    action: str = Field(min_length=1, max_length=100)
    route: str = Field(default="/", max_length=255)
    target: str = Field(default="", max_length=255)
    sessionId: str = Field(min_length=8, max_length=64)
    metadata: dict = Field(default_factory=dict)


def _event_to_frontend(
    event: MiniappEvent,
    *,
    registration: MiniappEventRegistration | None = None,
    reserve_position: int | None = None,
    include_admin: bool = False,
    main_count: int = 0,
    reserve_count: int = 0,
) -> dict:
    item = {
        "id": str(event.id),
        "category": event.category,
        "format": event.format,
        "image": event.image_url or "",
        "lead": event.lead or "",
        "title": event.title,
        "date": event.date_text or "",
        "startsAt": event.starts_at.isoformat() if event.starts_at else "",
        "place": event.place or "",
        "description": event.description or "",
        "deadline": event.deadline_text or "",
        "url": event.external_url or "",
        "isActive": event.is_active,
        "isRegistered": registration is not None,
        "registrationStatus": registration.status if registration else "",
        "reservePosition": reserve_position,
    }
    if include_admin:
        item.update({
            "capacity": event.capacity,
            "mainCount": main_count,
            "reserveCount": reserve_count,
        })
    return item


def _apply_event_payload(event: MiniappEvent, payload: EventPayload) -> None:
    event.category = payload.category.strip() or "Другое"
    event.format = payload.format.strip() or "Офлайн"
    event.image_url = payload.image.strip()
    event.lead = payload.lead.strip()
    event.title = payload.title.strip()
    event.date_text = payload.date.strip()
    event.starts_at = (
        payload.startsAt.replace(tzinfo=timezone.utc)
        if payload.startsAt and payload.startsAt.tzinfo is None
        else payload.startsAt
    )
    event.place = payload.place.strip()
    event.description = payload.description.strip()
    event.deadline_text = payload.deadline.strip()
    event.external_url = payload.url.strip()
    event.capacity = payload.capacity
    event.is_active = payload.isActive


def _partner_to_frontend(
    company: Company,
    *,
    include_departments: bool = True,
    include_children: bool = True,
    children: list[Company] | None = None,
) -> dict:
    child_companies = children or []
    item = {
        "id": str(company.id),
        "name": company.name,
        "logoUrl": company.logo_url or "",
        "initial": (company.name[:1] or "К").upper(),
        "brandColor": "#2787f5" if company.name.casefold() == "vk" else "#c40016",
        "description": company.description or "",
        "achievements": company.achievements or "",
        "parentId": str(company.parent_company_id) if company.parent_company_id else None,
        # Do not dereference the self-referencing relationship here: in an
        # async SQLAlchemy response it may otherwise trigger implicit I/O.
        "parentName": "",
        "isActive": company.is_active,
        "departmentCount": len(company.divisions),
        "childCount": len(child_companies),
    }
    if include_departments:
        item["departments"] = [
            {
                "id": str(department.id),
                "companyId": str(company.id),
                "companyName": company.name,
                "name": department.name,
                "description": department.description or "",
            }
            for department in company.divisions
        ]
    item["children"] = (
        [
            _partner_to_frontend(child, include_departments=False, include_children=False)
            for child in child_companies
            if child.is_partner and child.is_active
        ]
        if include_children
        else []
    )
    return item


def _default_partner_to_frontend_from_profile(
    profile: dict,
    partner_id: str,
    *,
    include_departments: bool = True,
) -> dict:
    departments = [
        {
            "id": str(index),
            "companyId": partner_id,
            "companyName": profile["name"],
            "name": item["name"],
            "description": item["description"],
        }
        for index, item in enumerate(profile["departments"], start=1)
    ]
    partner = {
        "id": partner_id,
        "name": profile["name"],
        "logoUrl": profile["logo_url"],
        "initial": profile["name"][:1].upper(),
        "brandColor": "#2787f5" if profile["name"] == "VK" else "#c40016",
        "description": profile["description"],
        "achievements": profile["achievements"],
        "isActive": True,
        "departmentCount": len(departments),
        "childCount": 0,
        "children": [],
    }
    if include_departments:
        partner["departments"] = departments
    return partner


def _default_partner_to_frontend(*, include_departments: bool = True) -> dict:
    return _default_partner_to_frontend_from_profile(
        KEPT_PARTNER,
        "1",
        include_departments=include_departments,
    )


def _default_vk_partner_to_frontend(*, include_departments: bool = True) -> dict:
    partner = _default_partner_to_frontend_from_profile(
        VK_PARTNER,
        "2",
        include_departments=include_departments,
    )
    partner["children"] = _default_vk_ecosystem_partners_to_frontend(include_departments=False)
    partner["childCount"] = len(partner["children"])
    return partner


def _default_vk_ecosystem_partners_to_frontend(*, include_departments: bool = False) -> list[dict]:
    return [
        _default_partner_to_frontend_from_profile(
            profile,
            str(index),
            include_departments=include_departments,
        )
        for index, profile in enumerate(VK_ECOSYSTEM_PARTNERS, start=3)
    ]


def _apply_partner_payload(company: Company, payload: PartnerPayload) -> None:
    company.name = payload.name.strip()
    company.logo_url = payload.logo.strip()
    company.description = payload.description.strip()
    company.achievements = payload.achievements.strip()
    company.parent_company_id = payload.parentId
    company.is_partner = True
    company.is_active = payload.isActive
    company.divisions.clear()
    company.divisions.extend(
        Division(name=item.name.strip(), description=item.description.strip())
        for item in payload.departments
        if item.name.strip()
    )


async def _validate_parent_company(
    session: AsyncSession,
    parent_id: int | None,
    *,
    company_id: int | None = None,
) -> int | None:
    if parent_id is None:
        return None
    if company_id is not None and parent_id == company_id:
        raise HTTPException(status_code=422, detail="Компания не может быть родителем самой себя")

    parent = await session.get(Company, parent_id)
    if not parent or not parent.is_partner:
        raise HTTPException(status_code=422, detail="Родительская компания не найдена")

    seen: set[int] = set()
    cursor = parent
    while cursor is not None:
        if cursor.id in seen:
            raise HTTPException(status_code=422, detail="Обнаружена циклическая иерархия компаний")
        seen.add(cursor.id)
        if company_id is not None and cursor.parent_company_id == company_id:
            raise HTTPException(status_code=422, detail="Нельзя вложить компанию в собственное дочернее подразделение")
        cursor = await session.get(Company, cursor.parent_company_id) if cursor.parent_company_id else None
    return parent_id


async def _get_partner(
    session: AsyncSession,
    partner_id: int,
    *,
    public_only: bool = False,
) -> Company | None:
    conditions = [Company.id == partner_id, Company.is_partner.is_(True)]
    if public_only:
        conditions.append(Company.is_active.is_(True))
    return (
        await session.execute(
            select(Company)
            .options(
                selectinload(Company.divisions),
            )
            .where(*conditions)
        )
    ).scalar_one_or_none()


async def _get_partner_children(
    session: AsyncSession,
    parent_ids: list[int],
    *,
    public_only: bool = True,
) -> dict[int, list[Company]]:
    if not parent_ids:
        return {}
    conditions = [Company.parent_company_id.in_(parent_ids), Company.is_partner.is_(True)]
    if public_only:
        conditions.append(Company.is_active.is_(True))
    result = await session.execute(
        select(Company)
        .options(selectinload(Company.divisions))
        .where(*conditions)
        .order_by(Company.name)
    )
    children: dict[int, list[Company]] = {}
    for company in result.scalars().all():
        children.setdefault(company.parent_company_id, []).append(company)
    return children


@app.middleware("http")
async def disable_static_cache(request, call_next):
    response = await call_next(request)
    if (request.url.path in {"/", "/miniapp"}
            or request.url.path.startswith("/static/src/")
            or request.url.path.startswith("/api/v1/me/")
            or request.url.path.startswith("/assets/images/logos/")):
        response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/")
@app.get("/miniapp")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "kvs-job-miniapp"}


@app.get("/api/v1/bootstrap")
async def bootstrap():
    """Return the current miniapp backend contract."""
    return {
        "mode": "google_sheets",
        "entities": ["User", "Vacancy", "Partner", "Department", "CareerEvent", "Application", "Favorite", "Profile"],
        "frontend": "static-esm",
        "vacancySource": "GOOGLE_SHEETS_URL",
    }


def _profile_to_frontend(profile: StudentProfile | None, email: str) -> dict:
    return {
        "email": email,
        "faculty": profile.faculty if profile else "",
        "course": profile.course if profile else "",
        "group": profile.group if profile else "",
    }


@app.get("/api/v1/me/profile")
async def get_profile(
    profile_email: str = Depends(require_profile_email),
    session: AsyncSession = Depends(get_session),
):
    profile = await session.get(StudentProfile, profile_email)
    return _profile_to_frontend(profile, profile_email)


class StudentProfileUpdate(BaseModel):
    faculty: str = Field(default="", max_length=120)
    course: str = Field(default="", max_length=32)
    group: str = Field(default="", max_length=80)


@app.put("/api/v1/me/profile")
async def update_profile(
    body: StudentProfileUpdate,
    profile_email: str = Depends(require_profile_email),
    session: AsyncSession = Depends(get_session),
):
    profile = await session.get(StudentProfile, profile_email)
    if profile is None:
        profile = StudentProfile(email=profile_email)
        session.add(profile)
    profile.faculty = body.faculty.strip()
    profile.course = body.course.strip()
    profile.group = body.group.strip()
    await session.commit()
    return _profile_to_frontend(profile, profile_email)


@app.post("/api/v1/metrics/actions", status_code=204)
async def record_miniapp_action(
    payload: MetricEventPayload,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    max_user_id = None
    if MAX_BOT_TOKEN and x_max_init_data:
        parsed = verify_init_data(x_max_init_data, MAX_BOT_TOKEN)
        if parsed:
            max_user_id = extract_user_id(parsed)

    raw_data = json.dumps(payload.metadata, ensure_ascii=False, separators=(",", ":"))
    session.add(
        MiniappAction(
            max_user_id=max_user_id,
            session_id=payload.sessionId.strip(),
            event_type=payload.eventType,
            action=payload.action.strip(),
            route=payload.route.strip() or "/",
            target=payload.target.strip(),
            raw_data=raw_data[:4000],
        )
    )
    await session.commit()
    return Response(status_code=204)


@app.get("/api/v1/admin/metrics")
async def admin_get_metrics(
    days: int = Query(default=30, ge=7, le=90),
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await build_metrics_dashboard(session, days)


@app.get("/api/v1/admin/metrics/export")
async def admin_export_metrics(
    days: int = Query(default=30, ge=7, le=90),
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    content = await export_metrics_csv(session, days)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="kvs-metrics-{days}d.csv"'
        },
    )


@app.get("/api/v1/partners")
async def list_partners(session: AsyncSession = Depends(get_session)):
    try:
        result = await session.execute(
            select(Company)
            .options(selectinload(Company.divisions))
            .where(
                Company.is_partner.is_(True),
                Company.is_active.is_(True),
                Company.parent_company_id.is_(None),
            )
            .order_by(Company.name)
        )
    except (SQLAlchemyError, OSError) as exc:
        logging.getLogger(__name__).warning("Using default partners because the database is unavailable: %s", exc)
        items = [
            _default_partner_to_frontend(include_departments=False),
            _default_vk_partner_to_frontend(include_departments=False),
            *_default_vk_ecosystem_partners_to_frontend(include_departments=False),
        ]
        return {"source": "defaults", "items": items, "total": len(items)}
    companies = result.scalars().all()
    children_by_parent = await _get_partner_children(
        session,
        [company.id for company in companies],
    )
    items = [
        _partner_to_frontend(
            company,
            include_departments=False,
            children=children_by_parent.get(company.id, []),
        )
        for company in companies
    ]
    return {"source": "database", "items": items, "total": len(items)}


@app.get("/api/v1/partners/{partner_id}")
async def get_partner(partner_id: int, session: AsyncSession = Depends(get_session)):
    try:
        company = await _get_partner(session, partner_id, public_only=True)
    except (SQLAlchemyError, OSError) as exc:
        logging.getLogger(__name__).warning("Using default partner because the database is unavailable: %s", exc)
        if partner_id == 1:
            return _default_partner_to_frontend()
        if partner_id == 2:
            return _default_vk_partner_to_frontend()
        ecosystem_index = partner_id - 3
        if 0 <= ecosystem_index < len(VK_ECOSYSTEM_PARTNERS):
            return _default_partner_to_frontend_from_profile(
                VK_ECOSYSTEM_PARTNERS[ecosystem_index],
                str(partner_id),
            )
        raise HTTPException(status_code=404, detail="Partner not found") from exc
    if not company:
        raise HTTPException(status_code=404, detail="Partner not found")
    children_by_parent = await _get_partner_children(session, [company.id])
    return _partner_to_frontend(
        company,
        children=children_by_parent.get(company.id, []),
    )


@app.get("/api/v1/partners/{partner_id}/departments/{department_id}")
async def get_partner_department(
    partner_id: int,
    department_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        company = await _get_partner(session, partner_id, public_only=True)
    except (SQLAlchemyError, OSError) as exc:
        logging.getLogger(__name__).warning("Using default department because the database is unavailable: %s", exc)
        partner = (
            _default_partner_to_frontend()
            if partner_id == 1
            else _default_vk_partner_to_frontend()
            if partner_id == 2
            else _default_partner_to_frontend_from_profile(
                VK_ECOSYSTEM_PARTNERS[partner_id - 3],
            )
            if 3 <= partner_id < 3 + len(VK_ECOSYSTEM_PARTNERS)
            else None
        )
        if partner is None:
            raise HTTPException(status_code=404, detail="Partner not found") from exc
        department = next(
            (item for item in partner["departments"] if item["id"] == str(department_id)),
            None,
        )
        if not department:
            raise HTTPException(status_code=404, detail="Department not found") from exc
        return {**department, "companyLogoUrl": partner["logoUrl"]}
    if not company:
        raise HTTPException(status_code=404, detail="Partner not found")
    department = next((item for item in company.divisions if item.id == department_id), None)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    return {
        "id": str(department.id),
        "companyId": str(company.id),
        "companyName": company.name,
        "companyLogoUrl": company.logo_url or "",
        "name": department.name,
        "description": department.description or "",
    }


@app.get("/api/v1/admin/partners")
async def admin_list_partners(
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Company)
        .options(selectinload(Company.divisions))
        .where(Company.is_partner.is_(True))
        .order_by(Company.name)
    )
    companies = result.scalars().all()
    children_by_parent: dict[int, list[Company]] = {}
    for company in companies:
        if company.parent_company_id:
            children_by_parent.setdefault(company.parent_company_id, []).append(company)
    return {
        "items": [
            _partner_to_frontend(company, children=children_by_parent.get(company.id, []))
            for company in companies
        ]
    }


@app.post("/api/v1/admin/partners", status_code=201)
async def admin_create_partner(
    payload: PartnerPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")

    company = (
        await session.execute(select(Company).where(func.lower(Company.name) == name.lower()))
    ).scalar_one_or_none()
    if company and company.is_partner:
        raise HTTPException(status_code=409, detail="Partner with this name already exists")
    if company is None:
        company = Company()
        session.add(company)
    else:
        await session.refresh(company, attribute_names=["divisions"])

    await session.flush()
    await _validate_parent_company(session, payload.parentId, company_id=company.id)
    _apply_partner_payload(company, payload)
    await session.commit()
    company = await _get_partner(session, company.id)
    return _partner_to_frontend(company)


@app.put("/api/v1/admin/partners/{partner_id}")
async def admin_update_partner(
    partner_id: int,
    payload: PartnerPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    company = await _get_partner(session, partner_id)
    if not company:
        raise HTTPException(status_code=404, detail="Partner not found")
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Name is required")

    duplicate = (
        await session.execute(
            select(Company.id).where(
                Company.id != partner_id,
                func.lower(Company.name) == payload.name.strip().lower(),
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="Company with this name already exists")

    await _validate_parent_company(session, payload.parentId, company_id=company.id)
    _apply_partner_payload(company, payload)
    await session.commit()
    company = await _get_partner(session, partner_id)
    return _partner_to_frontend(company)


@app.delete("/api/v1/admin/partners/{partner_id}", status_code=204)
async def admin_delete_partner(
    partner_id: int,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    company = await _get_partner(session, partner_id)
    if not company:
        raise HTTPException(status_code=404, detail="Partner not found")
    company.is_partner = False
    company.is_active = False
    await session.commit()
    return None


@app.get("/api/v1/subscription")
async def get_subscription_status(user_id: int = Depends(require_miniapp_user)):
    try:
        status = await max_bot.subscription_status(user_id)
    except MaxApiError as exc:
        logging.getLogger(__name__).warning("MAX subscription check failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Не удалось проверить подписку. Убедитесь, что MAX-бот добавлен "
                "администратором обязательного канала."
            ),
        ) from exc
    return {
        "required": status.required,
        "subscribed": status.subscribed,
        "channelUrl": status.channel_url,
    }


async def _require_max_subscription(user_id: int) -> None:
    try:
        status = await max_bot.subscription_status(user_id)
    except MaxApiError as exc:
        raise HTTPException(status_code=503, detail="Не удалось проверить подписку в MAX") from exc
    if status.required and not status.subscribed:
        raise HTTPException(status_code=403, detail="Сначала подпишитесь на канал в MAX")


async def _reserve_position(
    session: AsyncSession,
    registration: MiniappEventRegistration,
) -> int | None:
    if registration.status != "reserve":
        return None
    return int(
        (
            await session.execute(
                select(func.count(MiniappEventRegistration.id)).where(
                    MiniappEventRegistration.event_id == registration.event_id,
                    MiniappEventRegistration.status == "reserve",
                    MiniappEventRegistration.id <= registration.id,
                )
            )
        ).scalar_one()
    )


def _registration_notification_text(event: MiniappEvent, status: str) -> str:
    if status == "confirmed":
        return f"Вы зарегистрированы на мероприятие «{event.title}». Место подтверждено."
    return (
        f"Вы в резерве на мероприятие «{event.title}». "
        "Как только освободится место, мы сообщим вам здесь."
    )


def _add_event_notification(
    session: AsyncSession,
    registration: MiniappEventRegistration,
    event: MiniappEvent,
    kind: str,
    text: str,
) -> None:
    session.add(
        MiniappNotification(
            event_id=event.id,
            max_user_id=registration.max_user_id,
            profile_email=registration.profile_email,
            kind=kind,
            event_title=event.title,
            text=text,
        )
    )


def _promotion_notification_text(event: MiniappEvent) -> str:
    return f"Освободилось место на мероприятии «{event.title}». Вы перенесены из резерва в основной список."


@app.get("/api/v1/events")
async def list_events(
    request: Request,
    category: str = Query(default="Все", max_length=120),
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    x_profile_email: str = Header(default="", alias="X-Profile-Email"),
    session: AsyncSession = Depends(get_session),
):
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    profile_email = _normalize_profile_email(x_profile_email)
    result = await session.execute(
        select(MiniappEvent)
        .where(MiniappEvent.is_active.is_(True))
        .order_by(MiniappEvent.starts_at.asc().nullslast(), MiniappEvent.created_at.desc())
    )
    events = result.scalars().all()
    registrations: dict[int, MiniappEventRegistration] = {}
    owner_filter = _registration_owner_filter(user_id, profile_email)
    if owner_filter is not None and events:
        rows = (
            await session.execute(
                select(MiniappEventRegistration).where(
                    owner_filter,
                    MiniappEventRegistration.event_id.in_([event.id for event in events]),
                )
            )
        ).scalars().all()
        await _backfill_registration_identity(rows, user_id, profile_email, session)
        registrations = {row.event_id: row for row in rows}
    all_items = []
    for event in events:
        registration = registrations.get(event.id)
        all_items.append(
            _event_to_frontend(
                event,
                registration=registration,
                reserve_position=(await _reserve_position(session, registration)) if registration else None,
            )
        )
    categories = ["Все", *sorted({item["category"] for item in all_items if item["category"]})]
    items = all_items if category in ("", "Все") else [item for item in all_items if item["category"] == category]

    return {
        "source": "database",
        "categories": categories,
        "items": items,
        "total": len(items),
        "registeredCount": len(registrations),
    }


@app.get("/api/v1/me/events")
async def list_my_events(
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    profile_email: str = Depends(require_profile_email),
    session: AsyncSession = Depends(get_session),
):
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    owner_filter = _registration_owner_filter(user_id, profile_email)
    result = await session.execute(
        select(MiniappEvent, MiniappEventRegistration)
        .join(
            MiniappEventRegistration,
            MiniappEventRegistration.event_id == MiniappEvent.id,
        )
        .where(
            owner_filter,
            MiniappEvent.is_active.is_(True),
        )
        .order_by(MiniappEvent.starts_at.asc().nullslast(), MiniappEvent.created_at.desc())
    )
    event_registrations = result.all()
    await _backfill_registration_identity(
        [registration for _, registration in event_registrations],
        user_id,
        profile_email,
        session,
    )
    items = []
    for event, registration in event_registrations:
        item = _event_to_frontend(
            event,
            registration=registration,
            reserve_position=await _reserve_position(session, registration),
        )
        item["registeredAt"] = registration.created_at.isoformat() if registration.created_at else ""
        items.append(item)
    return {"items": items, "total": len(items)}


@app.get("/api/v1/me/notifications")
async def list_my_notifications(
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    profile_email: str = Depends(require_profile_email),
    session: AsyncSession = Depends(get_session),
):
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    owner_filter = _notification_owner_filter(profile_email, user_id)
    rows = (
        await session.execute(
            select(MiniappNotification)
            .where(owner_filter)
            .order_by(MiniappNotification.created_at.desc(), MiniappNotification.id.desc())
            .limit(100)
        )
    ).scalars().all()
    items = [
        {
            "id": notification.id,
            "eventId": notification.event_id,
            "eventTitle": notification.event_title,
            "kind": notification.kind,
            "text": notification.text,
            "createdAt": notification.created_at.isoformat(),
            "readAt": notification.read_at.isoformat() if notification.read_at else None,
        }
        for notification in rows
    ]
    return {"items": items, "total": len(items), "unreadCount": await _unread_notification_count(session, owner_filter)}


def _notification_owner_filter(profile_email: str, user_id: int | None):
    conditions = [MiniappNotification.profile_email == profile_email]
    if user_id is not None:
        conditions.append(MiniappNotification.max_user_id == user_id)
    return or_(*conditions)


async def _unread_notification_count(session: AsyncSession, owner_filter) -> int:
    return int((await session.scalar(
        select(func.count(MiniappNotification.id)).where(
            owner_filter, MiniappNotification.read_at.is_(None),
        )
    )) or 0)


@app.get("/api/v1/me/notifications/unread-count")
async def unread_notification_count(
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    profile_email: str = Depends(require_profile_email),
    session: AsyncSession = Depends(get_session),
):
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    owner_filter = _notification_owner_filter(profile_email, user_id)
    return {"unreadCount": await _unread_notification_count(session, owner_filter)}


class MarkNotificationsReadRequest(BaseModel):
    through_id: int = Field(gt=0, alias="throughId")


@app.post("/api/v1/me/notifications/read")
async def mark_my_notifications_read(
    body: MarkNotificationsReadRequest,
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    profile_email: str = Depends(require_profile_email),
    session: AsyncSession = Depends(get_session),
):
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    owner_filter = _notification_owner_filter(profile_email, user_id)
    await session.execute(
        update(MiniappNotification)
        .where(owner_filter, MiniappNotification.id <= body.through_id, MiniappNotification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return {"unreadCount": await _unread_notification_count(session, owner_filter)}


@app.post("/api/v1/events/{event_id}/register", status_code=201)
async def register_for_event(
    event_id: int,
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    profile_email: str = Depends(require_profile_email),
    session: AsyncSession = Depends(get_session),
):
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    if user_id is not None:
        await _require_max_subscription(user_id)
    event = (
        await session.execute(
            select(MiniappEvent).where(MiniappEvent.id == event_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not event or not event.is_active:
        raise HTTPException(status_code=404, detail="Event not found")
    if not event.starts_at:
        raise HTTPException(status_code=409, detail="Event start time is not configured")
    now = datetime.now(timezone.utc)
    starts_at = event.starts_at
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    if starts_at <= now:
        raise HTTPException(status_code=409, detail="Event has already started")

    registration = (
        await session.execute(
            select(MiniappEventRegistration).where(
                MiniappEventRegistration.event_id == event_id,
                _registration_owner_filter(user_id, profile_email),
            )
        )
    ).scalar_one_or_none()
    if registration is None:
        main_count = int(
            (
                await session.execute(
                    select(func.count(MiniappEventRegistration.id)).where(
                        MiniappEventRegistration.event_id == event_id,
                        MiniappEventRegistration.status == "confirmed",
                    )
                )
            ).scalar_one()
        )
        status = "confirmed" if event.capacity <= 0 or main_count < event.capacity else "reserve"
        registration = MiniappEventRegistration(
            event_id=event_id,
            max_user_id=user_id,
            profile_email=profile_email,
            status=status,
        )
        session.add(registration)
        await session.flush()
        _add_event_notification(
            session, registration, event, "registration", _registration_notification_text(event, status)
        )
        await session.commit()
        await session.refresh(registration)
    else:
        registration_changed = False
        if registration.profile_email is None:
            registration.profile_email = profile_email
            registration_changed = True
        if registration.max_user_id is None and user_id is not None:
            registration.max_user_id = user_id
            registration_changed = True
        if registration_changed:
            await session.commit()
    item = _event_to_frontend(
        event,
        registration=registration,
        reserve_position=await _reserve_position(session, registration),
    )
    return item


@app.delete("/api/v1/events/{event_id}/register", status_code=204)
async def unregister_from_event(
    event_id: int,
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    profile_email: str = Depends(require_profile_email),
    session: AsyncSession = Depends(get_session),
):
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    event = (
        await session.execute(
            select(MiniappEvent).where(MiniappEvent.id == event_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    registration = (
        await session.execute(
            select(MiniappEventRegistration).where(
                MiniappEventRegistration.event_id == event_id,
                _registration_owner_filter(user_id, profile_email),
            )
        )
    ).scalar_one_or_none()
    if registration:
        should_promote = registration.status == "confirmed"
        await session.delete(registration)
        await session.flush()
        if should_promote:
            promoted = (
                await session.execute(
                    select(MiniappEventRegistration)
                    .where(
                        MiniappEventRegistration.event_id == event_id,
                        MiniappEventRegistration.status == "reserve",
                    )
                    .order_by(MiniappEventRegistration.created_at, MiniappEventRegistration.id)
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if promoted:
                promoted.status = "confirmed"
                promoted.promoted_at = datetime.now(timezone.utc)
                _add_event_notification(
                    session, promoted, event, "promotion", _promotion_notification_text(event)
                )
        await session.commit()
    return Response(status_code=204)


@app.get("/api/v1/admin/events")
async def admin_list_events(
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Full event list for the admin panel, including inactive/hidden events."""
    result = await session.execute(select(MiniappEvent).order_by(MiniappEvent.created_at.desc()))
    events = result.scalars().all()
    counts = {}
    if events:
        count_rows = (
            await session.execute(
                select(
                    MiniappEventRegistration.event_id,
                    MiniappEventRegistration.status,
                    func.count(MiniappEventRegistration.id),
                )
                .where(MiniappEventRegistration.event_id.in_([event.id for event in events]))
                .group_by(MiniappEventRegistration.event_id, MiniappEventRegistration.status)
            )
        ).all()
        for event_id, status, count in count_rows:
            counts.setdefault(event_id, {})[status] = int(count)
    return {
        "items": [
            _event_to_frontend(
                event,
                include_admin=True,
                main_count=counts.get(event.id, {}).get("confirmed", 0),
                reserve_count=counts.get(event.id, {}).get("reserve", 0),
            )
            for event in events
        ]
    }


@app.post("/api/v1/admin/events/upload", status_code=201)
async def admin_upload_event_image(
    request: Request,
    admin_id: int = Depends(require_admin),
):
    content_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    extension = content_types.get(request.headers.get("content-type", "").split(";", 1)[0])
    if not extension:
        raise HTTPException(status_code=415, detail="Поддерживаются JPG, PNG, WEBP и GIF")
    data = await request.body()
    if len(data) > 6 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Изображение должно быть не больше 6 МБ")
    if not data:
        raise HTTPException(status_code=422, detail="Файл пуст")
    filename = f"{uuid.uuid4().hex}{extension}"
    (EVENT_UPLOAD_DIR / filename).write_bytes(data)
    return {"url": f"/static/uploads/events/{filename}"}


@app.post("/api/v1/admin/events", status_code=201)
async def admin_create_event(
    payload: EventPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")
    if payload.capacity < 1:
        raise HTTPException(status_code=422, detail="Укажите лимит участников")

    event = MiniappEvent()
    _apply_event_payload(event, payload)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return _event_to_frontend(event, include_admin=True)


@app.put("/api/v1/admin/events/{event_id}")
async def admin_update_event(
    event_id: int,
    payload: EventPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    event = (
        await session.execute(
            select(MiniappEvent).where(MiniappEvent.id == event_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")
    if payload.capacity < 1:
        raise HTTPException(status_code=422, detail="Укажите лимит участников")

    main_count = int(
        (
            await session.execute(
                select(func.count(MiniappEventRegistration.id)).where(
                    MiniappEventRegistration.event_id == event_id,
                    MiniappEventRegistration.status == "confirmed",
                )
            )
        ).scalar_one()
    )
    if payload.capacity < main_count:
        raise HTTPException(
            status_code=409,
            detail=f"Лимит нельзя сделать меньше основного списка ({main_count})",
        )

    _apply_event_payload(event, payload)
    promoted = []
    free_slots = payload.capacity - main_count
    if free_slots > 0:
        promoted = list(
            (
                await session.execute(
                    select(MiniappEventRegistration)
                    .where(
                        MiniappEventRegistration.event_id == event_id,
                        MiniappEventRegistration.status == "reserve",
                    )
                    .order_by(MiniappEventRegistration.created_at, MiniappEventRegistration.id)
                    .limit(free_slots)
                    .with_for_update()
                )
            ).scalars()
        )
        now = datetime.now(timezone.utc)
        for registration in promoted:
            registration.status = "confirmed"
            registration.promoted_at = now
            _add_event_notification(
                session, registration, event, "promotion", _promotion_notification_text(event)
            )
    await session.commit()
    await session.refresh(event)
    reserve_count = int(
        (
            await session.execute(
                select(func.count(MiniappEventRegistration.id)).where(
                    MiniappEventRegistration.event_id == event_id,
                    MiniappEventRegistration.status == "reserve",
                )
            )
        ).scalar_one()
    )
    return _event_to_frontend(
        event,
        include_admin=True,
        main_count=main_count + len(promoted),
        reserve_count=reserve_count,
    )


@app.post("/api/v1/admin/events/{event_id}/message")
async def admin_message_event_participants(
    event_id: int,
    payload: EventMessagePayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(MiniappEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Введите текст сообщения")
    conditions = [MiniappEventRegistration.event_id == event_id]
    if payload.audience != "all":
        conditions.append(MiniappEventRegistration.status == payload.audience)
    registrations = list(
        (
            await session.execute(
                select(MiniappEventRegistration)
                .where(*conditions)
                .order_by(MiniappEventRegistration.id)
            )
        ).scalars()
    )
    recipients = [
        registration for registration in registrations
        if registration.profile_email or registration.max_user_id is not None
    ]
    for registration in recipients:
        _add_event_notification(session, registration, event, "admin", text)
    await session.commit()
    return {
        "total": len(registrations),
        "sent": len(recipients),
    }


@app.delete("/api/v1/admin/events/{event_id}", status_code=204)
async def admin_delete_event(
    event_id: int,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(MiniappEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await session.delete(event)
    await session.commit()
    return None


@app.post("/api/v1/admin/vacancies/sync")
async def admin_sync_vacancies(
    admin_id: int = Depends(require_admin),
):
    """Refresh the database snapshot from the configured Google Sheet."""
    del admin_id
    try:
        source_count = await run_vacancy_sync_job()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось обновить вакансии: {exc}") from exc
    return {"sourceCount": source_count, "status": "ready"}


@app.get("/api/v1/vacancies")
async def list_vacancies(
    q: str = Query(default="", max_length=160),
    category: str = Query(default="Все", max_length=120),
    limit: int = Query(default=80, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    refresh: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    # ``refresh`` is retained for compatibility with older clients. Source
    # refreshes are centralized in the scheduler so one HTTP request can never
    # make every user wait on Google Sheets.
    del refresh
    vacancies = (
        await session.execute(select(Vacancy).order_by(Vacancy.id.desc()))
    ).scalars().all()
    state = await session.get(VacancySyncState, 1)
    items = [vacancy_from_db(vacancy) for vacancy in vacancies]
    filtered = filter_vacancies(items, query=q, category=category)
    syncing = bool(state and state.status == "syncing")
    if syncing and state.started_at:
        started_at = state.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        # Do not leave the UI in an eternal "updating" state after a hard
        # process stop. The next scheduler run will write a fresh state.
        syncing = datetime.now(timezone.utc) - started_at < timedelta(minutes=20)
    maintenance = not items
    if syncing:
        maintenance_message = "Обновляем вакансии. Обычно это занимает несколько минут."
    elif state and state.status == "failed":
        maintenance_message = "Идёт технический перерыв. Повторим загрузку автоматически."
    else:
        maintenance_message = "Вакансии подготавливаются. Попробуйте открыть раздел через несколько минут."

    loaded_at = state.completed_at if state else None
    if loaded_at is None and vacancies:
        loaded_at = max((item.updated_at or item.created_at) for item in vacancies)
    return {
        "source": "database",
        "loadedAt": loaded_at.isoformat() if loaded_at else None,
        "categories": build_categories(items),
        "items": filtered[offset : offset + limit],
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "syncing": syncing,
        "maintenance": maintenance,
        "maintenanceMessage": maintenance_message,
    }


@app.get("/api/v1/vacancies/{vacancy_id}")
async def get_vacancy(
    vacancy_id: str,
    refresh: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    del refresh
    raw_id = vacancy_id[3:] if vacancy_id.startswith("db-") else vacancy_id
    if not raw_id.isdigit():
        raise HTTPException(status_code=404, detail="Vacancy not found")
    vacancy = await session.get(Vacancy, int(raw_id))
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    state = await session.get(VacancySyncState, 1)
    loaded_at = state.completed_at if state else vacancy.updated_at
    return {
        **vacancy_from_db(vacancy),
        "source": "database",
        "loadedAt": loaded_at.isoformat() if loaded_at else None,
    }
