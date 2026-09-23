from __future__ import annotations
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from .config import settings

NAVY = colors.HexColor('#0E2242')
GOLD = colors.HexColor('#B18235')


class BrandedPDFReport:
    def __init__(self, logo_path=None):
        self.logo_path = str(logo_path or settings.logo_path)

    def _text(self, c, text, x, top, width, size=10, bold=False, color=NAVY):
        style = ParagraphStyle('text', fontName='Helvetica-Bold' if bold else 'Helvetica',
                               fontSize=size, leading=size*1.35, textColor=color, splitLongWords=True)
        paragraph = Paragraph(escape(str(text)), style)
        _, height = paragraph.wrap(width, 1000)
        paragraph.drawOn(c, x, top-height)
        return top-height

    def _frame(self, c, title, subtitle):
        width, height = letter
        c.setFillColor(NAVY)
        c.rect(0, height-96, width, 96, fill=1, stroke=0)
        if Path(self.logo_path).is_file():
            c.drawImage(self.logo_path, 36, height-80, width=118, height=64,
                        preserveAspectRatio=True, anchor='c', mask='auto')
        self._text(c, title, 174, height-25, width-210, 23, True, colors.white)
        self._text(c, subtitle, 174, height-60, width-210, 9, color=colors.white)
        c.setStrokeColor(GOLD)
        c.line(36, 40, width-36, 40)
        self._text(c, 'ChocoLeads AI | Conceptual epoxy-floor visualization', 36, 30, 470, 8)
        c.drawRightString(width-36, 19, str(c.getPageNumber()))

    def build(self, leads, run_id, out_path):
        c = canvas.Canvas(str(out_path), pagesize=letter)
        c.setTitle('ChocoLeads AI - Lead Report')
        self._frame(c, 'ChocoLeads AI', 'Floors Today. Bigger Tomorrow.')
        top = self._text(c, 'Your property prospects', 36, 666, 540, 24, True)-12
        top = self._text(c, f'{len(leads)} leads | Run {run_id}', 36, top, 540, 11)-24
        for i, lead in enumerate(leads, 1):
            if top < 160:
                c.showPage()
                self._frame(c, 'Lead summary', 'Property prospects continued')
                top = 664
            top = self._text(c, f'{i:02d}  {lead.address}', 36, top, 540, 11, True)-3
            top = self._text(c, f'{lead.source_site} | {lead.property_type} | ZIP {lead.zipcode}', 58, top, 518, 9)-13
        self._text(c, 'After images are conceptual epoxy-floor edits, not photographs of completed work.',
                   36, 80, 540, 9)
        c.showPage()
        for i, lead in enumerate(leads, 1):
            self._frame(c, f'Property {i:02d}', lead.source_site)
            top = self._text(c, lead.address, 36, 676, 540, 16, True)-7
            top = self._text(c, f'{lead.property_type} | ZIP {lead.zipcode} | {lead.price or "Price not listed"} | {lead.size or "Size not listed"}', 36, top, 540, 9)-7
            # Keep a clickable source link compact even for long listing URLs.
            c.setFillColor(GOLD)
            c.setFont('Helvetica', 9)
            c.drawString(36, top-10, 'View original property listing')
            if lead.source_url.startswith(('https://', 'http://')):
                c.linkURL(lead.source_url, (36, top-14, 210, top+2), relative=0)
            top -= 30
            # Fixed, non-overlapping room blocks, strictly beneath metadata/header.
            block_height = min(232, (top-65)/2)
            for room in lead.selected_rooms[:2]:
                bottom = top-block_height
                c.setFillColor(GOLD)
                c.rect(36, top-26, 540, 26, fill=1, stroke=0)
                self._text(c, f'{room.room_label} | {room.style_label}', 44, top-7, 524, 9, True, colors.white)
                image_bottom = bottom+28
                image_height = block_height-66
                for x, path, caption in [(36, room.before_local_path, 'BEFORE'), (314, room.after_local_path, 'AFTER - CONCEPT')]:
                    c.setFillColor(colors.HexColor('#F3F5F8'))
                    c.rect(x, image_bottom, 262, image_height, fill=1, stroke=0)
                    if path and Path(path).is_file():
                        c.drawImage(path, x, image_bottom, width=262, height=image_height,
                                    preserveAspectRatio=True, anchor='c', mask='auto')
                    self._text(c, caption, x, bottom+20, 262, 9, True)
                top = bottom
            c.showPage()
        c.save()
        return str(out_path)
