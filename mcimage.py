"""Draws the Minecraft Discord posts as pictures.

One function per post, each returning PNG bytes:
  leaderboard()   the ranked table of players
  records()       one winner per category ("most deaths", "top miner", ...)
  status()        live server status

Every picture is 1380 pixels wide and wider than it is tall, because Discord
shows a posted image at most 550 wide and 350 tall: a wide shape fills that
box, so the text is readable without clicking.

Nothing here relies on telling colours apart: the state is always written as a
word, ranks are always numbers, and bars carry their figure beside them.

Needs Pillow (installed by the workflows). Fonts are in assets/fonts/.
The header artwork is assets/banner.jpg and assets/icon.png: swap either for a
file of the same name to change the look. Without them a plain header is drawn.
To change the colours, edit the list below.
"""
import io
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "assets", "fonts")

BG = (14, 16, 20)
ROW_A = (22, 25, 31)
ROW_B = (28, 32, 39)
LINE = (48, 54, 64)
ACCENT = (238, 134, 44)      # ember orange from the banner: header rule, bars, card edges
AMBER = (255, 226, 150)      # pale gold: the STARTING tag and a bar that is nearly full
WHITE = (240, 240, 236)
SOFT = (176, 180, 186)
DIM = (118, 124, 132)
MEDAL = [(212, 175, 55), (190, 194, 203), (176, 112, 62)]   # gold, silver, bronze

W = 1380
PAD = 40
ASSETS = os.path.join(HERE, "assets")
BANNER = os.path.join(ASSETS, "banner.jpg")
ICON = os.path.join(ASSETS, "icon.png")
HAS_ART = os.path.isfile(BANNER)
HEADER_H = 170 if HAS_ART else 108     # the art needs a taller strip to show the face
COLS_H = 56
ROW_H = 66
FOOT_H = 64

FILES = {"title": "Teko-SemiBold.ttf", "bold": "BarlowCondensed-Bold.ttf",
         "semi": "BarlowCondensed-SemiBold.ttf", "text": "BarlowCondensed-Medium.ttf",
         "mark": "DejaVuSans-Bold.ttf"}
_fonts = {}


def _font(style, size):
    key = (style, size)
    if key not in _fonts:
        path = os.path.join(FONTS, FILES[style])
        if not os.path.isfile(path):
            raise SystemExit(f"Font file {FILES[style]} is missing. Upload the whole 'assets' folder.")
        _fonts[key] = ImageFont.truetype(path, size)
    return _fonts[key]


def width(value, style, size, spacing=0):
    value = str(value)
    return _font(style, size).getlength(value) + spacing * len(value)


def text(draw, x, y, value, style, size, fill, align="left", spacing=0, max_width=None, shrink_to=None):
    """Draw value with its vertical middle at y. align is left, right or center.
    A value wider than max_width is first drawn smaller (down to shrink_to), and
    only cut off with an ellipsis if it still does not fit."""
    value = str(value)
    if max_width and shrink_to:
        while size > shrink_to and width(value, style, size, spacing) > max_width:
            size -= 1
    if max_width and width(value, style, size, spacing) > max_width:
        while value and width(value + "...", style, size, spacing) > max_width:
            value = value[:-1]
        value = value.rstrip() + "..."
    total = width(value, style, size, spacing)
    if align == "right":
        x -= total
    elif align == "center":
        x -= total / 2
    font = _font(style, size)
    if spacing:
        for ch in value:
            draw.text((x, y), ch, font=font, fill=fill, anchor="lm")
            x += font.getlength(ch) + spacing
    else:
        draw.text((x, y), value, font=font, fill=fill, anchor="lm")
    return total


def _art_header(canvas):
    """The banner across the top: the Muffin Man's face sits right of centre, and
    the picture fades to the background on the left so the title reads clearly."""
    banner = Image.open(BANNER).convert("RGB")
    scale = W / banner.width
    banner = banner.resize((W, round(banner.height * scale)), Image.LANCZOS)
    top = min(max(0, banner.height - HEADER_H), round(banner.height * 0.10))   # headband down to the teeth
    shift = round(W * 0.20)                                                    # slide the art right
    strip = Image.new("RGB", (W, HEADER_H), BG)
    strip.paste(banner.crop((0, top, W - shift, top + HEADER_H)), (shift, 0))
    strip = ImageEnhance.Brightness(strip).enhance(0.95)
    fade = Image.new("L", (W, HEADER_H), 0)
    fd = ImageDraw.Draw(fade)
    for x in range(W):
        fd.line([(x, 0), (x, HEADER_H)], fill=int(255 * max(0.0, 1 - x / (W * 0.62)) ** 0.8))
    canvas.paste(Image.composite(Image.new("RGB", (W, HEADER_H), BG), strip, fade), (0, 0))


def _canvas(height, title, subtitle, right=""):
    canvas = Image.new("RGB", (W, height), BG)
    draw = ImageDraw.Draw(canvas)
    if HAS_ART:
        _art_header(canvas)
        size = HEADER_H - 5 - 26
        tx = PAD
        if os.path.isfile(ICON):
            icon = Image.open(ICON).convert("RGBA").resize((size, size), Image.LANCZOS)
            canvas.paste(icon, (PAD, 13), icon)
            tx = PAD + size + 24
        rw = width(right.upper(), "semi", 26, 3) if right else 0
        text(draw, tx, 64, title.upper(), "title", 84, WHITE, max_width=W * 0.56 - tx, shrink_to=54)
        text(draw, tx, 124, subtitle.upper(), "semi", 26, SOFT, spacing=2, max_width=W - tx - PAD - rw - 40, shrink_to=20)
        if right:
            # a dark plate keeps the figure readable over the artwork
            draw.rectangle([W - PAD - rw - 18, 104, W - PAD + 10, 144], fill=(10, 10, 12))
            text(draw, W - PAD - 4, 124, right.upper(), "semi", 26, WHITE, align="right", spacing=3)
    else:
        # No artwork in assets/: a plain header with a drawn block mark.
        s, gx, gy = 30, PAD, 20
        for i, (cx, cy) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
            fill = ACCENT if i in (0, 3) else (110, 66, 28)
            draw.rectangle([gx + cx * (s + 4), gy + cy * (s + 4), gx + cx * (s + 4) + s, gy + cy * (s + 4) + s], fill=fill)
        tx = PAD + 2 * s + 26
        rw = width(right.upper(), "semi", 26, 3) if right else 0
        text(draw, tx, 36, title.upper(), "title", 62, WHITE, max_width=W - tx - PAD - 20)
        text(draw, tx, 78, subtitle.upper(), "semi", 24, SOFT, spacing=2, max_width=W - tx - PAD - rw - 40)
        if right:
            text(draw, W - PAD, 78, right.upper(), "semi", 26, WHITE, align="right", spacing=3)
    draw.rectangle([0, HEADER_H - 5, W, HEADER_H], fill=ACCENT)
    return canvas, draw


def _footer(draw, y, left, right):
    draw.line([(PAD, y + 4), (W - PAD, y + 4)], fill=LINE, width=2)
    text(draw, PAD, y + FOOT_H / 2 + 2, left.upper(), "semi", 26, DIM, spacing=2)
    text(draw, W - PAD, y + FOOT_H / 2 + 2, right.upper(), "semi", 26, DIM, align="right", spacing=2)


def _png(canvas):
    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _rank(draw, cx, cy, rank, r=22, size=32):
    """Rank marker. The top three get a filled disc; the number is always shown,
    so the place never depends on telling the disc colours apart."""
    if 1 <= rank <= 3:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MEDAL[rank - 1])
        text(draw, cx, cy + 1, rank, "bold", size, (18, 18, 20), align="center")
    else:
        text(draw, cx, cy + 1, rank, "semi", size, DIM, align="center")


def _bar(draw, x, y, w, h, fraction, fill=ACCENT):
    draw.rectangle([x, y, x + w, y + h], fill=(40, 44, 52))
    if fraction > 0:
        draw.rectangle([x, y, x + max(h, round(w * min(1.0, fraction))), y + h], fill=fill)


# ----------------------------------------------------------------- leaderboard
def leaderboard(title, subtitle, columns, rows, sort_key, right="", footer_left="", footer_right=""):
    """columns: [(heading, key, formatter)] left to right. rows: dicts with name
    plus one value per key, already sorted. sort_key names the highlighted column."""
    n = max(1, len(rows))
    canvas, draw = _canvas(HEADER_H + COLS_H + ROW_H * n + FOOT_H, title, subtitle, right)
    name_x = PAD + 96
    first_col = name_x + 330
    step = (W - PAD - first_col) / len(columns)
    xs = [first_col + step * (i + 1) for i in range(len(columns))]

    y = HEADER_H + COLS_H / 2 + 2
    text(draw, PAD + 34, y, "#", "semi", 28, DIM, align="center")
    text(draw, name_x, y, "PLAYER", "semi", 28, DIM, spacing=3)
    for (heading, key, _), x in zip(columns, xs):
        text(draw, x, y, heading.upper(), "semi", 26, WHITE if key == sort_key else DIM, align="right", spacing=2)
    top = HEADER_H + COLS_H
    draw.line([(PAD, top - 1), (W - PAD, top - 1)], fill=LINE, width=2)

    if not rows:
        text(draw, W / 2, top + ROW_H / 2, "No players yet", "semi", 36, SOFT, align="center")
    for i, r in enumerate(rows):
        y0 = top + i * ROW_H
        mid = y0 + ROW_H / 2
        draw.rectangle([PAD, y0, W - PAD, y0 + ROW_H - 3], fill=ROW_A if i % 2 == 0 else ROW_B)
        podium = i < 3
        if podium:
            draw.rectangle([PAD, y0, PAD + 6, y0 + ROW_H - 3], fill=MEDAL[i])
        _rank(draw, PAD + 34, mid, i + 1)
        text(draw, name_x, mid + 1, r.get("name") or "unknown", "bold" if podium else "semi", 38,
             WHITE if podium else (222, 222, 218), max_width=310, shrink_to=28)
        for (_, key, fmt), x in zip(columns, xs):
            main = key == sort_key
            text(draw, x, mid + 1, fmt(r.get(key, 0)), "bold" if main else "text", 40 if main else 36,
                 WHITE if main else SOFT, align="right")
    _footer(draw, top + ROW_H * n, footer_left, footer_right)
    return _png(canvas)


# --------------------------------------------------------------------- records
def records(title, subtitle, cards, right="", footer_left="", footer_right=""):
    """cards: [(label, player name, value text)], drawn two to a row."""
    card_h, gap = 132, 14
    lines = max(1, (len(cards) + 1) // 2)
    body = 22 + lines * (card_h + gap)
    canvas, draw = _canvas(HEADER_H + body + FOOT_H, title, subtitle, right)
    cw = (W - 2 * PAD - gap) / 2
    for i, (label, name, value) in enumerate(cards):
        x0 = PAD + (i % 2) * (cw + gap)
        y0 = HEADER_H + 22 + (i // 2) * (card_h + gap)
        draw.rectangle([x0, y0, x0 + cw, y0 + card_h], fill=ROW_A)
        draw.rectangle([x0, y0, x0 + 6, y0 + card_h], fill=ACCENT)
        text(draw, x0 + 28, y0 + 30, label.upper(), "semi", 25, DIM, spacing=3)
        vw = width(value, "semi", 36)
        text(draw, x0 + 28, y0 + 84, name, "bold", 52, WHITE, max_width=cw - 80 - vw, shrink_to=30)
        text(draw, x0 + cw - 26, y0 + 86, value, "semi", 36, SOFT, align="right")
    if not cards:
        text(draw, W / 2, HEADER_H + body / 2, "No records yet", "semi", 36, SOFT, align="center")
    _footer(draw, HEADER_H + body, footer_left, footer_right)
    return _png(canvas)


# ---------------------------------------------------------------------- status
def _mark(draw, cx, cy, state, r=17):
    """A shape for each state, so the tag reads without colour: a filled disc for
    online, a ring for offline, a triangle for starting."""
    if state == "ONLINE":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(14, 16, 20))
    elif state == "STARTING":
        draw.polygon([(cx - r, cy + r - 2), (cx + r, cy + r - 2), (cx, cy - r)], fill=AMBER)
    else:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=SOFT, width=5)


def status(s, footer_left="", footer_right=""):
    """Live status as one picture. s: dict with name, state (ONLINE, STARTING or
    OFFLINE), note, players, max, names, facts [(label, value)] and
    gauges [(label, value text, fraction 0-1 or None)]."""
    state = str(s.get("state") or "OFFLINE").upper()
    top_h, gauge_h = 330, 150
    gauges = (s.get("gauges") or [])[:4]
    body_h = 26 + top_h + (gauge_h if gauges else 0) + 22
    canvas, draw = _canvas(HEADER_H + body_h + FOOT_H, s.get("name") or "Minecraft server",
                           "Live server status", s.get("note") or "")
    x0, x1, y = PAD, W - PAD, HEADER_H + 26
    draw.rectangle([x0, y, x1, y + body_h - 48], fill=ROW_A)
    draw.rectangle([x0, y, x1, y + 5], fill=ACCENT if state == "ONLINE" else (70, 74, 82))

    # State tag, top right: a shape and the word.
    tag_w = width(state, "bold", 40, 5) + 104
    tx = x1 - 36 - tag_w
    if state == "ONLINE":
        draw.rectangle([tx, y + 36, tx + tag_w, y + 104], fill=WHITE)
        ink = (14, 16, 20)
    else:
        draw.rectangle([tx, y + 36, tx + tag_w, y + 104], outline=AMBER if state == "STARTING" else DIM, width=3)
        ink = WHITE if state == "STARTING" else SOFT
    _mark(draw, tx + 40, y + 70, state)
    text(draw, tx + 74, y + 71, state, "bold", 40, ink, spacing=5)

    split = x0 + (x1 - x0) * 0.47
    if state == "ONLINE":
        players, cap = s.get("players", 0), s.get("max", 0) or 20
        nw = text(draw, x0 + 36, y + 138, players, "title", 250, WHITE)
        text(draw, x0 + 36 + nw + 20, y + 108, "PLAYERS", "semi", 30, DIM, spacing=4)
        text(draw, x0 + 36 + nw + 20, y + 176, f"/ {cap}", "semi", 56, SOFT)
        _bar(draw, x0 + 36, y + 262, split - 40 - (x0 + 36), 18, players / cap)
        names = s.get("names") or []
        line = ", ".join(names) if names else ("Nobody on right now" if not players else "")
        text(draw, x0 + 36, y + 304, line, "text", 30, SOFT, max_width=split - 40 - (x0 + 36))
    else:
        big = "STARTING UP" if state == "STARTING" else "OFFLINE"
        text(draw, x0 + 36, y + 150, big, "title", 150, SOFT, max_width=split - 40 - (x0 + 36), shrink_to=90)
        text(draw, x0 + 36, y + 262, s.get("detail") or "", "text", 32, DIM, max_width=split - 40 - (x0 + 36))

    # Right: up to three facts (version, modpack, mods).
    draw.line([(split, y + 40), (split, y + top_h - 30)], fill=LINE, width=2)
    fy = y + 78
    for i, (label, value) in enumerate((s.get("facts") or [])[:3]):
        text(draw, split + 40, fy - 30, label.upper(), "semi", 24, DIM, spacing=4)
        room = x1 - 36 - (split + 40) - (tag_w + 24 if i == 0 else 0)
        text(draw, split + 40, fy + 8, value or "Unknown", "semi", 44, (232, 232, 228), max_width=room, shrink_to=26)
        fy += 96

    # Bottom: resource gauges. Each shows its figure in text and a bar where a limit is known.
    if gauges:
        gy = y + top_h
        draw.line([(x0 + 36, gy), (x1 - 36, gy)], fill=LINE, width=2)
        gw = (x1 - x0 - 72) / len(gauges)
        for i, (label, value, fraction) in enumerate(gauges):
            gx = x0 + 36 + i * gw
            text(draw, gx, gy + 36, label.upper(), "semi", 24, DIM, spacing=4)
            text(draw, gx, gy + 80, value, "bold", 44, WHITE, max_width=gw - 30, shrink_to=30)
            if fraction is not None:
                _bar(draw, gx, gy + 112, gw - 34, 12, fraction, AMBER if fraction >= 0.9 else ACCENT)
    _footer(draw, HEADER_H + body_h, footer_left, footer_right)
    return _png(canvas)
