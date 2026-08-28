"""Assemble rendered charts into a PowerPoint deck.

Two ways, chosen by the size preset's `chrome` (see themes/<name>.yaml,
`size_styles.<size>.chrome`):

* **chart** — the chart carries its own title, units line and source, so the
  slide is just a white sheet with the figures placed on it at their exact
  export size. This is what every preset did before the 16:9 ones arrived.

* **slide** — the chart is rendered BARE and the slide carries the words: a
  title placeholder, white panels on a light-grey canvas, each panel captioned
  above a rule with its source as a footnote, and a page number. That is how
  BBVA decks are actually built — every chart measured in *Sistema Bancario*
  has no title of its own.

The furniture is DRAWN, not inherited from a .pptx: the BBVA template is an
asset this repo does not carry, so a deck that opened it could not be built
without it. Every number lives in the theme under `deck.slide`, in millimetres,
measured off real slides. `deck.*` is econcharts' own vocabulary — neither
python-pptx nor the PowerPoint object model has a name for "caption sub-size" —
so both editions use the same keys and a value means the same thing on either
side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from econcharts.theme import Theme, load_theme

_MM_PER_IN = 25.4
# Character width as a fraction of the type size, for the caption fit estimate.
# The Excel edition asks PowerPoint how tall the text actually is; python-pptx
# cannot measure text, so this estimates. Arial digits are 0.556 em and mixed
# upper-case prose runs a little wider.
_CHAR_EM = 0.58


@dataclass
class DeckItem:
    """One rendered chart, plus the words the slide may have to set for it."""

    image: Path
    size_mm: tuple
    size_name: str
    title: Optional[str] = None
    subtitle: Optional[str] = None
    source: Optional[str] = None


def _mm(v) -> int:
    return Inches(float(v) / _MM_PER_IN)


def _rgb(theme: Theme, name, fallback="#000000") -> RGBColor:
    hexval = theme.colors.get(str(name), str(name) if str(name).startswith("#") else fallback)
    return RGBColor.from_string(hexval.lstrip("#").upper())


def _slot(theme: Theme, key: str, slot: int, default):
    """`deck.slide.panel.x` and `.w` are sequences: the template's two panels are
    NOT the same width."""
    v = theme.val(f"deck.slide.{key}")
    if not isinstance(v, list) or not v:
        return default
    return v[slot] if slot < len(v) else v[-1]


def _textbox(slide, x, y, w, h, *, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(_mm(x), _mm(y), _mm(w), _mm(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.paragraphs[0].alignment = align
    return box


def _run(paragraph, text, *, font, size, color, bold):
    r = paragraph.add_run()
    r.text = text
    r.font.name = font
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    return r


def _caption_size(title: str, sub: str, width_mm: float, box_h_mm: float,
                  size: float, sub_size: float, floor: float) -> tuple:
    """Step the caption down a point at a time until its estimated height fits.

    The rule sits at a FIXED distance below the panel top — that spacing is the
    house style and does not move — so a caption that wraps past its box would
    run straight through it. BBVA's own captions are short; a spec title plus
    its units line need not be. Shrinking is bounded and deterministic, and it
    never moves the rule.
    """
    width_pt = width_mm / _MM_PER_IN * 72.0
    box_h_pt = box_h_mm / _MM_PER_IN * 72.0
    while True:
        lines = 0
        for text, pt in ((title, size), (sub, sub_size)):
            if not text:
                continue
            per_line = max(1, int(width_pt / (pt * _CHAR_EM)))
            lines += math.ceil(len(text) / per_line) * pt * 1.2
        if lines <= box_h_pt or size <= floor:
            return size, sub_size
        size, sub_size = size - 1, max(floor, sub_size - 1)


def _draw_furniture(slide, theme: Theme, page_no: int, panels: int) -> None:
    """Title placeholder, page number, canvas and the white panels — one slide's
    worth of chrome that belongs to no single chart."""
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(
        theme, theme.val("deck.slide.background", "canvas"), "#F7F8F8")

    font = str(theme.val("format.font.name", "Arial"))
    box = _textbox(slide, theme.val("deck.slide.title.x", 9.5),
                   theme.val("deck.slide.title.y", 7.2),
                   theme.val("deck.slide.title.w", 235.2),
                   theme.val("deck.slide.title.h", 10.7))
    _run(box.text_frame.paragraphs[0],
         str(theme.val("deck.slide.title.placeholder", "XXX")),
         font=font, size=theme.val("deck.slide.title.size", 19),
         color=_rgb(theme, theme.val("deck.slide.title.color", "blue")), bold=True)

    box = _textbox(slide, theme.val("deck.slide.page.x", 232.9),
                   theme.val("deck.slide.page.y", 132.3),
                   theme.val("deck.slide.page.w", 14.0),
                   theme.val("deck.slide.page.h", 8.6), align=PP_ALIGN.RIGHT)
    _run(box.text_frame.paragraphs[0],
         f"{theme.val('deck.slide.page.prefix', 'p.')} {page_no}",
         font=font, size=theme.val("deck.slide.page.size", 8),
         color=_rgb(theme, theme.val("deck.slide.page.color", "ink")), bold=False)

    for i in range(panels):
        pnl = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            _mm(_slot(theme, "panel.x", i, 9.5)), _mm(theme.val("deck.slide.panel.y", 25.0)),
            _mm(_slot(theme, "panel.w", i, 114.5)), _mm(theme.val("deck.slide.panel.h", 108.2)))
        pnl.fill.solid()
        pnl.fill.fore_color.rgb = _rgb(theme, theme.val("deck.slide.panel.fill", "white"), "#FFFFFF")
        pnl.line.fill.background()
        pnl.shadow.inherit = False


def _place_in_panel(slide, item: DeckItem, theme: Theme, slot: int) -> None:
    px = float(_slot(theme, "panel.x", slot, 9.5))
    pw = float(_slot(theme, "panel.w", slot, 114.5))
    py = float(theme.val("deck.slide.panel.y", 25.0))
    ph = float(theme.val("deck.slide.panel.h", 108.2))
    dx = float(theme.val("deck.slide.caption.dx", 6.7))
    font = str(theme.val("format.font.name", "Arial"))

    w_mm, h_mm = item.size_mm
    slide.shapes.add_picture(str(item.image),
                             _mm(px + (pw - w_mm) / 2),
                             _mm(py + float(theme.val("deck.slide.chart.dy", 21.0))),
                             width=_mm(w_mm), height=_mm(h_mm))

    title, sub = item.title or "", item.subtitle or ""
    if title or sub:
        if bool(theme.val("deck.slide.caption.upper", True)):
            title, sub = title.upper(), sub.upper()
        if sub:
            sub = f"({sub})"
        cap_h = float(theme.val("deck.slide.caption.h", 10.5))
        size, sub_size = _caption_size(
            title, sub, pw - 2 * dx, cap_h,
            float(theme.val("deck.slide.caption.size", 12)),
            float(theme.val("deck.slide.caption.sub_size", 10)),
            float(theme.val("deck.slide.caption.min_size", 8)))
        box = _textbox(slide, px + dx, py + float(theme.val("deck.slide.caption.dy", 5.2)),
                       pw - 2 * dx, cap_h)
        colour = _rgb(theme, theme.val("deck.slide.caption.color", "blue"))
        tf = box.text_frame
        _run(tf.paragraphs[0], title, font=font, size=size, color=colour,
             bold=bool(theme.val("deck.slide.caption.bold", True)))
        if sub:
            # The units line is its own paragraph, a size down and not bold.
            p = tf.add_paragraph()
            p.alignment = PP_ALIGN.LEFT
            _run(p, sub, font=font, size=sub_size, color=colour,
                 bold=bool(theme.val("deck.slide.caption.sub_bold", False)))

        rule_y = py + float(theme.val("deck.slide.rule.dy", 18.0))
        ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                        _mm(px + dx), _mm(rule_y),
                                        _mm(px + pw - dx), _mm(rule_y))
        ln.line.color.rgb = _rgb(theme, theme.val("deck.slide.rule.color", "blue"))
        ln.line.width = Pt(float(theme.val("deck.slide.rule.weight", 0.75)))

    if item.source:
        box = _textbox(slide, px, py + ph + float(theme.val("deck.slide.source.dy", 4.1)),
                       pw, float(theme.val("deck.slide.source.h", 4.8)))
        _run(box.text_frame.paragraphs[0],
             f"{theme.source_prefix} {item.source}".strip(),
             font=font, size=float(theme.val("deck.slide.source.size", 7)),
             color=_rgb(theme, theme.val("deck.slide.source.color", "slate")), bold=False)


def _place_plain(slide, item: DeckItem, theme: Theme, slot: int, per_slide: int,
                 slide_w: int, slide_h: int) -> None:
    """chrome: chart — the figure already carries its own words, so it is simply
    centred in its share of the slide at its true export size."""
    margin_x = _mm(float(theme.val("deck.margin_x_in", 0.4)) * _MM_PER_IN)
    margin_y = Inches(0.6)
    gap = Inches(0.5)
    box_w = (slide_w - 2 * margin_x - (per_slide - 1) * gap) // per_slide
    box_h = slide_h - 2 * margin_y
    w, h = _mm(item.size_mm[0]), _mm(item.size_mm[1])
    if w > box_w or h > box_h:                     # safety: shrink, keep aspect
        s = min(box_w / w, box_h / h)
        w, h = int(w * s), int(h * s)
    left = margin_x + slot * (box_w + gap) + (box_w - w) // 2
    slide.shapes.add_picture(str(item.image), left, margin_y + (box_h - h) // 2,
                             width=w, height=h)


def build_deck(items: list, out_path: Union[str, Path],
               theme: Union[Theme, str, None] = None) -> Path:
    """Build a .pptx from rendered charts, in order. Returns the saved path.

    `items` are DeckItem records. Tuples of `(image_path, size_mm)` are still
    accepted — that was the signature before slide chrome existed — and are
    treated as the default preset with no words of their own.
    """
    if isinstance(theme, str) or theme is None:
        theme = load_theme(theme or "bbva")
    items = [it if isinstance(it, DeckItem)
             else DeckItem(image=it[0], size_mm=it[1], size_name="slides_half")
             for it in items]

    prs = Presentation()
    prs.slide_width = Inches(float(theme.val("deck.slide_width_in", 13.333)))
    prs.slide_height = Inches(float(theme.val("deck.slide_height_in", 7.5)))
    blank = prs.slide_layouts[6]

    i, page = 0, 1
    while i < len(items):
        size_name = items[i].size_name
        per_slide = int(theme.val(f"deck.per_slide.{size_name}", 2))
        # A slide holds charts of ONE preset. The chart that opens it decides
        # how many it takes and whether it owes them chrome, so a chart of a
        # different preset must start a new slide rather than be swept into
        # this one: a `chrome: slide` chart landing on a plain slide renders
        # bare AND gets no caption, losing its title and source entirely.
        batch = [it for it in items[i:i + per_slide] if it.size_name == size_name]
        slide = prs.slides.add_slide(blank)
        if theme.chrome(size_name) == "slide":
            _draw_furniture(slide, theme, page, len(batch))
            for slot, item in enumerate(batch):
                _place_in_panel(slide, item, theme, slot)
        else:
            for slot, item in enumerate(batch):
                _place_plain(slide, item, theme, slot, per_slide,
                             prs.slide_width, prs.slide_height)
        i += len(batch)
        page += 1

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return out_path
