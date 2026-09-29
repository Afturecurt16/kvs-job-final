"""Vacancy image generation and cache synchronization utilities."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from services.vacancy_defaults import (
    DEFAULT_DESCRIPTION,
    DEFAULT_SALARY,
    DEFAULT_SCHEDULE,
    DEFAULT_SPHERE,
    present_features,
    present_value,
)

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent.parent / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
FONTS_DIR = ASSETS_DIR / "fonts"
BASE_TEMPLATE_SIZE = (1280, 1280)
VACANCY_TEMPLATE_PATH = IMAGES_DIR / "vacancy_card.png"
RENDER_SIGNATURE_VERSION = "5"


def get_cache_dir() -> Path:
    """Resolve the cache directory for Docker and local runs."""
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return Path("/app/cache/images")
    return Path(__file__).parent.parent / "cache" / "images"


CACHE_DIR = get_cache_dir()
CACHE_FILE_RE = re.compile(r"^vacancy_(\d+)\.png$")

COLORS = {
    "background": "#FFFFFF",
    "accent": "#B20B13",
    "dark": "#111111",
}

LAYOUT = {
    "organization": (66, 68, 1015, 132),
    "position": (60, 124, 1045, 252),
    "salary": (124, 366, 560, 446),
    "schedule": (124, 492, 560, 572),
    "sphere": (124, 618, 560, 698),
    "description": (124, 754, 1168, 960),
}
FEATURE_NUMBER_CLEAR_BOX = (650, 370, 732, 660)
FEATURE_NUMBER_COLUMN = (662, 0, 726, 0)
FEATURE_TEXT_COLUMN = (742, 0, 1230, 0)
FEATURE_TOP = 378
FEATURE_ROW_HEIGHT = 72
FEATURE_ROW_BOX_HEIGHT = 60


def _font_candidates(*names: str) -> list[Path]:
    """Return possible font file locations in project assets and system fonts."""
    search_dirs = [
        FONTS_DIR,
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts/truetype"),
        Path("/usr/share/fonts/TTF"),
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
    ]
    candidates: list[Path] = []
    for directory in search_dirs:
        for name in names:
            candidates.append(directory / name)
    return candidates


def _load_font(candidates: list[Path], size: int, fallback_bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load the first available font from candidates with a sane fallback."""
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue

    fallback_candidates = _font_candidates(
        "arialbd.ttf" if fallback_bold else "arial.ttf",
        "DejaVuSans-Bold.ttf" if fallback_bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if fallback_bold else "LiberationSans-Regular.ttf",
    )
    for path in fallback_candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue

    return ImageFont.load_default()


def get_prosto_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Prosto Sans Bold or fallback."""
    return _load_font(
        _font_candidates(
            "ProstoSans-Bold.ttf",
            "ProstoSans-Bold.otf",
            "Prosto Sans Bold.ttf",
            "Prosto Sans Bold.otf",
        ),
        size,
        fallback_bold=True,
    )


def get_nozhik_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Nozhik Bold or fallback."""
    return _load_font(
        _font_candidates(
            "Nozhik-Bold.ttf",
            "Nozhik-Bold.otf",
            "Nozhik Bold.ttf",
            "Nozhik Bold.otf",
            "Nozhik.ttf",
            "Nozhik.otf",
        ),
        size,
        fallback_bold=True,
    )


def get_qanelas_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Qanelas or fallback."""
    return _load_font(
        _font_candidates(
            "QanelasDEMO-Black.otf",
            "QanelasDEMO-Black.ttf",
            "Qanelas-Regular.ttf",
            "Qanelas-Regular.otf",
            "Qanelas Medium.ttf",
            "Qanelas Medium.otf",
            "Qanelas-Bold.ttf",
            "Qanelas-Bold.otf",
        ),
        size,
        fallback_bold=False,
    )


def scale_box(box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Scale coordinates from the reference 1280x1280 layout to the actual template size."""
    scale_x = size[0] / BASE_TEMPLATE_SIZE[0]
    scale_y = size[1] / BASE_TEMPLATE_SIZE[1]
    x1, y1, x2, y2 = box
    return (
        round(x1 * scale_x),
        round(y1 * scale_y),
        round(x2 * scale_x),
        round(y2 * scale_y),
    )


def build_feature_row_boxes(
    size: tuple[int, int],
    feature_count: int,
) -> list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """Build paired number/text boxes for each rendered feature row."""
    scale_x = size[0] / BASE_TEMPLATE_SIZE[0]
    scale_y = size[1] / BASE_TEMPLATE_SIZE[1]
    number_x1 = round(FEATURE_NUMBER_COLUMN[0] * scale_x)
    number_x2 = round(FEATURE_NUMBER_COLUMN[2] * scale_x)
    text_x1 = round(FEATURE_TEXT_COLUMN[0] * scale_x)
    text_x2 = round(FEATURE_TEXT_COLUMN[2] * scale_x)
    top = round(FEATURE_TOP * scale_y)
    row_height = round(FEATURE_ROW_HEIGHT * scale_y)
    row_box_height = round(FEATURE_ROW_BOX_HEIGHT * scale_y)

    rows: list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]] = []
    for index in range(feature_count):
        row_top = top + index * row_height
        row_bottom = row_top + row_box_height
        number_box = (number_x1, row_top, number_x2, row_bottom)
        text_box = (text_x1, row_top, text_x2, row_bottom)
        rows.append((number_box, text_box))

    return rows


def normalize_text(text: str | None, uppercase: bool = False) -> str:
    """Trim extra whitespace and optionally uppercase the value."""
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    value = "\n".join(line for line in lines if line)
    return value.upper() if uppercase else value


def format_salary_text(text: str | None) -> str:
    """Move the `до` part of salary ranges to the next line."""
    value = (text or "").strip()
    if not value:
        return ""
    return re.sub(r"\s+до\s+", "\nдо ", value, count=1, flags=re.IGNORECASE)


def contains_cyrillic(text: str) -> bool:
    """Check whether text contains Cyrillic characters."""
    return any("\u0400" <= char <= "\u04FF" for char in text)


def resolve_font_for_text(
    text: str,
    primary_font_getter,
    fallback_font_getter,
    size: int,
) -> ImageFont.FreeTypeFont:
    """Pick a fallback font when the primary asset is known to lack Cyrillic."""
    font = primary_font_getter(size)
    font_path = str(getattr(font, "path", "") or "")
    if contains_cyrillic(text) and "QanelasDEMO-Black.otf" in font_path:
        return fallback_font_getter(size)
    return font


def wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    draw: ImageDraw.Draw,
) -> list[str]:
    """Wrap text into multiple lines based on rendered width."""
    lines: list[str] = []

    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] <= max_width:
                current_line = test_line
                continue

            if current_line:
                lines.append(current_line)
            current_line = word

        if current_line:
            lines.append(current_line)

    return lines


def build_vacancy_render_data(vacancy) -> dict:
    """Collect all SQL-backed fields that are rendered into the card."""
    features = present_features(
        getattr(vacancy, "feature1", ""),
        getattr(vacancy, "feature2", ""),
        getattr(vacancy, "feature3", ""),
    )

    return {
        "organization": getattr(vacancy, "organization", "") or "Компания",
        "position": getattr(vacancy, "position", "") or "Вакансия",
        "salary": format_salary_text(present_value(getattr(vacancy, "salary", ""), DEFAULT_SALARY)),
        "schedule": present_value(getattr(vacancy, "schedule", ""), DEFAULT_SCHEDULE),
        "work_format": getattr(vacancy, "work_format", "") or "",
        "sphere": present_value(getattr(vacancy, "sphere", ""), DEFAULT_SPHERE),
        "description": present_value(getattr(vacancy, "description", ""), DEFAULT_DESCRIPTION),
        "features": features,
    }


def _measure_multiline(
    draw: ImageDraw.Draw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    spacing: int,
) -> tuple[int, int, int]:
    """Measure the actual ink bounds of a multiline text block."""
    widths: list[int] = []
    block_top: int | None = None
    block_bottom: int | None = None
    current_y = 0

    for line in lines:
        left, top, right, bottom = draw.textbbox((0, current_y), line, font=font)
        widths.append(right - left)
        block_top = top if block_top is None else min(block_top, top)
        block_bottom = bottom if block_bottom is None else max(block_bottom, bottom)
        current_y += (bottom - top) + spacing

    if block_top is None or block_bottom is None:
        return 0, 0, 0

    return max(widths, default=0), block_top, block_bottom


def draw_text_in_box(
    draw: ImageDraw.Draw,
    text: str,
    box: tuple[int, int, int, int],
    font_getter,
    fill: str,
    *,
    max_size: int,
    min_size: int,
    uppercase: bool = False,
    max_lines: int | None = None,
    spacing_ratio: float = 0.15,
    fallback_font_getter=None,
    vertical_align: str = "top",
) -> None:
    """Draw text fitted into a predefined box on the template."""
    normalized = normalize_text(text, uppercase=uppercase)
    if not normalized:
        return

    x1, y1, x2, y2 = box
    box_width = max(1, x2 - x1)
    box_height = max(1, y2 - y1)

    best_layout: tuple[ImageFont.FreeTypeFont, list[str], int, int, int] | None = None
    for size in range(max_size, min_size - 1, -2):
        if fallback_font_getter is not None:
            font = resolve_font_for_text(normalized, font_getter, fallback_font_getter, size)
        else:
            font = font_getter(size)
        spacing = max(4, round(size * spacing_ratio))
        lines = wrap_text(normalized, font, box_width, draw)
        if max_lines is not None and len(lines) > max_lines:
            continue
        width, block_top, block_bottom = _measure_multiline(draw, lines, font, spacing)
        height = block_bottom - block_top
        if width <= box_width and height <= box_height:
            best_layout = (font, lines, spacing, block_top, height)
            break

    if best_layout is None:
        if fallback_font_getter is not None:
            font = resolve_font_for_text(normalized, font_getter, fallback_font_getter, min_size)
        else:
            font = font_getter(min_size)
        spacing = max(2, round(min_size * spacing_ratio))
        lines = wrap_text(normalized, font, box_width, draw)
        if max_lines is not None:
            lines = lines[:max_lines]
        _, block_top, block_bottom = _measure_multiline(draw, lines, font, spacing)
        best_layout = (font, lines, spacing, block_top, block_bottom - block_top)

    font, lines, spacing, block_top, total_height = best_layout
    if vertical_align == "center":
        current_y = y1 + max(0, (box_height - total_height) // 2) - block_top
    else:
        current_y = y1
    for line in lines:
        draw.text((x1, current_y), line, font=font, fill=fill)
        left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
        current_y += (bottom - top) + spacing


def generate_vacancy_image(
    organization: str,
    position: str,
    salary: str = "",
    schedule: str = "",
    work_format: str = "",
    sphere: str = "",
    description: str = "",
    features: list[str] | None = None,
) -> BytesIO:
    """Generate one vacancy card using the provided PNG template."""
    if VACANCY_TEMPLATE_PATH.exists():
        img = Image.open(VACANCY_TEMPLATE_PATH).convert("RGB")
    else:
        img = Image.new("RGB", BASE_TEMPLATE_SIZE, COLORS["background"])

    draw = ImageDraw.Draw(img)
    size = img.size

    scaled_layout = {key: scale_box(box, size) for key, box in LAYOUT.items()}
    draw_text_in_box(
        draw,
        organization,
        scaled_layout["organization"],
        get_prosto_font,
        COLORS["dark"],
        max_size=96,
        min_size=40,
        uppercase=True,
        max_lines=2,
        spacing_ratio=0.04,
    )
    draw_text_in_box(
        draw,
        position,
        scaled_layout["position"],
        get_nozhik_font,
        COLORS["accent"],
        max_size=152,
        min_size=54,
        uppercase=True,
        max_lines=2,
        spacing_ratio=0.03,
    )
    draw_text_in_box(
        draw,
        salary,
        scaled_layout["salary"],
        get_prosto_font,
        COLORS["accent"],
        max_size=72,
        min_size=30,
        uppercase=True,
        max_lines=2,
        spacing_ratio=0.18,
        vertical_align="center",
    )
    draw_text_in_box(
        draw,
        schedule,
        scaled_layout["schedule"],
        get_prosto_font,
        COLORS["accent"],
        max_size=72,
        min_size=30,
        uppercase=True,
        max_lines=2,
        spacing_ratio=0.04,
        vertical_align="center",
    )
    draw_text_in_box(
        draw,
        sphere,
        scaled_layout["sphere"],
        get_prosto_font,
        COLORS["accent"],
        max_size=72,
        min_size=30,
        uppercase=True,
        max_lines=2,
        spacing_ratio=0.04,
        vertical_align="center",
    )
    draw_text_in_box(
        draw,
        description,
        scaled_layout["description"],
        get_prosto_font,
        COLORS["accent"],
        max_size=56,
        min_size=24,
        max_lines=4,
        spacing_ratio=0.06,
    )

    draw.rectangle(scale_box(FEATURE_NUMBER_CLEAR_BOX, size), fill=COLORS["background"])

    for index, (feature_text, (number_box, text_box)) in enumerate(
        zip(features or [], build_feature_row_boxes(size, len(features or []))),
        start=1,
    ):
        draw_text_in_box(
            draw,
            f"{index}.",
            number_box,
            get_prosto_font,
            COLORS["accent"],
            max_size=64,
            min_size=28,
            uppercase=True,
            max_lines=1,
            spacing_ratio=0.04,
            vertical_align="top",
        )
        draw_text_in_box(
            draw,
            feature_text,
            text_box,
            get_qanelas_font,
            COLORS["dark"],
            max_size=52,
            min_size=22,
            max_lines=2,
            spacing_ratio=0.16,
            fallback_font_getter=get_prosto_font,
            vertical_align="top",
        )

    buffer = BytesIO()
    img.save(buffer, format="PNG", quality=95)
    buffer.seek(0)
    return buffer


def generate_vacancy_card(vacancy) -> BytesIO:
    """Generate a vacancy card from the ORM object."""
    return generate_vacancy_image(**build_vacancy_render_data(vacancy))


def get_vacancy_cache_path(vacancy_id: int) -> Path:
    """Return the PNG path for one vacancy image."""
    return CACHE_DIR / f"vacancy_{vacancy_id}.png"


def get_vacancy_signature_path(vacancy_id: int) -> Path:
    """Return the sidecar signature path for one cached vacancy image."""
    return CACHE_DIR / f"vacancy_{vacancy_id}.sha256"


def ensure_cache_dir() -> None:
    """Create the image cache directory if needed."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_render_template_signature() -> str:
    """Return a cheap fingerprint for the active card template."""
    if not VACANCY_TEMPLATE_PATH.exists():
        return f"builtin:{BASE_TEMPLATE_SIZE[0]}x{BASE_TEMPLATE_SIZE[1]}"

    stat = VACANCY_TEMPLATE_PATH.stat()
    return f"template:{stat.st_size}:{stat.st_mtime_ns}"


def build_vacancy_cache_signature(vacancy) -> str:
    """Hash all fields that affect the rendered image."""
    data = build_vacancy_render_data(vacancy)
    normalized_parts = [
        RENDER_SIGNATURE_VERSION,
        get_render_template_signature(),
        str(data["organization"]).strip(),
        str(data["position"]).strip(),
        str(data["salary"]).strip(),
        str(data["schedule"]).strip(),
        str(data["work_format"]).strip(),
        str(data["sphere"]).strip(),
        str(data["description"]).strip(),
        *[str(feature).strip() for feature in data["features"]],
    ]
    payload = "\n".join(normalized_parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_vacancy_cache_signature(vacancy_id: int) -> str | None:
    """Read the cached signature if it exists."""
    signature_path = get_vacancy_signature_path(vacancy_id)
    if not signature_path.exists():
        return None
    return signature_path.read_text(encoding="utf-8").strip() or None


def write_vacancy_cache_signature(vacancy_id: int, signature: str) -> None:
    """Persist the rendered-image signature."""
    get_vacancy_signature_path(vacancy_id).write_text(signature, encoding="utf-8")


def is_cached(vacancy_id: int) -> bool:
    """Check whether a PNG exists for the vacancy."""
    return get_vacancy_cache_path(vacancy_id).exists()


def is_cache_fresh(vacancy) -> bool:
    """Check whether the cached image exists and matches current SQL data."""
    vacancy_id = getattr(vacancy, "id", None)
    if vacancy_id is None:
        return False

    cache_path = get_vacancy_cache_path(vacancy_id)
    if not cache_path.exists():
        return False

    expected_signature = build_vacancy_cache_signature(vacancy)
    cached_signature = read_vacancy_cache_signature(vacancy_id)
    return cached_signature == expected_signature


def delete_cached_vacancy(vacancy_id: int) -> None:
    """Delete cached image and its signature for a vacancy."""
    for path in (get_vacancy_cache_path(vacancy_id), get_vacancy_signature_path(vacancy_id)):
        if path.exists():
            path.unlink()


def list_cached_vacancy_ids() -> set[int]:
    """Return vacancy IDs currently present in the cache folder."""
    ensure_cache_dir()
    cached_ids: set[int] = set()
    for file in CACHE_DIR.glob("vacancy_*.png"):
        match = CACHE_FILE_RE.match(file.name)
        if match:
            cached_ids.add(int(match.group(1)))
    return cached_ids


def clear_cache() -> None:
    """Delete all cached vacancy images and signatures."""
    ensure_cache_dir()
    for file in CACHE_DIR.glob("vacancy_*.*"):
        if file.suffix.lower() in {".png", ".sha256"}:
            file.unlink()


def generate_and_cache(vacancy) -> bytes:
    """Render the vacancy image and overwrite the cache."""
    ensure_cache_dir()
    vacancy_id = getattr(vacancy, "id", None)
    if vacancy_id is None:
        raise ValueError("Vacancy must have an id before caching an image")

    image_bytes = generate_vacancy_card(vacancy).read()
    get_vacancy_cache_path(vacancy_id).write_bytes(image_bytes)
    write_vacancy_cache_signature(vacancy_id, build_vacancy_cache_signature(vacancy))
    return image_bytes


def get_cached_or_generate(vacancy) -> bytes:
    """Return a fresh cached image for a vacancy card."""
    if is_cache_fresh(vacancy):
        return get_vacancy_cache_path(vacancy.id).read_bytes()
    return generate_and_cache(vacancy)


def get_missing_cache_ids(vacancy_ids: list[int]) -> list[int]:
    """Return vacancy IDs that do not yet have a PNG in cache."""
    ensure_cache_dir()
    return [vacancy_id for vacancy_id in vacancy_ids if not is_cached(vacancy_id)]


async def sync_vacancy_image_cache(vacancies: Iterable | None = None) -> dict[str, int]:
    """Synchronize cached vacancy images with current SQL records."""
    ensure_cache_dir()

    if vacancies is None:
        from sqlalchemy import select

        from database.db import async_session_maker
        from database.models import Vacancy

        async with async_session_maker() as session:
            result = await session.execute(select(Vacancy))
            vacancy_list = result.scalars().all()
    else:
        vacancy_list = list(vacancies)

    expected_ids = {vacancy.id for vacancy in vacancy_list if getattr(vacancy, "id", None) is not None}
    cached_ids = list_cached_vacancy_ids()
    orphan_ids = cached_ids - expected_ids

    removed = 0
    for vacancy_id in orphan_ids:
        await asyncio.to_thread(delete_cached_vacancy, vacancy_id)
        removed += 1

    generated = 0
    reused = 0
    for vacancy in vacancy_list:
        if is_cache_fresh(vacancy):
            reused += 1
            continue

        try:
            # Pillow rendering is CPU-bound and used to freeze every bot
            # update while a full cache was regenerated after midnight.
            await asyncio.to_thread(generate_and_cache, vacancy)
            generated += 1
        except Exception:
            logger.exception("Failed to generate image for vacancy %s", getattr(vacancy, "id", None))

    logger.info(
        "Vacancy image cache synced: total=%s, generated=%s, reused=%s, removed=%s",
        len(vacancy_list),
        generated,
        reused,
        removed,
    )
    return {
        "total": len(vacancy_list),
        "generated": generated,
        "reused": reused,
        "removed": removed,
    }


async def pregenerate_vacancy_images() -> dict[str, int]:
    """Backward-compatible entry point for startup cache generation."""
    return await sync_vacancy_image_cache()
