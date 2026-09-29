from __future__ import annotations

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Company

NON_BREAKING_SPACE = "\u00A0"


def clean_company_name(value: str | None) -> str:
    """Collapse whitespace so logically identical company names match."""
    if value is None:
        return ""
    return " ".join(str(value).replace(NON_BREAKING_SPACE, " ").split())


def normalize_company_name(value: str | None) -> str:
    """Normalize company names for comparisons."""
    return clean_company_name(value).casefold()


def normalized_company_sql(column):
    """PostgreSQL expression that mirrors normalize_company_name()."""
    without_nbsp = func.replace(column, NON_BREAKING_SPACE, " ")
    collapsed = func.regexp_replace(func.trim(without_nbsp), r"\s+", " ", "g")
    return func.lower(collapsed)


def company_has_description(company: Company) -> bool:
    """Return True when a company has a non-empty description."""
    return bool((company.description or "").strip())


def choose_preferred_company(companies: list[Company]) -> Company | None:
    """Prefer the company row that already contains a description."""
    if not companies:
        return None
    return min(
        companies,
        key=lambda company: (
            not company_has_description(company),
            len(clean_company_name(company.name)),
            company.id or 0,
        ),
    )


def deduplicate_companies(companies: list[Company]) -> list[Company]:
    """Collapse duplicate company rows that differ only by formatting."""
    companies_by_normalized_name: dict[str, list[Company]] = {}
    for company in companies:
        normalized_name = normalize_company_name(company.name)
        if not normalized_name:
            continue
        companies_by_normalized_name.setdefault(normalized_name, []).append(company)

    deduplicated = [
        preferred
        for preferred in (
            choose_preferred_company(group)
            for group in companies_by_normalized_name.values()
        )
        if preferred is not None
    ]
    return sorted(deduplicated, key=lambda company: clean_company_name(company.name).casefold())


def company_order_by_preference():
    """Sort described companies before placeholder rows."""
    return (
        case(
            (
                and_(Company.description.isnot(None), func.trim(Company.description) != ""),
                0,
            ),
            else_=1,
        ),
        func.length(func.trim(Company.name)),
        Company.id.asc(),
    )


async def find_company_by_name(session: AsyncSession, company_name: str | None) -> Company | None:
    """Find the best matching company row by normalized name."""
    normalized_name = normalize_company_name(company_name)
    if not normalized_name:
        return None

    result = await session.execute(
        select(Company)
        .where(
            Company.name.isnot(None),
            Company.name != "",
            normalized_company_sql(Company.name) == normalized_name,
        )
        .order_by(*company_order_by_preference())
    )
    return result.scalars().first()


async def get_company_aliases(session: AsyncSession, company_name: str | None) -> list[Company]:
    """Return all company rows that normalize to the same name."""
    normalized_name = normalize_company_name(company_name)
    if not normalized_name:
        return []

    result = await session.execute(
        select(Company)
        .where(
            Company.name.isnot(None),
            Company.name != "",
            normalized_company_sql(Company.name) == normalized_name,
        )
        .order_by(*company_order_by_preference())
    )
    return result.scalars().all()
