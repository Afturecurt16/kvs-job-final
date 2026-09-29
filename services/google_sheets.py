from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
import gspread
from google.oauth2.service_account import Credentials
from config import EVENTS_GOOGLE_SHEETS_URL, GOOGLE_CREDENTIALS_FILE, GOOGLE_SHEET_NAME, GOOGLE_SHEETS_URL, VACANCY_SYNC_ALLOW_EMPTY
from database.models import Vacancy, Company, Division
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from services.image_generator import sync_vacancy_image_cache
from datetime import datetime
from services.company_utils import clean_company_name, normalize_company_name

logger = logging.getLogger(__name__)
_vacancy_sync_lock = asyncio.Lock()


class VacancySyncError(RuntimeError):
    """Raised when a source snapshot is unsafe to apply to PostgreSQL."""

SHEET_HEADERS = [
    "Организация",
    "Подразделение",
    "Вакансия",
    "Сфера",
    "ЗП",
    "График",
    "Формат",
    "Описание",
    "Формат трудоустройства",
    "Особенность 1",
    "Особенность 2",
    "Особенность 3",
    "ИТиАБД",
    "ИОО",
    "ФинФак",
    "ВШУ",
    "НАБ",
    "СНиМК",
    "МЭО",
    "ФЭБ",
    "ЮрФак",
    "Ссылка на вакансию",
]

COMPANIES_SHEET_TITLE = "Компании"
DIVISIONS_SHEET_TITLE = "Подразделения"

COMPANY_HEADERS = ["Компания", "Описание"]
DIVISION_HEADERS = ["Компания", "Подразделение", "Описание"]

EVENT_REGISTRATIONS_SHEET_TITLE = "Участники"
EVENT_REGISTRATION_HEADERS = [
    "Статус",
    "Позиция",
    "Username",
    "Имя",
    "Фамилия",
    "Отчество",
    "Курс",
    "Факультет",
    "Источник",
    "Дата записи на мероприятие",
]

FACULTY_SHEET_TO_DB = {
    "ИТиАБД": "itiabd",
    "ИОО": "ioo",
    "ФинФак": "finfak",
    "ВШУ": "vshu",
    "НАБ": "nab",
    "СНиМК": "snimk",
    "МЭО": "meo",
    "ФЭБ": "feb",
    "ЮрФак": "yurfak",
}


def _safe_print(message: str) -> None:
    """Print logs without crashing on consoles that cannot encode emoji."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sanitized = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(sanitized)


def _column_number_to_letter(column_number: int) -> str:
    """Convert a 1-based column number to Excel column letters."""
    letters = []
    while column_number > 0:
        column_number, remainder = divmod(column_number - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _sheet_last_column() -> str:
    """Return the letter of the last configured vacancy column."""
    return _column_number_to_letter(len(SHEET_HEADERS))


def _event_sheet_last_column() -> str:
    """Return the letter of the last configured event-registration column."""
    return _column_number_to_letter(len(EVENT_REGISTRATION_HEADERS))


def _clean_spreadsheet_title(value: str) -> str:
    """Sanitize spreadsheet titles for Google Drive."""
    invalid_chars = '\\/:?*[]'
    cleaned = "".join(" " if char in invalid_chars else char for char in (value or "").strip())
    cleaned = " ".join(cleaned.split())
    return cleaned[:100] or "Мероприятие"


def _build_event_spreadsheet_title(event_id: int, title: str) -> str:
    """Build a spreadsheet title for a single event."""
    return _clean_spreadsheet_title(f"Мероприятие {event_id} - {title}")


def _format_datetime(value: datetime | None) -> str:
    """Format datetimes for spreadsheet export."""
    if not value:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _ensure_sheet_headers(sheet) -> None:
    """Make sure the vacancy headers exist in the second row."""
    existing_headers = sheet.row_values(2)
    if existing_headers[: len(SHEET_HEADERS)] != SHEET_HEADERS:
        sheet.update(values=[SHEET_HEADERS], range_name="A2")


def ensure_vacancy_sheet_headers() -> bool:
    """Ensure the vacancy worksheet contains the latest header set."""
    spreadsheet = get_google_spreadsheet()
    if not spreadsheet:
        _safe_print("⚠️ Не удалось подключиться к Google Sheets для обновления заголовков вакансий")
        return False

    _ensure_sheet_headers(spreadsheet.sheet1)
    _safe_print("✅ Заголовки листа вакансий актуализированы")
    return True


def _clear_sheet_data_rows(sheet) -> None:
    """Clear existing vacancy rows without touching header rows."""
    all_values = sheet.get_all_values()
    if len(all_values) <= 2:
        return
    sheet.batch_clear([f"A3:{_sheet_last_column()}{len(all_values)}"])


def _ensure_headers(sheet, headers: list[str], header_row: int = 1) -> None:
    """Ensure the worksheet contains the expected headers."""
    existing_headers = sheet.row_values(header_row)
    if existing_headers[: len(headers)] != headers:
        sheet.update(values=[headers], range_name=f"A{header_row}")


def _clear_worksheet_data_rows(sheet, last_column_letter: str, data_start_row: int) -> None:
    """Clear worksheet rows below the header."""
    all_values = sheet.get_all_values()
    if len(all_values) < data_start_row:
        return
    sheet.batch_clear([f"A{data_start_row}:{last_column_letter}{len(all_values)}"])


def _vacancy_row_to_db_payload(vacancy_data: dict[str, str]) -> dict:
    """Convert one Google Sheets row into Vacancy kwargs."""
    payload = {
        "organization": vacancy_data.get("Организация", "").strip(),
        "division": vacancy_data.get("Подразделение", "").strip(),
        "position": vacancy_data.get("Вакансия", "").strip(),
        "sphere": vacancy_data.get("Сфера", "").strip(),
        "salary": vacancy_data.get("ЗП", "").strip(),
        "schedule": vacancy_data.get("График", "").strip(),
        "work_format": vacancy_data.get("Формат", "").strip(),
        "description": vacancy_data.get("Описание", "").strip(),
        "vacancy_url": vacancy_data.get("Ссылка на вакансию", "").strip(),
        "employment_format": vacancy_data.get("Формат трудоустройства", "").strip(),
        "feature1": vacancy_data.get("Особенность 1", "").strip(),
        "feature2": vacancy_data.get("Особенность 2", "").strip(),
        "feature3": vacancy_data.get("Особенность 3", "").strip(),
    }
    for sheet_name, db_field in FACULTY_SHEET_TO_DB.items():
        payload[db_field] = _parse_faculty_field(vacancy_data.get(sheet_name, ""))
    return payload


def _bool_to_sheet_value(value: bool | None) -> str:
    """Convert boolean DB values to human-readable sheet values."""
    return "Да" if value else ""


def _vacancy_to_sheet_row(vacancy: Vacancy) -> list[str]:
    """Convert one Vacancy ORM object into Google Sheets row values."""
    return [
        vacancy.organization or "",
        vacancy.division or "",
        vacancy.position or "",
        vacancy.sphere or "",
        vacancy.salary or "",
        vacancy.schedule or "",
        vacancy.work_format or "",
        vacancy.description or "",
        vacancy.employment_format or "",
        vacancy.feature1 or "",
        vacancy.feature2 or "",
        vacancy.feature3 or "",
        _bool_to_sheet_value(vacancy.itiabd),
        _bool_to_sheet_value(vacancy.ioo),
        _bool_to_sheet_value(vacancy.finfak),
        _bool_to_sheet_value(vacancy.vshu),
        _bool_to_sheet_value(vacancy.nab),
        _bool_to_sheet_value(vacancy.snimk),
        _bool_to_sheet_value(vacancy.meo),
        _bool_to_sheet_value(vacancy.feb),
        _bool_to_sheet_value(vacancy.yurfak),
        vacancy.vacancy_url or "",
    ]


async def _sync_companies_and_divisions(session: AsyncSession, vacancies_data: list[dict]) -> tuple[int, int]:
    """Backfill companies and divisions from synced vacancies without touching descriptions."""
    organizations = sorted(
        {clean_company_name(item["organization"]) for item in vacancies_data if clean_company_name(item.get("organization"))}
    )
    if not organizations:
        return 0, 0

    existing_companies_result = await session.execute(
        select(Company).where(Company.name.isnot(None), Company.name != "")
    )
    companies_by_name = {
        normalize_company_name(company.name): company
        for company in existing_companies_result.scalars().all()
        if normalize_company_name(company.name)
    }

    created_companies = 0
    for organization in organizations:
        normalized_name = normalize_company_name(organization)
        if normalized_name not in companies_by_name:
            company = Company(name=organization, description=None)
            session.add(company)
            companies_by_name[normalized_name] = company
            created_companies += 1

    if created_companies:
        await session.flush()

    company_ids = [company.id for company in companies_by_name.values() if company.id is not None]
    if not company_ids:
        return created_companies, 0

    existing_divisions_result = await session.execute(
        select(Division).where(Division.company_id.in_(company_ids))
    )
    existing_divisions = {
        (division.company_id, division.name)
        for division in existing_divisions_result.scalars().all()
    }

    created_divisions = 0
    division_pairs = sorted(
        {
            (clean_company_name(item["organization"]), item["division"])
            for item in vacancies_data
            if clean_company_name(item.get("organization")) and item.get("division")
        }
    )
    for organization, division_name in division_pairs:
        company = companies_by_name.get(normalize_company_name(organization))
        if not company or company.id is None:
            continue
        division_key = (company.id, division_name)
        if division_key in existing_divisions:
            continue
        session.add(Division(company_id=company.id, name=division_name, description=None))
        existing_divisions.add(division_key)
        created_divisions += 1

    return created_companies, created_divisions


def get_google_spreadsheet():
    """Подключение к Google Sheets - тот же метод что в генераторе"""
    _safe_print("🔗 Подключение к Google Sheets...")
    
    # Проверяем наличие credentials
    if not GOOGLE_CREDENTIALS_FILE:
        _safe_print("❌ GOOGLE_CREDENTIALS_FILE не указан")
        return None
    
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        _safe_print(f"❌ Файл {GOOGLE_CREDENTIALS_FILE} не найден")
        return None
    
    try:
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=scopes
        )
        client = gspread.authorize(creds)
        
        # Пробуем разные способы открытия таблицы
        spreadsheet = None
        if GOOGLE_SHEETS_URL:
            _safe_print(f"📎 Открываю по URL: {GOOGLE_SHEETS_URL[:60]}...")
            spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
        elif GOOGLE_SHEET_NAME:
            _safe_print(f"📎 Открываю по имени: {GOOGLE_SHEET_NAME}")
            spreadsheet = client.open(GOOGLE_SHEET_NAME)
        else:
            _safe_print("❌ Не указаны GOOGLE_SHEETS_URL или GOOGLE_SHEET_NAME")
            return None
        
        sheet = spreadsheet.sheet1
        _safe_print(f"✅ Подключено к таблице: {spreadsheet.title}")
        return spreadsheet
        
    except Exception as e:
        _safe_print(f"❌ Ошибка подключения: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_google_sheet():
    """Return the first worksheet with vacancies."""
    spreadsheet = get_google_spreadsheet()
    if not spreadsheet:
        return None
    return spreadsheet.sheet1


def get_google_client():
    """Return an authorized Google Sheets client."""
    if not GOOGLE_CREDENTIALS_FILE:
        return None

    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=scopes,
    )
    return gspread.authorize(creds)


def get_events_google_spreadsheet():
    """Return the shared spreadsheet used for event registrations."""
    client = get_google_client()
    if client is None or not EVENTS_GOOGLE_SHEETS_URL:
        return None

    return client.open_by_url(EVENTS_GOOGLE_SHEETS_URL)


def get_or_create_worksheet(spreadsheet, title: str, rows: int = 1000, cols: int = 10):
    """Return an existing worksheet or create it if missing."""
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def ensure_event_spreadsheet(event: Event) -> tuple[str | None, str | None]:
    """Create or update a dedicated worksheet for one event."""
    spreadsheet = get_events_google_spreadsheet()
    if spreadsheet is None:
        return None, None

    worksheet_title = _build_event_spreadsheet_title(event.id, event.title)
    worksheet = None
    if event.spreadsheet_id:
        for existing_worksheet in spreadsheet.worksheets():
            if str(existing_worksheet.id) == str(event.spreadsheet_id):
                worksheet = existing_worksheet
                break

    if worksheet is None:
        try:
            worksheet = spreadsheet.worksheet(worksheet_title)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=worksheet_title,
                rows=2000,
                cols=len(EVENT_REGISTRATION_HEADERS),
            )
    elif worksheet.title != worksheet_title:
        worksheet.update_title(worksheet_title)

    _ensure_headers(worksheet, EVENT_REGISTRATION_HEADERS, header_row=1)
    worksheet_url = f"{spreadsheet.url}#gid={worksheet.id}"
    return str(worksheet.id), worksheet_url


def delete_event_spreadsheet(event: Event) -> None:
    """Delete the dedicated worksheet linked to an event."""
    if not event.spreadsheet_id:
        return

    spreadsheet = get_events_google_spreadsheet()
    if spreadsheet is None:
        return

    for worksheet in spreadsheet.worksheets():
        if str(worksheet.id) == str(event.spreadsheet_id):
            try:
                spreadsheet.del_worksheet(worksheet)
            except Exception:
                pass
            break


async def export_event_registrations_to_sheet(session: AsyncSession, event: Event) -> int:
    """Export one event registration list to its dedicated worksheet."""
    worksheet_id, worksheet_url = ensure_event_spreadsheet(event)
    if not worksheet_id:
        return 0

    event.spreadsheet_id = worksheet_id
    event.spreadsheet_url = worksheet_url

    spreadsheet = get_events_google_spreadsheet()
    if spreadsheet is None:
        return 0

    worksheet = None
    for existing_worksheet in spreadsheet.worksheets():
        if str(existing_worksheet.id) == str(worksheet_id):
            worksheet = existing_worksheet
            break
    if worksheet is None:
        worksheet = get_or_create_worksheet(
            spreadsheet,
            _build_event_spreadsheet_title(event.id, event.title),
            rows=2000,
            cols=len(EVENT_REGISTRATION_HEADERS),
        )
    _ensure_headers(worksheet, EVENT_REGISTRATION_HEADERS, header_row=1)
    _clear_worksheet_data_rows(worksheet, _event_sheet_last_column(), data_start_row=2)

    result = await session.execute(
        select(EventRegistration, User)
        .join(User, User.id == EventRegistration.user_id)
        .where(EventRegistration.event_id == event.id)
        .order_by(EventRegistration.created_at.asc(), EventRegistration.id.asc())
    )
    registrations = result.all()

    main_position = 0
    reserve_position = 0
    rows_to_write: list[list[str]] = []
    for registration, user in registrations:
        if registration.status == "main":
            main_position += 1
            status_label = "Основной список"
            position = str(main_position)
        else:
            reserve_position += 1
            status_label = "Резерв"
            position = str(reserve_position)

        rows_to_write.append(
            [
                status_label,
                position,
                f"@{user.username}" if user.username else "",
                user.first_name or "",
                user.last_name or "",
                user.patronymic or "",
                str(user.course or ""),
                user.faculty or "",
                user.info_source or "",
                _format_datetime(registration.created_at),
            ]
        )

    if rows_to_write:
        worksheet.update(
            values=rows_to_write,
            range_name=f"A2:{_event_sheet_last_column()}{len(rows_to_write) + 1}",
        )

    return len(rows_to_write)


async def sync_company_reference_data_from_sheets(
    session: AsyncSession,
    spreadsheet=None,
) -> tuple[int, int, int, int]:
    """Import companies and divisions from dedicated Google Sheets worksheets."""
    if spreadsheet is None:
        spreadsheet = get_google_spreadsheet()
    if not spreadsheet:
        return 0, 0, 0, 0

    companies_sheet = get_or_create_worksheet(spreadsheet, COMPANIES_SHEET_TITLE, rows=1000, cols=5)
    divisions_sheet = get_or_create_worksheet(spreadsheet, DIVISIONS_SHEET_TITLE, rows=2000, cols=5)
    _ensure_headers(companies_sheet, COMPANY_HEADERS, header_row=1)
    _ensure_headers(divisions_sheet, DIVISION_HEADERS, header_row=1)

    existing_companies = (
        await session.execute(select(Company).where(Company.name.isnot(None), Company.name != "").order_by(Company.name))
    ).scalars().all()
    companies_by_name = {
        normalize_company_name(company.name): company
        for company in existing_companies
        if normalize_company_name(company.name)
    }

    created_companies = 0
    updated_companies = 0
    company_rows = companies_sheet.get_all_values()[1:]
    for row in company_rows:
        company_name = clean_company_name(row[0] if len(row) > 0 else "")
        description = (row[1] if len(row) > 1 else "").strip() or None
        normalized_name = normalize_company_name(company_name)
        if not normalized_name:
            continue

        company = companies_by_name.get(normalized_name)
        if company is None:
            company = Company(name=company_name, description=description)
            session.add(company)
            companies_by_name[normalized_name] = company
            created_companies += 1
            continue

        changed = False
        if company.name != company_name:
            company.name = company_name
            changed = True
        if (company.description or None) != description:
            company.description = description
            changed = True
        if changed:
            updated_companies += 1

    if created_companies:
        await session.flush()

    existing_companies = (
        await session.execute(select(Company).where(Company.name.isnot(None), Company.name != ""))
    ).scalars().all()
    companies_by_name = {
        normalize_company_name(company.name): company
        for company in existing_companies
        if normalize_company_name(company.name)
    }
    companies_by_id = {company.id: company for company in existing_companies if company.id is not None}

    existing_divisions = (
        await session.execute(select(Division).where(Division.name.isnot(None), Division.name != ""))
    ).scalars().all()
    divisions_by_key = {}
    for division in existing_divisions:
        company = companies_by_id.get(division.company_id)
        if not company:
            continue
        division_key = (company.id, clean_company_name(division.name).casefold())
        divisions_by_key[division_key] = division

    created_divisions = 0
    updated_divisions = 0
    division_rows = divisions_sheet.get_all_values()[1:]
    for row in division_rows:
        company_name = clean_company_name(row[0] if len(row) > 0 else "")
        division_name = clean_company_name(row[1] if len(row) > 1 else "")
        description = (row[2] if len(row) > 2 else "").strip() or None
        normalized_company_name = normalize_company_name(company_name)
        if not normalized_company_name or not division_name:
            continue

        company = companies_by_name.get(normalized_company_name)
        if company is None:
            company = Company(name=company_name, description=None)
            session.add(company)
            await session.flush()
            companies_by_name[normalized_company_name] = company
            companies_by_id[company.id] = company
            created_companies += 1

        division_key = (company.id, division_name.casefold())
        division = divisions_by_key.get(division_key)
        if division is None:
            division = Division(company_id=company.id, name=division_name, description=description)
            session.add(division)
            divisions_by_key[division_key] = division
            created_divisions += 1
            continue

        changed = False
        if division.name != division_name:
            division.name = division_name
            changed = True
        if (division.description or None) != description:
            division.description = description
            changed = True
        if changed:
            updated_divisions += 1

    return created_companies, updated_companies, created_divisions, updated_divisions


async def export_company_reference_data_to_sheets(session: AsyncSession, spreadsheet=None) -> tuple[int, int]:
    """Export companies and divisions from SQL into dedicated Google Sheets worksheets."""
    if spreadsheet is None:
        spreadsheet = get_google_spreadsheet()
    if not spreadsheet:
        return 0, 0

    companies_sheet = get_or_create_worksheet(spreadsheet, COMPANIES_SHEET_TITLE, rows=1000, cols=5)
    divisions_sheet = get_or_create_worksheet(spreadsheet, DIVISIONS_SHEET_TITLE, rows=2000, cols=5)
    _ensure_headers(companies_sheet, COMPANY_HEADERS, header_row=1)
    _ensure_headers(divisions_sheet, DIVISION_HEADERS, header_row=1)
    _clear_worksheet_data_rows(companies_sheet, "B", data_start_row=2)
    _clear_worksheet_data_rows(divisions_sheet, "C", data_start_row=2)

    companies = (
        await session.execute(select(Company).where(Company.name.isnot(None), Company.name != "").order_by(Company.name))
    ).scalars().all()
    company_rows = [[clean_company_name(company.name), company.description or ""] for company in companies]
    if company_rows:
        companies_sheet.update(values=company_rows, range_name=f"A2:B{len(company_rows) + 1}")

    companies_by_id = {company.id: company for company in companies if company.id is not None}
    divisions = (
        await session.execute(select(Division).where(Division.name.isnot(None), Division.name != "").order_by(Division.company_id, Division.name))
    ).scalars().all()
    division_rows = []
    for division in divisions:
        company = companies_by_id.get(division.company_id)
        if not company:
            continue
        division_rows.append(
            [
                clean_company_name(company.name),
                clean_company_name(division.name),
                division.description or "",
            ]
        )
    if division_rows:
        divisions_sheet.update(values=division_rows, range_name=f"A2:C{len(division_rows) + 1}")

    return len(company_rows), len(division_rows)


def parse_vacancies_from_sheet(sheet) -> list[dict]:
    """Парсинг вакансий из Google таблицы"""
    try:
        # Получаем заголовки из 2 строки (у пользователя такая структура)
        _ensure_sheet_headers(sheet)
        headers = sheet.row_values(2)
        _safe_print(f"📋 Заголовки ({len(headers)}): {headers[:5]}...")
        
        if not headers or len(headers) < 5:
            _safe_print("❌ Заголовки не найдены или их слишком мало")
            return []
        
        # Получаем все данные
        all_values = sheet.get_all_values()
        _safe_print(f"📊 Всего строк в таблице: {len(all_values)}")
        
        # Данные начинаются с 3 строки (индекс 2)
        data_rows = all_values[2:] if len(all_values) > 2 else []
        _safe_print(f"📊 Строк с данными: {len(data_rows)}")
        
        if not data_rows:
            _safe_print("⚠️ Нет данных для парсинга (строки 3+)")
            return []
        
        vacancies = []
        for row_idx, row in enumerate(data_rows):
            # Пропускаем пустые строки
            if not row or not row[0] or not row[0].strip():
                continue
            
            # Создаем словарь из строки
            vacancy_data = {}
            for i, header in enumerate(headers):
                if i < len(row):
                    vacancy_data[header] = row[i]
                else:
                    vacancy_data[header] = ""
            
            # Преобразуем в структуру для БД
            vacancy = {
                "organization": vacancy_data.get("Организация", "").strip(),
                "division": vacancy_data.get("Подразделение", "").strip(),
                "position": vacancy_data.get("Вакансия", "").strip(),
                "sphere": vacancy_data.get("Сфера", "").strip(),
                "salary": vacancy_data.get("ЗП", "").strip(),
                "schedule": vacancy_data.get("График", "").strip(),
                "work_format": vacancy_data.get("Формат", "").strip(),
                "description": vacancy_data.get("Описание", "").strip(),
                "employment_format": vacancy_data.get("Формат трудоустройства", "").strip(),
                "feature1": vacancy_data.get("Особенность 1", "").strip(),
                "feature2": vacancy_data.get("Особенность 2", "").strip(),
                "feature3": vacancy_data.get("Особенность 3", "").strip(),
                "itiabd": _parse_faculty_field(vacancy_data.get("ИТиАБД", "")),
                "ioo": _parse_faculty_field(vacancy_data.get("ИОО", "")),
                "finfak": _parse_faculty_field(vacancy_data.get("ФинФак", "")),
                "vshu": _parse_faculty_field(vacancy_data.get("ВШУ", "")),
                "nab": _parse_faculty_field(vacancy_data.get("НАБ", "")),
                "snimk": _parse_faculty_field(vacancy_data.get("СНиМК", "")),
                "meo": _parse_faculty_field(vacancy_data.get("МЭО", "")),
                "feb": _parse_faculty_field(vacancy_data.get("ФЭБ", "")),
                "yurfak": _parse_faculty_field(vacancy_data.get("Юрфак", "")),
            }
            
            # Пропускаем вакансии без организации или позиции
            if vacancy["organization"] and vacancy["position"]:
                vacancies.append(vacancy)
        
        _safe_print(f"✅ Распознано вакансий: {len(vacancies)}")
        return vacancies
        
    except Exception as e:
        _safe_print(f"❌ Ошибка парсинга: {e}")
        import traceback
        traceback.print_exc()
        return []


def _parse_faculty_field(value: str) -> bool:
    """Парсинг поля факультета"""
    if not value:
        return False
    value_lower = str(value).lower().strip()
    return value_lower in ['да', 'yes', '1', 'x', '✓', 'true', 'т', '+']


# Класс для обратной совместимости
def parse_vacancies_from_sheet(sheet, *, strict: bool = False) -> list[dict]:
    """Parse vacancies from Google Sheets using the canonical header mapping."""
    try:
        _ensure_sheet_headers(sheet)
        headers = sheet.row_values(2)
        _safe_print(f"Headers ({len(headers)}): {headers[:5]}...")

        if not headers or len(headers) < 5:
            _safe_print("Headers are missing or too short")
            return []

        all_values = sheet.get_all_values()
        _safe_print(f"Total rows in sheet: {len(all_values)}")

        data_rows = all_values[2:] if len(all_values) > 2 else []
        _safe_print(f"Rows with data: {len(data_rows)}")

        vacancies = []
        for source_row, row in enumerate(data_rows, start=3):
            if not row or not row[0] or not row[0].strip():
                continue

            vacancy_data = {}
            for index, header in enumerate(headers):
                vacancy_data[header] = row[index] if index < len(row) else ""

            vacancy = _vacancy_row_to_db_payload(vacancy_data)
            if vacancy["organization"] and vacancy["position"]:
                vacancy["_source_row"] = source_row
                vacancies.append(vacancy)

        _safe_print(f"Parsed vacancies: {len(vacancies)}")
        return vacancies

    except Exception as e:
        _safe_print(f"Sheet parsing error: {e}")
        import traceback
        traceback.print_exc()
        if strict:
            raise VacancySyncError(f"Failed to parse vacancy sheet: {e}") from e
        return []


class GoogleSheetsParser:
    def __init__(self):
        self.sheet = None
        
    def connect(self):
        self.sheet = get_google_sheet()
        return self.sheet is not None
    
    def parse_vacancies(self) -> list[dict]:
        if not self.sheet:
            if not self.connect():
                return []
        return parse_vacancies_from_sheet(self.sheet)


def _vacancy_source_key(payload: dict) -> str:
    vacancy_url = (payload.get("vacancy_url") or "").strip().casefold()
    if vacancy_url:
        identity = f"url:{vacancy_url}"
    else:
        identity = "|".join(
            (payload.get(field) or "").strip().casefold()
            for field in ("organization", "division", "position", "employment_format")
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _load_vacancy_snapshot() -> list[dict]:
    """Read and validate the complete source snapshot in a worker thread."""
    spreadsheet = get_google_spreadsheet()
    if spreadsheet is None:
        raise VacancySyncError("Google Sheets is unavailable")
    vacancies = parse_vacancies_from_sheet(spreadsheet.sheet1, strict=True)
    if not vacancies and not VACANCY_SYNC_ALLOW_EMPTY:
        raise VacancySyncError(
            "The source returned zero vacancies; the previous snapshot was preserved"
        )

    deduplicated: dict[str, dict] = {}
    for payload in vacancies:
        source_key = _vacancy_source_key(payload)
        payload["source_key"] = source_key
        deduplicated[source_key] = payload
    return list(deduplicated.values())


VACANCY_SYNC_FIELDS = (
    "organization", "division", "position", "sphere", "salary", "schedule",
    "work_format", "description", "vacancy_url", "employment_format",
    "feature1", "feature2", "feature3", "itiabd", "ioo", "finfak", "vshu",
    "nab", "snimk", "meo", "feb", "yurfak",
)


async def sync_vacancies_to_db_with_stats(
    session: AsyncSession,
    clear_existing: bool = True,
) -> dict[str, int]:
    """Atomically apply a validated snapshot without blocking the bot event loop."""
    async with _vacancy_sync_lock:
        vacancies_data = await asyncio.to_thread(_load_vacancy_snapshot)
        existing = (await session.execute(select(Vacancy))).scalars().all()
        existing_by_key = {
            vacancy.source_key: vacancy for vacancy in existing if vacancy.source_key
        }
        source_keys = {payload["source_key"] for payload in vacancies_data}

        added = 0
        updated = 0
        for payload in vacancies_data:
            source_key = payload["source_key"]
            source_row = int(payload.get("_source_row") or 0) or None
            vacancy = existing_by_key.get(source_key)
            if vacancy is None:
                values = {field: payload.get(field) for field in VACANCY_SYNC_FIELDS}
                session.add(Vacancy(
                    source_key=source_key,
                    source_row=source_row,
                    **values,
                ))
                added += 1
                continue

            changed = vacancy.source_row != source_row
            vacancy.source_row = source_row
            for field in VACANCY_SYNC_FIELDS:
                value = payload.get(field)
                if getattr(vacancy, field) != value:
                    setattr(vacancy, field, value)
                    changed = True
            if changed:
                updated += 1

        deleted = 0
        if clear_existing:
            for vacancy in existing:
                if not vacancy.source_key or vacancy.source_key not in source_keys:
                    await session.delete(vacancy)
                    deleted += 1

        await _sync_companies_and_divisions(session, vacancies_data)
        await session.commit()

    try:
        cache_stats = await sync_vacancy_image_cache()
        logger.info("Vacancy image cache refreshed after database sync: %s", cache_stats)
    except Exception:
        # Image cards are a secondary presentation optimization. Their failure
        # must not roll back the already committed SQL snapshot.
        logger.exception("Vacancies updated, but image cache refresh failed")

    stats = {
        "source": len(vacancies_data),
        "added": added,
        "updated": updated,
        "deleted": deleted,
    }
    logger.info("Vacancy snapshot applied: %s", stats)
    return stats


async def sync_vacancies_to_db(session: AsyncSession, clear_existing: bool = True):
    """Backward-compatible entry point used by existing admin commands."""
    stats = await sync_vacancies_to_db_with_stats(session, clear_existing)
    return stats["source"]


async def sync_vacancies_to_sheet(session: AsyncSession, clear_existing: bool = True) -> int:
    """Synchronize vacancies from SQL back to Google Sheets."""
    _safe_print("\n" + "=" * 50)
    _safe_print("EXPORT VACANCIES TO GOOGLE SHEETS")
    _safe_print("=" * 50)

    spreadsheet = get_google_spreadsheet()
    if not spreadsheet:
        _safe_print("Failed to connect to Google Sheets")
        return 0
    sheet = spreadsheet.sheet1

    _ensure_sheet_headers(sheet)
    if clear_existing:
        _clear_sheet_data_rows(sheet)

    vacancies_result = await session.execute(select(Vacancy).order_by(Vacancy.created_at.desc(), Vacancy.id.desc()))
    vacancies = vacancies_result.scalars().all()
    if not vacancies:
        _safe_print("No vacancies in SQL for export")
        exported_companies, exported_divisions = await export_company_reference_data_to_sheets(session, spreadsheet)
        _safe_print(f"EXPORTED COMPANIES: {exported_companies}")
        _safe_print(f"EXPORTED DIVISIONS: {exported_divisions}")
        return 0

    rows_to_write = [_vacancy_to_sheet_row(vacancy) for vacancy in vacancies]
    end_row = 2 + len(rows_to_write)
    range_name = f"A3:{_sheet_last_column()}{end_row}"
    sheet.update(values=rows_to_write, range_name=range_name)
    exported_companies, exported_divisions = await export_company_reference_data_to_sheets(session, spreadsheet)

    _safe_print("=" * 50)
    _safe_print(f"EXPORTED: {len(rows_to_write)} vacancies")
    _safe_print(f"EXPORTED COMPANIES: {exported_companies}")
    _safe_print(f"EXPORTED DIVISIONS: {exported_divisions}")
    _safe_print("=" * 50 + "\n")
    return len(rows_to_write)


async def ensure_vacancies_seeded(session: AsyncSession) -> int:
    """Load vacancies from Google Sheets once when the database is empty."""
    try:
        ensure_vacancy_sheet_headers()
    except Exception as exc:
        _safe_print(f"⚠️ Не удалось обновить заголовки листа вакансий: {exc}")

    existing_count = (await session.execute(select(func.count(Vacancy.id)))).scalar() or 0
    if existing_count > 0:
        _safe_print(f"ℹ️ Вакансии уже загружены: {existing_count}")
        return existing_count

    _safe_print("ℹ️ База вакансий пуста, запускаю начальную синхронизацию из Google Sheets")
    return await sync_vacancies_to_db(session, clear_existing=False)
