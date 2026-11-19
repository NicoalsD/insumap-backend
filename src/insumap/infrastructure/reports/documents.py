"""Abstract factory of the report documents: the PDF and HTML families (P03).

Pattern: P03 Abstract Factory

A family is coherent by construction. The writer and the text rules of one
factory always come together, so a PDF never receives HTML escaping and an HTML
document never receives PDF encoding. Every value of a report goes through the
``ReportText`` of its family before it is written.

The PDF engine (fpdf2) loads no image and no remote resource: the document only
contains what the generator wrote.
"""

from __future__ import annotations

import html
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Final, final, override

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from insumap.application.reports.model import ReportFormat

FONT_FAMILY: Final = "Helvetica"
"""A core PDF font: no font file is read from disk."""
PAGE_MARGIN_MM: Final = 15
TABLE_ROW_HEIGHT_MM: Final = 7
TITLE_SIZE: Final = 16
HEADING_SIZE: Final = 12
BODY_SIZE: Final = 10
NOTE_SIZE: Final = 8
ELLIPSIS: Final = "..."
HTML_STYLE: Final = (
    "body{font-family:system-ui,sans-serif;margin:2rem;color:#1f2933}"
    "h1{font-size:1.5rem}h2{font-size:1.1rem;margin-top:1.5rem}"
    "table{border-collapse:collapse;width:100%;margin:.5rem 0}"
    "th,td{border:1px solid #cbd2d9;padding:.3rem .5rem;text-align:left}"
    "th{background:#f0f4f8}.nota{font-size:.85rem;color:#52606d}"
)


class ReportText(ABC):
    """Product: makes a value safe for the output of its family."""

    @abstractmethod
    def safe(self, value: str) -> str:
        """The value as the output can carry it, never as markup or as a failure."""


class ReportWriter(ABC):
    """Product: writes the parts of one document and renders it to bytes."""

    @abstractmethod
    def title(self, text: str) -> None:
        """The main title of the document."""

    @abstractmethod
    def heading(self, text: str) -> None:
        """A section title."""

    @abstractmethod
    def paragraph(self, text: str) -> None:
        """Running text."""

    @abstractmethod
    def note(self, text: str) -> None:
        """Small text: the simulated-data mark and the disclaimer."""

    @abstractmethod
    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        """A table with a header row."""

    @abstractmethod
    def render(self) -> bytes:
        """The whole document."""


class ReportDocumentFactory(ABC):
    """Abstract factory of one output family.

    Pattern: P03 Abstract Factory
    """

    @property
    @abstractmethod
    def output(self) -> ReportFormat:
        """The format every product of this family produces."""

    @property
    @abstractmethod
    def media_type(self) -> str:
        """The media type of the rendered document."""

    @abstractmethod
    def create_text(self) -> ReportText:
        """The text rules of this family."""

    @abstractmethod
    def create_writer(self) -> ReportWriter:
        """A writer that uses this family's text rules."""


@final
class HtmlReportText(ReportText):
    @override
    def safe(self, value: str) -> str:
        """HTML escaping of every value: nothing reaches the page as markup."""
        return html.escape(value, quote=True)


@final
class HtmlReportWriter(ReportWriter):
    def __init__(self, text: ReportText) -> None:
        self._text = text
        self._title = ""
        self._parts: list[str] = []

    @override
    def title(self, text: str) -> None:
        self._title = self._text.safe(text)
        self._parts.append(f"<h1>{self._title}</h1>")

    @override
    def heading(self, text: str) -> None:
        self._parts.append(f"<h2>{self._text.safe(text)}</h2>")

    @override
    def paragraph(self, text: str) -> None:
        self._parts.append(f"<p>{self._text.safe(text)}</p>")

    @override
    def note(self, text: str) -> None:
        self._parts.append(f'<p class="nota">{self._text.safe(text)}</p>')

    @override
    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        head = "".join(f"<th>{self._text.safe(name)}</th>" for name in headers)
        body = "".join(
            "<tr>"
            + "".join(f"<td>{self._text.safe(cell)}</td>" for cell in row)
            + "</tr>"
            for row in rows
        )
        self._parts.append(
            f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        )

    @override
    def render(self) -> bytes:
        document = (
            '<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{self._title}</title><style>{HTML_STYLE}</style></head>"
            f"<body>{''.join(self._parts)}</body></html>"
        )
        return document.encode("utf-8")


@final
class HtmlReportDocumentFactory(ReportDocumentFactory):
    """The HTML family: escaping by ``html.escape``, output in UTF-8."""

    @property
    @override
    def output(self) -> ReportFormat:
        return ReportFormat.HTML

    @property
    @override
    def media_type(self) -> str:
        return "text/html; charset=utf-8"

    @override
    def create_text(self) -> ReportText:
        return HtmlReportText()

    @override
    def create_writer(self) -> ReportWriter:
        return HtmlReportWriter(self.create_text())


@final
class PdfReportText(ReportText):
    @override
    def safe(self, value: str) -> str:
        """Core PDF fonts only speak Latin-1: any other character becomes ``?``.

        Replacing it is safer than failing: a name with an emoji must not turn
        into a server error.
        """
        return value.encode("latin-1", errors="replace").decode("latin-1")


@final
class PdfReportWriter(ReportWriter):
    def __init__(self, text: ReportText) -> None:
        self._text = text
        self._pdf = FPDF(format="A4")
        self._pdf.set_margins(PAGE_MARGIN_MM, PAGE_MARGIN_MM, PAGE_MARGIN_MM)
        self._pdf.set_auto_page_break(auto=True, margin=PAGE_MARGIN_MM)
        self._pdf.add_page()

    @override
    def title(self, text: str) -> None:
        safe = self._text.safe(text)
        self._pdf.set_title(safe)
        self._pdf.set_font(FONT_FAMILY, style="B", size=TITLE_SIZE)
        self._line(safe, height=9)

    @override
    def heading(self, text: str) -> None:
        self._pdf.ln(3)
        self._pdf.set_font(FONT_FAMILY, style="B", size=HEADING_SIZE)
        self._line(self._text.safe(text), height=7)

    @override
    def paragraph(self, text: str) -> None:
        self._pdf.set_font(FONT_FAMILY, size=BODY_SIZE)
        self._line(self._text.safe(text), height=5)

    @override
    def note(self, text: str) -> None:
        self._pdf.set_font(FONT_FAMILY, style="I", size=NOTE_SIZE)
        self._line(self._text.safe(text), height=4)

    @override
    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        width = self._pdf.epw / len(headers)
        self._pdf.set_font(FONT_FAMILY, style="B", size=BODY_SIZE)
        self._row([self._text.safe(name) for name in headers], width)
        self._pdf.set_font(FONT_FAMILY, size=BODY_SIZE)
        for row in rows:
            self._row([self._text.safe(cell) for cell in row], width)
        self._pdf.ln(2)

    @override
    def render(self) -> bytes:
        return bytes(self._pdf.output())

    def _line(self, text: str, *, height: float) -> None:
        self._pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def _row(self, cells: Sequence[str], width: float) -> None:
        for index, cell in enumerate(cells):
            last = index == len(cells) - 1
            self._pdf.cell(
                width,
                TABLE_ROW_HEIGHT_MM,
                _fit(self._pdf, cell, width),
                border=1,
                new_x=XPos.LMARGIN if last else XPos.RIGHT,
                new_y=YPos.NEXT if last else YPos.TOP,
            )


def _fit(pdf: FPDF, text: str, width: float) -> str:
    """Shorten a cell so its text stays inside the column."""
    limit = width - 2
    if pdf.get_string_width(text) <= limit:
        return text
    cut = text
    while cut and pdf.get_string_width(cut + ELLIPSIS) > limit:
        cut = cut[:-1]
    return cut + ELLIPSIS


@final
class PdfReportDocumentFactory(ReportDocumentFactory):
    """The PDF family: fpdf2 with a core font and Latin-1 text."""

    @property
    @override
    def output(self) -> ReportFormat:
        return ReportFormat.PDF

    @property
    @override
    def media_type(self) -> str:
        return "application/pdf"

    @override
    def create_text(self) -> ReportText:
        return PdfReportText()

    @override
    def create_writer(self) -> ReportWriter:
        return PdfReportWriter(self.create_text())
