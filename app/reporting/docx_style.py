from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt


def configure_document_styles(document: Document) -> None:
    """Apply a deterministic CJK-capable font map for Word and headless rendering."""
    style_sizes = {
        "Normal": 10.5,
        "Title": 18,
        "Heading 1": 15,
        "Heading 2": 12.5,
        "List Bullet": 10.5,
    }
    for style_name, size in style_sizes.items():
        style = document.styles[style_name]
        style.font.name = "Noto Sans CJK SC"
        style.font.size = Pt(size)
        style._element.get_or_add_rPr().rFonts.set(
            qn("w:eastAsia"), "Noto Sans CJK SC"
        )
    document.styles["Heading 1"].font.bold = True
    document.styles["Heading 2"].font.bold = True
