"""
report_pdf.py
=============

Builds a PDF report with matplotlib's own PDF backend (no extra dependency).

A report is a list of sections, each one of
    ("text",   title, [paragraph, ...])
    ("table",  title, rows)             rows = list of dicts (one per table row)
    ("figure", title, fig_or_png_path)  a matplotlib Figure or a saved PNG

Pages are A4 landscape. Used by main.py (outputs/report.pdf) and by the
dashboard's "Download PDF report" button (built in memory).
"""

from __future__ import annotations

import datetime as dt
import io
import textwrap

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

PAGE = (11.69, 8.27)     # A4 landscape, inches
INK, INK_2, GRID, HEAD = "#0b0b0b", "#52514e", "#e1e0d9", "#f0efec"


def _page(title: str | None = None):
    fig = plt.figure(figsize=PAGE)
    fig.patch.set_facecolor("white")
    if title:
        fig.text(0.05, 0.94, title, fontsize=16, fontweight="bold", color=INK, va="top")
    return fig


def _footer(fig, page_no: int, doc_title: str):
    fig.text(0.05, 0.03, doc_title, fontsize=8, color=INK_2)
    fig.text(0.95, 0.03, f"page {page_no}", fontsize=8, color=INK_2, ha="right")


def _text_page(title: str, paragraphs: list[str]):
    fig = _page(title)
    y = 0.87
    for para in paragraphs:
        bullet = para.startswith("- ")
        body = para[2:] if bullet else para
        lines = textwrap.wrap(body, width=125) or [""]
        for i, line in enumerate(lines):
            prefix = "•  " if bullet and i == 0 else ("    " if bullet else "")
            fig.text(0.06, y, prefix + line, fontsize=10.5, color=INK, va="top")
            y -= 0.032
        y -= 0.014
        if y < 0.1:
            break
    return fig


def _table_pages(title: str, rows: list[dict], max_rows: int = 18):
    if not rows:
        return [_text_page(title, ["(no rows)"])]
    cols = list(rows[0].keys())
    pages = []
    for start in range(0, len(rows), max_rows):
        chunk = rows[start:start + max_rows]
        fig = _page(title if start == 0 else f"{title} (continued)")
        ax = fig.add_axes([0.04, 0.08, 0.92, 0.8])
        ax.axis("off")
        cell_text = [[textwrap.fill(str(r[c]), 18) for c in cols] for r in chunk]
        header = [textwrap.fill(str(c), 14) for c in cols]
        font = 8 if len(cols) <= 10 else 6.8
        tbl = ax.table(cellText=cell_text, colLabels=header, loc="upper center", cellLoc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(font)
        tbl.scale(1, 2.3)
        for (r, _), cell in tbl.get_celld().items():
            cell.set_edgecolor(GRID)
            if r == 0:
                cell.set_facecolor(HEAD)
                cell.set_text_props(fontweight="bold", color=INK)
                cell.set_height(cell.get_height() * 1.6)
        pages.append(fig)
    return pages


def _figure_page(title: str, figure):
    if isinstance(figure, str):
        img = plt.imread(figure)
        fig = _page(title)
        ax = fig.add_axes([0.05, 0.07, 0.9, 0.82])
        ax.imshow(img)
        ax.axis("off")
        return fig, False
    # A live Figure: give it a title and print it on its own page.
    figure.set_size_inches(*PAGE)
    figure.subplots_adjust(top=0.86, bottom=0.1)
    figure.text(0.05, 0.95, title, fontsize=16, fontweight="bold", color=INK, va="top")
    return figure, True


def build_pdf(sections: list[tuple], out=None, doc_title: str = "Mamdani Fuzzy Room Temperature Controller"):
    """
    Write the report. `out` = file path or file-like; None returns PDF bytes.
    """
    buffer = io.BytesIO() if out is None else None
    target = buffer if buffer is not None else out
    page_no = 0
    with PdfPages(target) as pdf:
        cover = _page()
        cover.text(0.06, 0.62, doc_title, fontsize=24, fontweight="bold", color=INK)
        cover.text(0.06, 0.55, "Temperature + humidity Mamdani FIS · Fuzzy PI · ON/OFF baseline",
                   fontsize=13, color=INK_2)
        cover.text(0.06, 0.50, f"Generated {dt.date.today():%d %B %Y}", fontsize=11, color=INK_2)
        pdf.savefig(cover)
        plt.close(cover)
        for kind, title, content in sections:
            if kind == "text":
                figs = [(_text_page(title, content), False)]
            elif kind == "table":
                figs = [(f, False) for f in _table_pages(title, content)]
            elif kind == "figure":
                figs = [_figure_page(title, content)]
            else:
                raise ValueError(f"unknown section kind {kind!r}")
            for fig, _ in figs:
                page_no += 1
                _footer(fig, page_no, doc_title)
                pdf.savefig(fig)
                plt.close(fig)
        info = pdf.infodict()
        info["Title"] = doc_title
        info["Subject"] = "Fuzzy logic control of room temperature and humidity"
    return buffer.getvalue() if buffer is not None else out
