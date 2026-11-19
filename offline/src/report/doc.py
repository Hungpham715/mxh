"""Tiny block-document model rendered to both Markdown and PDF (ReportLab, embedded TTF for Vietnamese)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

# Logical font name -> candidate files by platform. Windows Arial first; on Linux fall back
# to metric-compatible Liberation Sans, then DejaVu Sans. All styles below keep referring to
# the logical names ("Arial", "Consolas"), so the rendered document does not depend on the OS.
FONT_CANDIDATES: dict[str, list[str]] = {
    "Arial": ["C:/Windows/Fonts/arial.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "Arial-Bold": ["C:/Windows/Fonts/arialbd.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "Arial-Italic": ["C:/Windows/Fonts/ariali.ttf",
                     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"],
    "Arial-BoldItalic": ["C:/Windows/Fonts/arialbi.ttf",
                         "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"],
    "Consolas": ["C:/Windows/Fonts/consola.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
}


def _resolve_font(logical: str) -> str:
    for candidate in FONT_CANDIDATES[logical]:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(f"no usable font for {logical!r}; tried: {FONT_CANDIDATES[logical]}")


@dataclass
class Doc:
    blocks: list[tuple[str, Any]] = field(default_factory=list)

    def h1(self, t: str): self.blocks.append(("h1", t))
    def h2(self, t: str): self.blocks.append(("h2", t))
    def h3(self, t: str): self.blocks.append(("h3", t))
    def p(self, t: str): self.blocks.append(("p", t))
    def bullets(self, items: list[str]): self.blocks.append(("ul", items))
    def code(self, t: str): self.blocks.append(("code", t))
    def table(self, header: list[str], rows: list[list[Any]], widths: list[float] | None = None):
        self.blocks.append(("table", (header, [[("" if c is None else str(c)) for c in r] for r in rows], widths)))
    def img(self, path: Path, caption: str, width_cm: float = 16):
        self.blocks.append(("img", (Path(path), caption, width_cm)))
    def pagebreak(self): self.blocks.append(("pb", None))

    # ------------------------------------------------------------- markdown
    def to_markdown(self, base: Path) -> str:
        out = []
        for kind, v in self.blocks:
            if kind == "h1": out.append(f"# {v}\n")
            elif kind == "h2": out.append(f"## {v}\n")
            elif kind == "h3": out.append(f"### {v}\n")
            elif kind == "p": out.append(v.replace("<b>", "**").replace("</b>", "**").replace("<i>", "*").replace("</i>", "*") + "\n")
            elif kind == "ul": out.append("\n".join(f"- {x}" for x in v) + "\n")
            elif kind == "code": out.append(f"```\n{v}\n```\n")
            elif kind == "table":
                h, rows, _ = v
                out.append("| " + " | ".join(h) + " |\n|" + "---|" * len(h) + "\n" +
                           "\n".join("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows) + "\n")
            elif kind == "img":
                path, cap, _ = v
                # Relative to the markdown file when possible, so the report renders on GitHub
                # regardless of which machine built it (os.path.relpath raises across Windows drives).
                try:
                    rel = Path(os.path.relpath(path, base)).as_posix()
                except ValueError:
                    rel = path.as_posix()
                out.append(f"![{cap}]({rel})\n\n*{cap}*\n")
        return "\n".join(out)

    # ------------------------------------------------------------- pdf
    def to_pdf(self, path: Path, title: str) -> int:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_JUSTIFY
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
                                        Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle)

        for logical in FONT_CANDIDATES:
            pdfmetrics.registerFont(TTFont(logical, _resolve_font(logical)))
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic", boldItalic="Arial-BoldItalic")

        ss = getSampleStyleSheet()
        body = ParagraphStyle("body", parent=ss["Normal"], fontName="Arial", fontSize=10.5, leading=14.5,
                              alignment=TA_JUSTIFY, spaceAfter=6)
        h1 = ParagraphStyle("h1", parent=body, fontName="Arial-Bold", fontSize=16, leading=20, spaceBefore=10,
                            spaceAfter=10, alignment=0, textColor=colors.HexColor("#1f3b5c"))
        h2 = ParagraphStyle("h2", parent=h1, fontSize=13, leading=17, spaceBefore=10, spaceAfter=6)
        h3 = ParagraphStyle("h3", parent=h1, fontSize=11.5, leading=15, spaceBefore=6, spaceAfter=4)
        cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=10.5, alignment=0, spaceAfter=0)
        cellb = ParagraphStyle("cellb", parent=cell, fontName="Arial-Bold")
        cap = ParagraphStyle("cap", parent=body, fontName="Arial-Italic", fontSize=9, alignment=1)
        mono = ParagraphStyle("mono", parent=body, fontName="Consolas", fontSize=8, leading=10,
                              backColor=colors.HexColor("#f3f3f3"), borderPadding=4)
        W = A4[0] - 4 * cm
        story: list[Any] = []
        for kind, v in self.blocks:
            if kind == "h1": story.append(Paragraph(v, h1))
            elif kind == "h2": story.append(Paragraph(v, h2))
            elif kind == "h3": story.append(Paragraph(v, h3))
            elif kind == "p": story.append(Paragraph(v, body))
            elif kind == "ul":
                story.append(ListFlowable([ListItem(Paragraph(x, body), leftIndent=12) for x in v],
                                          bulletType="bullet", start="•", leftIndent=12, bulletFontName="Arial"))
            elif kind == "code":
                story.append(Preformatted(v, mono, maxLineLength=110))
                story.append(Spacer(1, 6))
            elif kind == "table":
                h, rows, widths = v
                data = [[Paragraph(escape(c), cellb) for c in h]] + [[Paragraph(escape(c), cell) for c in r] for r in rows]
                cw = [W * w for w in widths] if widths else [W / len(h)] * len(h)
                t = Table(data, colWidths=cw, repeatRows=1)
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde6f0")),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")])]))
                story.append(t)
                story.append(Spacer(1, 8))
            elif kind == "img":
                p, c, wcm = v
                if p.exists():
                    from reportlab.lib.utils import ImageReader
                    iw, ih = ImageReader(str(p)).getSize()
                    w = min(wcm * cm, W)
                    hgt = w * ih / iw
                    if hgt > 19 * cm:
                        hgt = 19 * cm
                        w = hgt * iw / ih
                    story.append(KeepTogether([Image(str(p), width=w, height=hgt), Paragraph(c, cap)]))
                else:
                    story.append(Paragraph(f"[Hình không tồn tại: {escape(str(p.name))}]", cap))
            elif kind == "pb":
                story.append(PageBreak())

        pages = {"n": 0}

        def footer(canvas, doc):
            pages["n"] = doc.page
            canvas.saveState()
            canvas.setFont("Arial", 8)
            canvas.drawString(2 * cm, 1.2 * cm, title)
            canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Trang {doc.page}")
            canvas.restoreState()

        path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm,
                                bottomMargin=2 * cm, title=title, author="nlp-collab-graph")
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return pages["n"]
