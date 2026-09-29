import sys
import time
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import select, text
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, SEED_DEMO_DATA

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _safe_print(message: str) -> None:
    """Print logs without crashing on non-UTF8 Windows consoles."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sanitized = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(sanitized)

async def get_session():
    async with async_session_maker() as session:
        yield session

async def init_db():
    """Create missing tables and optionally seed demo data."""
    from database.models import Base
    started_at = time.monotonic()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS ioo BOOLEAN DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS vacancy_url TEXT"))
            await conn.execute(text("ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS source_key VARCHAR(64)"))
            await conn.execute(text("ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS source_row INTEGER"))
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_vacancies_source_key ON vacancies (source_key) WHERE source_key IS NOT NULL"))
            await conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_url TEXT"))
            await conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS achievements TEXT"))
            await conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS parent_company_id INTEGER REFERENCES companies(id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_companies_parent_company_id ON companies (parent_company_id)"))
            await conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_partner BOOLEAN NOT NULL DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"))
            await conn.execute(text("ALTER TABLE miniapp_events ADD COLUMN IF NOT EXISTS starts_at TIMESTAMPTZ"))
            await conn.execute(text("ALTER TABLE miniapp_events ADD COLUMN IF NOT EXISTS capacity INTEGER NOT NULL DEFAULT 0"))
            await conn.execute(text("ALTER TABLE miniapp_event_registrations ADD COLUMN IF NOT EXISTS max_user_id BIGINT"))
            await conn.execute(text("ALTER TABLE miniapp_event_registrations ALTER COLUMN max_user_id DROP NOT NULL"))
            await conn.execute(text("ALTER TABLE miniapp_event_registrations ADD COLUMN IF NOT EXISTS profile_email VARCHAR(320)"))
            await conn.execute(text("ALTER TABLE miniapp_event_registrations ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'confirmed'"))
            await conn.execute(text("ALTER TABLE miniapp_event_registrations ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ"))
            await conn.execute(text("ALTER TABLE miniapp_event_registrations ADD COLUMN IF NOT EXISTS in_app_reminder_day_sent_at TIMESTAMPTZ"))
            await conn.execute(text("ALTER TABLE miniapp_event_registrations ADD COLUMN IF NOT EXISTS in_app_reminder_two_hours_sent_at TIMESTAMPTZ"))
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_miniapp_event_registration_max ON miniapp_event_registrations (event_id, max_user_id) WHERE max_user_id IS NOT NULL"))
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_miniapp_event_registration_email ON miniapp_event_registrations (event_id, profile_email) WHERE profile_email IS NOT NULL"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_miniapp_event_registrations_status ON miniapp_event_registrations (status)"))
            await conn.execute(text("ALTER TABLE miniapp_actions ADD COLUMN IF NOT EXISTS max_user_id BIGINT"))
            await conn.execute(text("ALTER TABLE miniapp_notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_miniapp_actions_max_user_id ON miniapp_actions (max_user_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_miniapp_events_starts_at ON miniapp_events (starts_at)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_companies_is_partner ON companies (is_partner)"))
        if SEED_DEMO_DATA:
            await seed_demo_data()
        await seed_kept_partner()
        await seed_vk_partner()
        await seed_vk_ecosystem_partners()
        _safe_print(f"✅ База данных готова за {time.monotonic() - started_at:.1f} с")
    except Exception as e:
        _safe_print(f"❌ Ошибка при создании таблиц: {e}")
        raise


async def seed_demo_data():
    """Seed demo companies/divisions for MVP environments."""
    from database.models import Company, Division
    
    # Демо компании и подразделения
    DEMO_DATA = [
        {
            "name": "Сбербанк",
            "description": "Крупнейший банк России и Восточной Европы. Предоставляет полный спектр банковских услуг для частных и корпоративных клиентов.",
            "divisions": [
                {"name": "IT-департамент", "description": "Разработка и поддержка банковских систем, мобильных приложений и цифровых сервисов."},
                {"name": "Аналитика", "description": "Data Science, машинное обучение, бизнес-аналитика и исследования."},
                {"name": "Розничный бизнес", "description": "Работа с частными клиентами, продажи банковских продуктов."},
            ]
        },
        {
            "name": "Яндекс",
            "description": "Технологическая компания, разрабатывающая поисковую систему, сервисы такси, доставки, облачные технологии и многое другое.",
            "divisions": [
                {"name": "Поиск", "description": "Разработка поисковых алгоритмов и машинного обучения."},
                {"name": "Яндекс.Такси", "description": "Сервис заказа такси и курьерской доставки."},
                {"name": "Яндекс.Маркет", "description": "Маркетплейс и e-commerce направление."},
            ]
        },
        {
            "name": "Тинькофф",
            "description": "Онлайн-банк и финансовая экосистема. Известен инновационным подходом и отсутствием отделений.",
            "divisions": [
                {"name": "Разработка", "description": "Backend, Frontend, Mobile разработка банковских продуктов."},
                {"name": "Тинькофф Инвестиции", "description": "Брокерские услуги и инвестиционные продукты."},
                {"name": "Бизнес", "description": "Продукты для малого и среднего бизнеса."},
            ]
        },
    ]
    
    async with async_session_maker() as session:
        for company_data in DEMO_DATA:
            # Проверяем, есть ли уже такая компания
            result = await session.execute(
                select(Company).where(Company.name == company_data["name"])
            )
            company = result.scalar_one_or_none()
            
            if not company:
                # Создаём компанию
                company = Company(
                    name=company_data["name"],
                    description=company_data["description"]
                )
                session.add(company)
                await session.flush()  # Получаем ID
                
                # Создаём подразделения
                for div_data in company_data["divisions"]:
                    division = Division(
                        company_id=company.id,
                        name=div_data["name"],
                        description=div_data["description"]
                    )
                    session.add(division)
                
                _safe_print(f"✅ Добавлена компания: {company_data['name']} с {len(company_data['divisions'])} подразделениями")
        
        await session.commit()
    
    _safe_print("✅ Демо-данные загружены")


async def seed_kept_partner() -> None:
    """Add the supplied Kept profile once without overwriting later admin edits."""
    from sqlalchemy import func

    from database.models import Company, Division
    from services.partner_defaults import KEPT_PARTNER

    async with async_session_maker() as session:
        company = (
            await session.execute(
                select(Company).where(func.lower(Company.name) == KEPT_PARTNER["name"].lower())
            )
        ).scalar_one_or_none()

        # is_active=False is also the tombstone used when an admin removes a
        # partner. Respect that choice on later restarts instead of re-seeding.
        if company and (company.is_partner or not company.is_active):
            return

        if company is None:
            company = Company(name=KEPT_PARTNER["name"])
            session.add(company)
            await session.flush()

        company.description = KEPT_PARTNER["description"]
        company.logo_url = KEPT_PARTNER["logo_url"]
        company.achievements = KEPT_PARTNER["achievements"]
        company.is_partner = True
        company.is_active = True

        existing_names = {
            name.casefold()
            for name in (
                await session.execute(
                    select(Division.name).where(Division.company_id == company.id)
                )
            ).scalars()
        }
        for division_data in KEPT_PARTNER["departments"]:
            if division_data["name"].casefold() not in existing_names:
                session.add(Division(company_id=company.id, **division_data))

        await session.commit()


async def seed_vk_partner() -> None:
    """Add the VK partner profile without overwriting later admin edits."""
    from sqlalchemy import func

    from database.models import Company, Division
    from services.partner_defaults import VK_PARTNER

    async with async_session_maker() as session:
        company = (
            await session.execute(
                select(Company).where(func.lower(Company.name) == VK_PARTNER["name"].lower())
            )
        ).scalar_one_or_none()

        if company and (company.is_partner or not company.is_active):
            return

        if company is None:
            company = Company(name=VK_PARTNER["name"])
            session.add(company)
            await session.flush()

        company.description = VK_PARTNER["description"]
        company.logo_url = VK_PARTNER["logo_url"]
        company.achievements = VK_PARTNER["achievements"]
        company.is_partner = True
        company.is_active = True

        existing_names = {
            name.casefold()
            for name in (
                await session.execute(
                    select(Division.name).where(Division.company_id == company.id)
                )
            ).scalars()
        }
        for division_data in VK_PARTNER["departments"]:
            if division_data["name"].casefold() not in existing_names:
                session.add(Division(company_id=company.id, **division_data))

        await session.commit()


async def seed_vk_ecosystem_partners() -> None:
    """Add public VK ecosystem products as separate partner cards."""
    from sqlalchemy import func

    from database.models import Company, Division
    from services.partner_defaults import VK_ECOSYSTEM_PARTNERS

    async with async_session_maker() as session:
        vk_company = (
            await session.execute(
                select(Company).where(func.lower(Company.name) == "vk")
            )
        ).scalar_one_or_none()
        if vk_company is None:
            return

        for profile in VK_ECOSYSTEM_PARTNERS:
            company = (
                await session.execute(
                    select(Company).where(func.lower(Company.name) == profile["name"].lower())
                )
            ).scalar_one_or_none()

            if company and company.is_partner:
                if company.parent_company_id != vk_company.id:
                    company.parent_company_id = vk_company.id
                continue
            if company and not company.is_active:
                continue

            if company is None:
                company = Company(name=profile["name"])
                session.add(company)
                await session.flush()

            company.description = profile["description"]
            company.logo_url = profile["logo_url"]
            company.achievements = profile["achievements"]
            company.parent_company_id = vk_company.id
            company.is_partner = True
            company.is_active = True

            existing_names = {
                name.casefold()
                for name in (
                    await session.execute(
                        select(Division.name).where(Division.company_id == company.id)
                    )
                ).scalars()
            }
            for division_data in profile["departments"]:
                if division_data["name"].casefold() not in existing_names:
                    session.add(Division(company_id=company.id, **division_data))

        await session.commit()

