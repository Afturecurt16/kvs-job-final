from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

PROJECT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_DIR / ".env")
load_dotenv()

SHEET_CACHE_TTL_SECONDS = max(15, int(os.getenv("MINIAPP_SHEET_CACHE_TTL_SECONDS", "300")))

HEADER_ALIASES = {
    "organization": ("Организация",),
    "division": ("Подразделение",),
    "position": ("Вакансия",),
    "sphere": ("Сфера",),
    "salary": ("ЗП",),
    "schedule": ("График",),
    "work_format": ("Формат",),
    "description": ("Описание",),
    "employment_format": ("Формат трудоустройства",),
    "feature1": ("Особенность 1",),
    "feature2": ("Особенность 2",),
    "feature3": ("Особенность 3",),
    "vacancy_url": ("Ссылка на вакансию",),
}

# Same 9 faculty checkbox columns used by the vacancy synchronizer.
# (FACULTY_SHEET_TO_DB) — sheet header paired with the short label used in the bot's
# faculty menu (config.py FACULTIES), in that menu's display order.
FACULTY_COLUMNS = [
    ("ИТиАБД", "ИТиАБД"),
    ("ИОО", "ИОО"),
    ("МЭО", "МЭО"),
    ("ФЭБ", "ФЭБ"),
    ("СНиМК", "СНиМК"),
    ("НАБ", "НАБ"),
    ("ВШУ", "ВШУ"),
    ("ФинФак", "ФФ"),
    ("ЮрФак", "ЮФ"),
]

FACULTY_CHECKED_VALUES = {"да", "yes", "1", "x", "✓", "true", "т", "+"}

BRAND_COLORS = ["#21A33B", "#159DD8", "#F40909", "#EC1C24", "#6266FF", "#C40016", "#009F62"]
METRO_COLORS = ["#D0183D", "#1268B3", "#159B55", "#EC7D00", "#7B61FF", "#C40016"]

# Known employer logos (local SVG/PNG assets served from assets/images/logos/),
# each with its real brand color for the vacancy-detail
# banner. Matched against the "Организация" cell by substring so minor spelling
# variants in the sheet still resolve. Companies without a verified logo asset
# (e.g. Билайн, Росатом) intentionally have none — they fall
# back to the colored-initial avatar and hashed banner color, same as any
# unrecognized organization.
COMPANY_LOGOS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("sberbank", "svg", "#21A038", ("сбербанк", "сбер")),
    ("tbank", "svg", "#FFDD2D", ("т-банк", "тбанк", "тинькофф", "tinkoff", "t-bank")),
    ("vtb", "svg", "#002882", ("втб",)),
    ("alfabank", "svg", "#EF3124", ("альфа-банк", "альфабанк", "alfa-bank", "alfa bank")),
    ("raiffeisen", "svg", "#FFE600", ("райффайзен", "raiffeisen")),
    ("rosbank", "svg", "#002F87", ("росбанк", "rosbank")),
    ("yandex", "svg", "#FC3F1D", ("яндекс", "yandex")),
    ("vk", "svg", "#0077FF", ("вконтакте", "vkontakte", "vk company", "mail.ru", "мейл.ру")),
    ("mts", "svg", "#FF0000", ("мтс", "mts")),
    ("megafon", "svg", "#00B956", ("мегафон", "megafon")),
    ("rostelecom", "svg", "#7B2BF9", ("ростелеком", "rostelecom")),
    ("ozon", "svg", "#005BFF", ("озон", "ozon")),
    ("wildberries", "png", "#CB11AB", ("wildberries", "вайлдберриз")),
    ("x5group-full", "png", "#5FAF2D", ("x5 group", "икс 5", "икс5", "пятёрочка", "пятерочка", "перекрёсток", "перекресток")),
    ("magnit", "svg", "#E30713", ("магнит", "magnit")),
    ("rosneft", "svg", "#1A1A1A", ("роснефть", "rosneft")),
    ("lukoil", "svg", "#EE1C25", ("лукойл", "lukoil")),
    ("aeroflot", "svg", "#00256C", ("аэрофлот", "aeroflot")),
    ("rzd", "svg", "#DA4216", ("ржд", "российские железные дороги", "russian railways")),
    ("kept_kpmg", "svg", "#00338D", ("kept", "кэпт", "kpmg", "кпмг")),
    ("deloitte", "svg", "#86BC25", ("deloitte", "делойт")),
    ("pwc", "svg", "#D04A02", ("pwc", "технологии доверия", "pricewaterhousecoopers")),
    ("b1", "png", "#14A557", ("б1", "b1")),
    ("ey", "svg", "#FFE600", ("эрнст энд янг", "ernst & young", "ey")),
    ("sibur", "svg", "#00A19C", ("сибур", "sibur")),
    ("cbrf", "svg", "#6D6E71", ("банк россии", "центральный банк", "центробанк", "цб рф")),
    ("gazprombank", "svg", "#476BF0", ("газпромбанк", "gazprombank", "gazprom bank", "банк гпб", "gpb bank")),
    ("mars", "svg", "#0000A0", ("mars incorporated", "mars inc", "марс", "марс инкорпорейтед", "mars")),
    ("uralsib", "png", "#5B268B", ("уралсиб", "uralsib")),
    ("pg", "png", "#003DA5", ("procter & gamble", "procter and gamble", "p&g", "p and g")),
    # Kept last: "газпром" alone would also match the unrelated Газпромбанк/Газпром нефть
    # subsidiaries. Газпромбанк resolves above; Газпром нефть is excluded explicitly below.
    ("gazprom", "svg", "#0079C1", ("газпром",)),
]

GAZPROM_SUBSIDIARY_EXCLUSIONS = ("газпромнефть", "газпром нефть")

VACANCY_WEB_LOGO_MAP = {
    name.casefold(): record["file"]
    for name, record in json.loads(
        (Path(__file__).with_name("vacancy_web_logo_map.json")).read_text(encoding="utf-8")
    ).items()
}


def _match_company(organization: str) -> tuple[str | None, str | None, str]:
    """Return (logo_slug, logo_ext, brandColor) for an organization.

    logo_slug/logo_ext are None when there's no known local logo asset; in that
    case the brand color falls back to a stable per-name color.
    """
    normalized = organization.casefold()
    web_logo = VACANCY_WEB_LOGO_MAP.get(normalized)
    selected_logo = (
        (f"vacancy_web/{Path(web_logo).stem}", Path(web_logo).suffix.lstrip("."))
        if web_logo else None
    )
    is_gazprom_subsidiary = any(term in normalized for term in GAZPROM_SUBSIDIARY_EXCLUSIONS)

    if not is_gazprom_subsidiary:
        for slug, ext, color, aliases in COMPANY_LOGOS:
            if any(alias in normalized for alias in aliases):
                return (*selected_logo, color) if selected_logo else (slug, ext, color)

    if selected_logo:
        return *selected_logo, _brand_color(organization)
    return None, None, _brand_color(organization)

_cache: dict[str, Any] = {"expires_at": 0.0, "items": None, "loaded_at": None}


class VacancySheetError(RuntimeError):
    """Raised when Google Sheets cannot be read for the miniapp."""


def _resolve_credentials_path() -> Path:
    raw_path = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip() or "credentials.json"
    path = Path(raw_path)
    if path.is_absolute():
        return path

    project_path = PROJECT_DIR / path
    if project_path.exists():
        return project_path

    return Path.cwd() / path


def _get_spreadsheet():
    credentials_path = _resolve_credentials_path()
    if not credentials_path.exists():
        raise VacancySheetError(f"Google credentials file not found: {credentials_path}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    credentials = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    client = gspread.authorize(credentials)

    spreadsheet_url = os.getenv("GOOGLE_SHEETS_URL", "").strip()
    spreadsheet_name = os.getenv("GOOGLE_SHEET_NAME", "").strip()
    if spreadsheet_url:
        return client.open_by_url(spreadsheet_url)
    if spreadsheet_name:
        return client.open(spreadsheet_name)
    raise VacancySheetError("GOOGLE_SHEETS_URL or GOOGLE_SHEET_NAME must be configured")


def _get_value(row: dict[str, str], key: str) -> str:
    for header in HEADER_ALIASES[key]:
        value = row.get(header)
        if value is not None:
            return str(value).strip()
    return ""


def _stable_index(value: str, modulo: int) -> int:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def _brand_color(company: str) -> str:
    return BRAND_COLORS[_stable_index(company or "KVS", len(BRAND_COLORS))]


def _metro_color(value: str) -> str:
    return METRO_COLORS[_stable_index(value or "default", len(METRO_COLORS))]


def _kind(value: str) -> str:
    normalized = value.casefold()
    if "стаж" in normalized:
        return "Стажировка"
    if "вак" in normalized:
        return "Вакансия"
    return value or "Вакансия"


def _features(*values: str) -> list[str]:
    return [value for value in values if value]


def _is_faculty_checked(value: str) -> bool:
    return value.strip().casefold() in FACULTY_CHECKED_VALUES


def _faculties_for_row(row: dict[str, str]) -> list[str]:
    return [label for header, label in FACULTY_COLUMNS if _is_faculty_checked(row.get(header, ""))]


def _to_frontend_vacancy(row: dict[str, str], row_number: int) -> dict[str, Any] | None:
    organization = _get_value(row, "organization")
    title = _get_value(row, "position")
    if not organization or not title:
        return None

    division = _get_value(row, "division")
    sphere = _get_value(row, "sphere") or "Другое"
    faculties = _faculties_for_row(row)
    salary = _get_value(row, "salary")
    schedule = _get_value(row, "schedule")
    work_format = _get_value(row, "work_format")
    employment_format = _kind(_get_value(row, "employment_format"))
    description = _get_value(row, "description")
    features = _features(_get_value(row, "feature1"), _get_value(row, "feature2"), _get_value(row, "feature3"))
    vacancy_url = _get_value(row, "vacancy_url")
    logo_slug, logo_ext, brand_color = _match_company(organization)

    return {
        "id": f"sheet-{row_number}",
        "sourceRow": row_number,
        "company": {
            "id": f"company-{_stable_index(organization, 100000)}",
            "name": organization,
            "initial": organization[:1].upper() or "K",
            "brandColor": brand_color,
            "logoUrl": f"/assets/images/logos/{logo_slug}.{logo_ext}" if logo_slug else None,
            "verified": True,
        },
        "division": division,
        "title": title,
        "salary": salary,
        "metro": division or schedule,
        "metroColor": _metro_color(division or schedule or organization),
        "format": work_format,
        "kind": employment_format,
        "sphere": sphere,
        "faculties": faculties,
        "category": faculties[0] if faculties else "Без факультета",
        "experience": features[0] if features else "Без опыта",
        "description": description,
        "fullDescription": description,
        "requirements": features,
        "offer": [value for value in [salary, schedule, work_format, employment_format] if value],
        "applyUrl": vacancy_url,
    }


DB_FACULTY_COLUMNS = [
    ("itiabd", "ИТиАБД"),
    ("ioo", "ИОО"),
    ("meo", "МЭО"),
    ("feb", "ФЭБ"),
    ("snimk", "СНиМК"),
    ("nab", "НАБ"),
    ("vshu", "ВШУ"),
    ("finfak", "ФФ"),
    ("yurfak", "ЮФ"),
]


def vacancy_from_db(vacancy) -> dict[str, Any]:
    """Map a SQL Vacancy to the existing miniapp response contract."""
    organization = (vacancy.organization or "Компания").strip()
    title = (vacancy.position or "Вакансия").strip()
    division = (vacancy.division or "").strip()
    salary = (vacancy.salary or "").strip()
    schedule = (vacancy.schedule or "").strip()
    work_format = (vacancy.work_format or "").strip()
    employment_format = _kind((vacancy.employment_format or "").strip())
    description = (vacancy.description or "").strip()
    features = _features(vacancy.feature1 or "", vacancy.feature2 or "", vacancy.feature3 or "")
    faculties = [label for field, label in DB_FACULTY_COLUMNS if bool(getattr(vacancy, field, False))]
    logo_slug, logo_ext, brand_color = _match_company(organization)

    return {
        "id": f"db-{vacancy.id}",
        "sourceRow": vacancy.source_row,
        "company": {
            "id": f"company-{_stable_index(organization, 100000)}",
            "name": organization,
            "initial": organization[:1].upper() or "K",
            "brandColor": brand_color,
            "logoUrl": f"/assets/images/logos/{logo_slug}.{logo_ext}" if logo_slug else None,
            "verified": True,
        },
        "division": division,
        "title": title,
        "salary": salary,
        "metro": division or schedule,
        "metroColor": _metro_color(division or schedule or organization),
        "format": work_format,
        "kind": employment_format,
        "sphere": (vacancy.sphere or "Другое").strip(),
        "faculties": faculties,
        "category": faculties[0] if faculties else "Без факультета",
        "experience": features[0] if features else "Без опыта",
        "description": description,
        "fullDescription": description,
        "requirements": features,
        "offer": [value for value in [salary, schedule, work_format, employment_format] if value],
        "applyUrl": (vacancy.vacancy_url or "").strip(),
    }


def _rows_from_sheet() -> list[dict[str, str]]:
    spreadsheet = _get_spreadsheet()
    sheet = spreadsheet.sheet1
    values = sheet.get_all_values()
    if len(values) < 3:
        return []

    headers = [header.strip() for header in values[1]]
    rows: list[dict[str, str]] = []
    for row_index, raw_row in enumerate(values[2:], start=3):
        mapped = {
            header: raw_row[index].strip() if index < len(raw_row) else ""
            for index, header in enumerate(headers)
            if header
        }
        mapped["_row_number"] = str(row_index)
        rows.append(mapped)
    return rows


def load_vacancies_from_google_sheet(force_refresh: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    now = time.monotonic()
    if not force_refresh and _cache["items"] is not None and now < _cache["expires_at"]:
        return list(_cache["items"]), _cache["loaded_at"]

    items = []
    for row in _rows_from_sheet():
        item = _to_frontend_vacancy(row, int(row["_row_number"]))
        if item:
            items.append(item)

    loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _cache.update({
        "items": items,
        "loaded_at": loaded_at,
        "expires_at": now + SHEET_CACHE_TTL_SECONDS,
    })
    return list(items), loaded_at


def filter_vacancies(items: list[dict[str, Any]], query: str = "", category: str = "Все") -> list[dict[str, Any]]:
    normalized_query = query.strip().casefold()
    normalized_category = category.strip()

    def matches(item: dict[str, Any]) -> bool:
        if normalized_category and normalized_category != "Все" and normalized_category not in item.get("faculties", []):
            return False
        if not normalized_query:
            return True
        haystack = " ".join(
            str(value)
            for value in [
                item["title"],
                item["company"]["name"],
                item.get("division", ""),
                item["salary"],
                item["format"],
                item["kind"],
                item.get("sphere", ""),
                *item.get("faculties", []),
                item["description"],
            ]
        ).casefold()
        return normalized_query in haystack

    return [item for item in items if matches(item)]


def build_categories(items: list[dict[str, Any]]) -> list[str]:
    # Faculty order mirrors the bot's own faculty menu (config.py FACULTIES),
    # not an alphabetical sort, so the chips line up with what students expect.
    present = {label for item in items for label in item.get("faculties", [])}
    ordered = [label for _, label in FACULTY_COLUMNS if label in present]
    return ["Все", *ordered]
