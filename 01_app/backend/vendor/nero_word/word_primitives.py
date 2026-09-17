#!/usr/bin/env python3
"""Small deterministic Word primitives shared by NERO task-level builders.

This module does not choose document content, templates, layout profiles, or
acceptance outcomes.  It only centralizes low-level python-docx / OOXML
operations that otherwise get copied into individual builders.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of one file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_receipt(path: str | Path) -> dict[str, Any]:
    """Return the minimal deterministic identity fields for one file."""

    resolved = Path(path)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _ensure_child(parent, tag: str):
    child = parent.find(qn(tag))
    if child is None:
        child = OxmlElement(tag)
        parent.append(child)
    return child


def _set_run_properties(
    font,
    element,
    *,
    latin: str,
    east_asia: str,
    size_pt: float | None,
    bold: bool | None,
    italic: bool | None,
    color,
    language: str | None,
) -> None:
    font.name = latin
    if size_pt is not None:
        font.size = Pt(size_pt)
    if bold is not None:
        font.bold = bold
    if italic is not None:
        font.italic = italic
    if color is not None:
        font.color.rgb = color

    r_pr = element.get_or_add_rPr()
    r_fonts = _ensure_child(r_pr, "w:rFonts")
    r_fonts.set(qn("w:hint"), "eastAsia")
    r_fonts.set(qn("w:ascii"), latin)
    r_fonts.set(qn("w:hAnsi"), latin)
    r_fonts.set(qn("w:eastAsia"), east_asia)
    r_fonts.set(qn("w:cs"), east_asia)

    if language:
        lang = _ensure_child(r_pr, "w:lang")
        lang.set(qn("w:val"), language)
        lang.set(qn("w:eastAsia"), language)


def apply_run_font(
    run,
    *,
    latin: str,
    east_asia: str | None = None,
    size_pt: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    color=None,
    language: str | None = "zh-CN",
) -> None:
    """Apply explicit Latin/CJK font properties to a run."""

    _set_run_properties(
        run.font,
        run._element,
        latin=latin,
        east_asia=east_asia or latin,
        size_pt=size_pt,
        bold=bold,
        italic=italic,
        color=color,
        language=language,
    )


def apply_style_font(
    style,
    *,
    latin: str,
    east_asia: str | None = None,
    size_pt: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    color=None,
    language: str | None = "zh-CN",
) -> None:
    """Apply explicit Latin/CJK font properties to a Word style."""

    _set_run_properties(
        style.font,
        style._element,
        latin=latin,
        east_asia=east_asia or latin,
        size_pt=size_pt,
        bold=bold,
        italic=italic,
        color=color,
        language=language,
    )


def get_or_add_paragraph_style(document, name: str):
    """Return a named paragraph style, creating it only when absent."""

    try:
        return document.styles[name]
    except KeyError:
        return document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)


def _set_on_off(parent, tag: str, enabled: bool | None) -> None:
    if enabled is None:
        return
    matches = parent.findall(qn(tag))
    if enabled:
        node = matches[0] if matches else OxmlElement(tag)
        if not matches:
            parent.append(node)
        for duplicate in matches[1:]:
            parent.remove(duplicate)
    else:
        for node in matches:
            parent.remove(node)


def set_paragraph_keep(
    paragraph,
    *,
    keep_next: bool | None = None,
    keep_lines: bool | None = None,
) -> None:
    """Set paragraph pagination flags without creating duplicate OOXML nodes."""

    p_pr = paragraph._p.get_or_add_pPr()
    _set_on_off(p_pr, "w:keepNext", keep_next)
    _set_on_off(p_pr, "w:keepLines", keep_lines)


def set_paragraph_shading(paragraph, fill: str) -> None:
    """Set a solid paragraph background fill."""

    shading = _ensure_child(paragraph._p.get_or_add_pPr(), "w:shd")
    shading.set(qn("w:fill"), fill)


def set_cell_margins(
    cell,
    *,
    top: int = 100,
    start: int = 120,
    bottom: int = 100,
    end: int = 120,
) -> None:
    """Set explicit cell margins in DXA."""

    tc_mar = _ensure_child(cell._tc.get_or_add_tcPr(), "w:tcMar")
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = _ensure_child(tc_mar, f"w:{side}")
        node.set(qn("w:w"), str(int(value)))
        node.set(qn("w:type"), "dxa")


def set_cell_shading(cell, fill: str) -> None:
    """Set a solid cell background fill."""

    shading = _ensure_child(cell._tc.get_or_add_tcPr(), "w:shd")
    shading.set(qn("w:fill"), fill)


def set_table_borders(
    table,
    *,
    color: str = "auto",
    size: int = 4,
    style: str = "single",
    space: int = 0,
    edges: Iterable[str] = ("top", "left", "bottom", "right", "insideH", "insideV"),
) -> None:
    """Apply one deterministic border specification to selected table edges."""

    borders = _ensure_child(table._tbl.tblPr, "w:tblBorders")
    for edge in edges:
        node = _ensure_child(borders, f"w:{edge}")
        node.set(qn("w:val"), style)
        node.set(qn("w:sz"), str(int(size)))
        node.set(qn("w:space"), str(int(space)))
        node.set(qn("w:color"), color)


def set_repeat_table_header(row, enabled: bool = True) -> None:
    """Mark or unmark one table row as a repeating header row."""

    tr_pr = row._tr.get_or_add_trPr()
    _set_on_off(tr_pr, "w:tblHeader", enabled)
    if enabled:
        tr_pr.find(qn("w:tblHeader")).set(qn("w:val"), "true")


def set_row_cant_split(row, enabled: bool = True) -> None:
    """Prevent or allow a table row to split across pages."""

    _set_on_off(row._tr.get_or_add_trPr(), "w:cantSplit", enabled)


def append_field(run, instruction: str, *, display_text: str | None = None) -> None:
    """Append a complex Word field to an existing run."""

    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction.strip()} "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")

    run._r.extend((begin, instr, separate))
    if display_text is not None:
        text = OxmlElement("w:t")
        text.text = display_text
        run._r.append(text)
    run._r.append(end)


def add_field(paragraph, instruction: str, *, display_text: str | None = None):
    """Create a run containing one complex Word field."""

    run = paragraph.add_run()
    append_field(run, instruction, display_text=display_text)
    return run


def add_page_number(paragraph, *, display_text: str = "1"):
    """Add a PAGE field; the cached text remains provisional until Word/WPS updates it."""

    return add_field(paragraph, "PAGE", display_text=display_text)


def set_inline_shape_alt(
    inline_shape,
    *,
    title: str | None = None,
    description: str | None = None,
) -> None:
    """Set title and description on an inline picture's drawing properties."""

    doc_pr = inline_shape._inline.docPr
    if description is not None:
        doc_pr.set("descr", description)
    if title is not None:
        doc_pr.set("title", title)
