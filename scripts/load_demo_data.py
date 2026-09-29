"""Load explicitly labelled, repeatable fixtures into a local test database.

Run from the app container: python scripts/load_demo_data.py
No external services are contacted; existing non-demo records are untouched.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from database.db import async_session_maker, engine
from database.models import Company, MiniappEvent, Vacancy


async def load() -> None:
    data = json.loads((ROOT / "fixtures/demo_data.json").read_text(encoding="utf-8"))
    created = {"companies": 0, "vacancies": 0, "events": 0}
    async with async_session_maker() as session:
        async with session.begin():
            company = (await session.execute(
                select(Company).where(Company.name == data["company"]["name"])
            )).scalar_one_or_none()
            if company is None:
                session.add(Company(**data["company"]))
                created["companies"] += 1
            for item in data["vacancies"]:
                found = (await session.execute(
                    select(Vacancy.id).where(Vacancy.source_key == item["source_key"])
                )).scalar_one_or_none()
                if found is None:
                    session.add(Vacancy(**item))
                    created["vacancies"] += 1
            event = (await session.execute(
                select(MiniappEvent).where(MiniappEvent.title == data["event"]["title"])
            )).scalars().first()
            if event is None:
                starts = datetime.now(timezone.utc) + timedelta(days=data["event_days_from_load"])
                local = starts.astimezone(timezone(timedelta(hours=3)))
                session.add(MiniappEvent(
                    **data["event"], starts_at=starts,
                    date_text=local.strftime("%d.%m.%Y, %H:%M МСК"),
                    deadline_text="Демонстрационная регистрация",
                ))
                created["events"] += 1
            elif event.starts_at and event.starts_at < datetime.now(timezone.utc):
                print("Existing demo event has started. Set a future date in the admin panel.")
    print("Demo fixtures loaded: " + json.dumps(created))
    print("Existing records and registrations were preserved. Accounts: student1/student2 @edu.fa.ru.")


async def main() -> None:
    try:
        await load()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
