from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from dotenv import dotenv_values
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from .dashboard_db import DATA_DIR
from .dashboard_service import dashboard

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = DATA_DIR / "reports"
REPORT_WINDOW = {"day": "day", "week": "7d", "month": "month"}
REPORT_LABEL = {"day": "日报", "week": "周报", "month": "月报"}


def generate_report(
    product_line: str,
    report_type: str,
    *,
    output_dir: Optional[Path] = None,
    today: Optional[date] = None,
) -> Path:
    if report_type not in REPORT_WINDOW:
        raise ValueError("报告类型必须是 day、week 或 month")
    current = today or date.today()
    data = dashboard(today=current)
    module = next(
        (item for item in data["product_lines"] if item["product_line"] == product_line),
        None,
    )
    if module is None:
        raise ValueError("当前重点产品线不存在")
    selected = next(
        item for item in module["windows"] if item["code"] == REPORT_WINDOW[report_type]
    )
    analysis = _deepseek_analysis(module, selected, report_type)

    target_dir = Path(output_dir or REPORT_DIR / current.isoformat())
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_line = re.sub(r'[\\/:*?"<>|]+', "_", product_line).strip() or "产品线"
    path = target_dir / f"{safe_line}-{current.isoformat()}-{REPORT_LABEL[report_type]}.docx"

    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run(f"{product_line}经营{REPORT_LABEL[report_type]}")
    title_run.bold = True
    title_run.font.size = Pt(18)
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run(f"报告周期：{selected['start']} 至 {selected['end']}")

    document.add_heading("一、领导摘要", level=1)
    for item in analysis.get("executive_summary", []):
        document.add_paragraph(str(item), style="List Bullet")

    document.add_heading("二、核心数据", level=1)
    _add_summary_table(document, selected)
    if selected.get("source_note"):
        paragraph = document.add_paragraph()
        run = paragraph.add_run("数据口径说明：" + selected["source_note"])
        run.italic = True
    for warning in selected.get("warnings") or []:
        document.add_paragraph("数据提示：" + warning)

    document.add_heading("三、趋势与变化", level=1)
    _add_analysis_section(document, "表现判断", analysis.get("performance"))
    _add_analysis_section(document, "变化原因", analysis.get("causes"))

    document.add_heading("四、已记录的操作与判断", level=1)
    any_note = False
    for window in module["windows"]:
        content = (window.get("note") or {}).get("content", "").strip()
        if not content:
            continue
        any_note = True
        document.add_heading(window["label"], level=2)
        for paragraph_text in content.splitlines():
            if paragraph_text.strip():
                document.add_paragraph(paragraph_text.strip())
    if not any_note:
        document.add_paragraph("本周期尚未填写人工记录。")

    document.add_heading("五、风险与下一步", level=1)
    _add_analysis_section(document, "主要风险", analysis.get("risks"))
    _add_analysis_section(document, "下一步建议", analysis.get("actions"))
    _add_analysis_section(document, "需要的支持", analysis.get("support_needed"))

    document.add_heading("六、产品范围", level=1)
    table = document.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    headers = ["产品", "ASIN", "MSKU", "店铺", "国家"]
    for index, value in enumerate(headers):
        table.rows[0].cells[index].text = value
    for product in module["products"]:
        cells = table.add_row().cells
        cells[0].text = str(product.get("product_name") or "-")
        cells[1].text = str(product.get("asin") or "-")
        cells[2].text = str(product.get("msku") or "-")
        cells[3].text = str(product.get("store_name") or "-")
        cells[4].text = str(product.get("country") or "-")

    document.save(path)
    return path


def _add_summary_table(document: Document, window: dict[str, Any]) -> None:
    metrics = [
        ("销售额", "sales_amount", "currency"),
        ("销量", "units", "count"),
        ("广告花费", "ad_spend", "currency"),
        ("广告销售额", "ad_sales", "currency"),
        ("TACOS", "tacos", "ratio"),
        ("CTR", "ctr", "ratio"),
        ("CPC", "cpc", "currency"),
        ("CVR", "cvr", "ratio"),
        ("退款金额", "refund_amount", "currency"),
        ("FBA可售库存", "fba_available", "count"),
    ]
    table = document.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.rows[0].cells[0].text = "指标"
    table.rows[0].cells[1].text = "本期"
    table.rows[0].cells[2].text = "对比上个等长周期"
    summary = window.get("summary") or {}
    comparisons = window.get("comparisons") or {}
    for label, code, unit in metrics:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = _format_metric(summary.get(code), unit)
        cells[2].text = _format_change(comparisons.get(code))


def _add_analysis_section(document: Document, heading: str, value: Any) -> None:
    document.add_heading(heading, level=2)
    items = value if isinstance(value, list) else ([value] if value else [])
    if not items:
        document.add_paragraph("暂无。")
        return
    for item in items:
        document.add_paragraph(str(item), style="List Bullet")


def _deepseek_analysis(
    module: dict[str, Any], selected: dict[str, Any], report_type: str
) -> dict[str, Any]:
    settings = _deepseek_settings()
    if not settings.get("api_key"):
        return _fallback_analysis(module, selected)
    context = {
        "report_type": report_type,
        "product_line": module["product_line"],
        "selected_window": selected,
        "all_window_notes": {
            item["code"]: (item.get("note") or {}).get("content", "")
            for item in module["windows"]
        },
        "products": module["products"],
    }
    prompt = (
        "根据下面的确定数据和人工记录，生成经营报告分析。不得创造、修改或补齐任何数字；"
        "缺失数据必须明确写缺失。将人工记录中的已执行操作、判断、原因、计划融入分析。"
        "只返回JSON，字段为 executive_summary、performance、causes、risks、actions、support_needed，"
        "每个字段都是字符串数组。\n\n"
        + json.dumps(context, ensure_ascii=False, default=str)
    )
    try:
        import httpx

        url = settings["base_url"].rstrip("/") + "/chat/completions"
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {settings['api_key']}"},
            json={
                "model": settings["model"],
                "messages": [
                    {
                        "role": "system",
                        "content": "你是严谨的亚马逊经营分析助手，只使用用户提供的数据。",
                    },
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
            timeout=90,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return {
            key: [str(item) for item in parsed.get(key, []) if str(item).strip()]
            for key in (
                "executive_summary",
                "performance",
                "causes",
                "risks",
                "actions",
                "support_needed",
            )
        }
    except Exception:
        return _fallback_analysis(module, selected)


def _fallback_analysis(
    module: dict[str, Any], selected: dict[str, Any]
) -> dict[str, Any]:
    summary = selected.get("summary") or {}
    notes = [
        (item.get("note") or {}).get("content", "").strip()
        for item in module["windows"]
        if (item.get("note") or {}).get("content", "").strip()
    ]
    executive = [
        f"本期销售额：{_format_metric(summary.get('sales_amount'), 'currency')}；"
        f"销量：{_format_metric(summary.get('units'), 'count')}。"
    ]
    if summary.get("ad_spend") is not None:
        executive.append(
            f"广告花费：{_format_metric(summary.get('ad_spend'), 'currency')}；"
            f"TACOS：{_format_metric(summary.get('tacos'), 'ratio')}。"
        )
    if selected.get("warnings"):
        executive.append("存在数据缺失，相关结论需要结合后续同步结果复核。")
    return {
        "executive_summary": executive,
        "performance": ["当前为规则版分析，数字由程序计算。"],
        "causes": notes[:3] or ["尚未填写人工原因判断。"],
        "risks": selected.get("warnings") or ["暂无程序识别出的数据风险。"],
        "actions": notes[-3:] or ["尚未填写下一步行动。"],
        "support_needed": ["尚未填写所需支持。"],
    }


def _deepseek_settings() -> dict[str, str]:
    env_path = ROOT / ".env"
    values = dotenv_values(env_path) if env_path.exists() else {}

    def read(name: str, default: str = "") -> str:
        return str(os.getenv(name) or values.get(name) or default).strip()

    return {
        "api_key": read("DEEPSEEK_API_KEY"),
        "base_url": read("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": read("DEEPSEEK_MODEL", "deepseek-chat"),
    }


def _format_metric(value: Any, unit: str) -> str:
    if value is None:
        return "数据缺失"
    number = float(value)
    if unit == "ratio":
        return f"{number * 100:.2f}%"
    if unit == "count":
        return f"{number:,.0f}"
    return f"{number:,.2f}"


def _format_change(value: Any) -> str:
    if value is None:
        return "无法比较"
    number = float(value)
    sign = "+" if number > 0 else ""
    return f"{sign}{number * 100:.2f}%"
