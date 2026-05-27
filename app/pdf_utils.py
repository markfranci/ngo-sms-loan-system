from datetime import datetime
from html import escape

from flask import make_response
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


BRAND_DARK = colors.HexColor('#18181B')
BRAND_MUTED = colors.HexColor('#52525B')
BRAND_LINE = colors.HexColor('#D4D4D8')
BRAND_SOFT = colors.HexColor('#F4F4F5')
BRAND_TEXT = colors.HexColor('#27272A')


def pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='Meta',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=BRAND_MUTED,
    ))
    styles.add(ParagraphStyle(
        name='SectionTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=BRAND_TEXT,
        spaceBefore=10,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name='CertificateTitle',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        alignment=1,
        textColor=BRAND_DARK,
        spaceAfter=14,
    ))
    styles.add(ParagraphStyle(
        name='CertificateBody',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=12,
        leading=20,
        alignment=1,
        textColor=BRAND_TEXT,
    ))
    return styles


def draw_pdf_chrome(canvas, doc, title, subtitle=None):
    canvas.saveState()
    page_width, page_height = doc.pagesize
    left = doc.leftMargin
    right = page_width - doc.rightMargin

    logo_size = 12 * mm
    logo_x = left
    logo_y = page_height - 21 * mm
    canvas.setFillColor(BRAND_DARK)
    canvas.roundRect(logo_x, logo_y, logo_size, logo_size, 2 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont('Helvetica-Bold', 8)
    canvas.drawCentredString(logo_x + logo_size / 2, logo_y + 4 * mm, 'NGO')

    canvas.setFillColor(BRAND_DARK)
    canvas.setFont('Helvetica-Bold', 13)
    canvas.drawString(left + 16 * mm, page_height - 12.5 * mm, 'NGO SMS Loan System')
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(BRAND_MUTED)
    canvas.drawString(left + 16 * mm, page_height - 17.5 * mm, subtitle or title)

    canvas.drawRightString(
        right,
        page_height - 12.5 * mm,
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )

    canvas.setStrokeColor(BRAND_LINE)
    canvas.setLineWidth(0.6)
    canvas.line(left, page_height - 24 * mm, right, page_height - 24 * mm)

    footer_y = 10 * mm
    canvas.line(left, footer_y + 5 * mm, right, footer_y + 5 * mm)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(BRAND_MUTED)
    canvas.drawString(left, footer_y, 'Confidential document')
    canvas.drawCentredString(page_width / 2, footer_y, 'Prepared for official review')
    canvas.drawRightString(right, footer_y, f'Page {canvas.getPageNumber()}')
    canvas.restoreState()


def build_pdf_response(filename, title, story, pagesize=A4, subtitle=None):
    from io import BytesIO

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=31 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(
        story,
        onFirstPage=lambda canvas, document: draw_pdf_chrome(canvas, document, title, subtitle),
        onLaterPages=lambda canvas, document: draw_pdf_chrome(canvas, document, title, subtitle),
    )
    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'application/pdf'
    return response


def modern_table(data, column_widths=None, font_size=8, header_font_size=8, repeat_rows=1):
    table = Table(data, colWidths=column_widths, repeatRows=repeat_rows)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BRAND_DARK),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), header_font_size),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, BRAND_SOFT]),
        ('TEXTCOLOR', (0, 1), (-1, -1), BRAND_TEXT),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), font_size),
        ('GRID', (0, 0), (-1, -1), 0.35, BRAND_LINE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    return table


def key_value_table(items, columns=2):
    styles = pdf_styles()
    rows = []
    row = []
    for label, value in items:
        row.append(Paragraph(f'<b>{escape(str(label))}</b><br/>{escape(str(value))}', styles['Meta']))
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        row.extend([''] * (columns - len(row)))
        rows.append(row)

    table = Table(rows, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BRAND_SOFT),
        ('BOX', (0, 0), (-1, -1), 0.5, BRAND_LINE),
        ('INNERGRID', (0, 0), (-1, -1), 0.35, BRAND_LINE),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    return table


def pdf_paragraph(value, style=None):
    styles = pdf_styles()
    return Paragraph(escape(str(value)), style or styles['BodyText'])


def landscape_a4():
    return landscape(A4)
