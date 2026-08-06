from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1280
PANEL_HEIGHT = 330
MARGIN_LEFT = 90
MARGIN_RIGHT = 35
MARGIN_TOP = 42
MARGIN_BOTTOM = 58


def create_report_charts(
    series: dict[str, Any],
    output_dir: Path,
    prefix: str,
) -> list[tuple[Path, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    dates = [str(value) for value in series.get("dates") or []]
    charts: list[tuple[Path, str]] = []

    sales = _numbers(series.get("sales_amount") or [])
    spend = _numbers(series.get("ad_spend") or [])
    if any(value is not None for value in sales + spend):
        path = output_dir / f"{prefix}-sales-ad.png"
        _draw_multi_panel(
            dates,
            [("Sales Amount", sales, (31, 94, 255)), ("Ad Spend", spend, (214, 107, 0))],
            path,
        )
        charts.append((path, "销售额与广告花费逐日趋势"))

    inventory = _numbers(series.get("fba_available") or [])
    if any(value is not None for value in inventory):
        path = output_dir / f"{prefix}-inventory.png"
        _draw_multi_panel(
            dates,
            [("FBA Available", inventory, (22, 133, 92))],
            path,
        )
        charts.append((path, "FBA可售库存逐日趋势"))
    return charts


def _draw_multi_panel(
    dates: list[str],
    panels: Iterable[tuple[str, list[Optional[float]], tuple[int, int, int]]],
    path: Path,
) -> None:
    panel_list = list(panels)
    height = PANEL_HEIGHT * len(panel_list)
    image = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for index, (title, values, color) in enumerate(panel_list):
        top = index * PANEL_HEIGHT
        _draw_panel(draw, font, top, title, dates, values, color)
    image.save(path, format="PNG", optimize=True)


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    top: int,
    title: str,
    dates: list[str],
    values: list[Optional[float]],
    color: tuple[int, int, int],
) -> None:
    left = MARGIN_LEFT
    right = WIDTH - MARGIN_RIGHT
    chart_top = top + MARGIN_TOP
    bottom = top + PANEL_HEIGHT - MARGIN_BOTTOM
    draw.text((left, top + 14), title, fill=(36, 48, 68), font=font)
    draw.line((left, chart_top, left, bottom), fill=(177, 186, 201), width=1)
    draw.line((left, bottom, right, bottom), fill=(177, 186, 201), width=1)

    valid = [value for value in values if value is not None]
    if not valid:
        draw.text((left + 12, chart_top + 20), "No data", fill=(100, 110, 125), font=font)
        return
    minimum = min(valid)
    maximum = max(valid)
    if minimum > 0:
        minimum = 0
    span = maximum - minimum or 1

    for grid in range(5):
        y = chart_top + (bottom - chart_top) * grid / 4
        draw.line((left, y, right, y), fill=(234, 237, 242), width=1)
        label = maximum - span * grid / 4
        draw.text((8, y - 6), _compact(label), fill=(90, 101, 118), font=font)

    count = max(len(values) - 1, 1)
    points: list[tuple[float, float]] = []
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = left + (right - left) * index / count
        if value is None:
            if current:
                segments.append(current)
                current = []
            continue
        y = bottom - (value - minimum) / span * (bottom - chart_top)
        current.append((x, y))
        points.append((x, y))
    if current:
        segments.append(current)
    for segment in segments:
        if len(segment) == 1:
            x, y = segment[0]
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=color)
        else:
            draw.line(segment, fill=color, width=4, joint="curve")
    for x, y in points:
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)

    if dates:
        draw.text((left, bottom + 16), dates[0], fill=(90, 101, 118), font=font)
        end_label = dates[-1]
        box = draw.textbbox((0, 0), end_label, font=font)
        draw.text((right - (box[2] - box[0]), bottom + 16), end_label, fill=(90, 101, 118), font=font)


def _numbers(values: list[Any]) -> list[Optional[float]]:
    result: list[Optional[float]] = []
    for value in values:
        if value is None:
            result.append(None)
            continue
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            result.append(None)
    return result


def _compact(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    if absolute >= 100:
        return f"{value:.0f}"
    return f"{value:.1f}"
