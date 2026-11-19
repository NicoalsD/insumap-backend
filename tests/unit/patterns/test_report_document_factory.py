"""P03 Abstract Factory: the PDF and HTML families of the reports."""

from __future__ import annotations

from insumap.application.reports.model import ReportFormat
from insumap.infrastructure.reports.documents import (
    HtmlReportDocumentFactory,
    HtmlReportText,
    PdfReportDocumentFactory,
    PdfReportText,
)


def test_each_family_reports_its_own_output_and_media_type() -> None:
    pdf = PdfReportDocumentFactory()
    html = HtmlReportDocumentFactory()

    assert pdf.output is ReportFormat.PDF
    assert pdf.media_type == "application/pdf"
    assert html.output is ReportFormat.HTML
    assert html.media_type == "text/html; charset=utf-8"


def test_the_text_rules_come_from_the_same_family() -> None:
    assert isinstance(PdfReportDocumentFactory().create_text(), PdfReportText)
    assert isinstance(HtmlReportDocumentFactory().create_text(), HtmlReportText)


def test_html_escapes_every_value_so_no_markup_is_injected() -> None:
    text = HtmlReportText()

    assert text.safe("<script>alert(1)</script>") == (
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    )
    assert text.safe('O\'Neil "x"') == "O&#x27;Neil &quot;x&quot;"


def test_an_html_document_never_carries_a_raw_injected_value() -> None:
    writer = HtmlReportDocumentFactory().create_writer()
    writer.title("<img src=x onerror=alert(1)>")
    writer.table(["<b>h</b>"], [["<script>x</script>"]])

    body = writer.render().decode("utf-8")

    assert "<img src=x" not in body
    assert "<script>x</script>" not in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body


def test_the_pdf_text_rule_replaces_characters_the_core_font_cannot_show() -> None:
    assert PdfReportText().safe("Ana 😀") == "Ana ?"
    assert PdfReportText().safe("María") == "María"


def test_a_pdf_document_is_a_pdf_file() -> None:
    writer = PdfReportDocumentFactory().create_writer()
    writer.title("Reporte")
    writer.paragraph("Texto de prueba")

    assert writer.render().startswith(b"%PDF")
