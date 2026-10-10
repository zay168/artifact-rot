"""Generate the README figures (docs/figures/*.svg), light and dark variants.

The figures are plain SVG with the two typefaces embedded as subset WOFF2 data URIs:
GitHub serves README images without access to external fonts, and a Didone silently
replaced by Times is not the same figure.

Numbers are copied from the S1 verdict (runs/20261004T014500Z-verdict/verdict.txt,
three passes, 3,988 links). `runs/` is not versioned, so they are written out here;
Wilson intervals are recomputed with `artifact_rot.survival.wilson_interval`.

Typefaces (SIL Open Font License), fetched once into .cache/fonts/:
    Bodoni Moda     https://github.com/google/fonts/tree/main/ofl/bodonimoda
    Hanken Grotesk  https://github.com/google/fonts/tree/main/ofl/hankengrotesk

Usage:
    uv pip install fonttools brotli
    python tools/readme_figures.py
"""

from __future__ import annotations

import base64
import io
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from artifact_rot.survival import wilson_interval

OUT = ROOT / "docs" / "figures"
CACHE = ROOT / ".cache" / "fonts"
FONT_URLS = {
    "BodoniModa.ttf": "https://github.com/google/fonts/raw/main/ofl/bodonimoda/BodoniModa%5Bopsz%2Cwght%5D.ttf",
    "HankenGrotesk.ttf": "https://github.com/google/fonts/raw/main/ofl/hankengrotesk/HankenGrotesk%5Bwght%5D.ttf",
}

# --- Data: S1 verdict, 2026-10-04 --------------------------------------------------

BY_YEAR = {  # year: (alive, dead, restricted, unknown)
    2010: (250, 118, 0, 126),
    2014: (412, 220, 2, 193),
    2018: (387, 192, 1, 202),
    2022: (495, 182, 0, 156),
    2025: (619, 199, 1, 233),
}
BY_KIND = {
    "generic_url": (2004, 904, 2, 901),
    "code_repo": (75, 5, 0, 0),
    "data_repo": (79, 1, 2, 9),
    "dataset_doi": (5, 1, 0, 0),
}
GAP, GAP_CI = 0.0777, (0.0228, 0.1345)
REF_RATE, REF_CI = 0.331, (0.294, 0.370)
UNKNOWN_RATE = 0.228


def rate(c: tuple[int, int, int, int]) -> tuple[float, float, float, int]:
    """Dead rate with `restricted` counted alive and `unknown` excluded (§4)."""
    alive, dead, restricted, _ = c
    n = alive + dead + restricted
    low, high = wilson_interval(dead, n)
    return dead / n, low, high, n


# --- Palette (style « sharp ») -----------------------------------------------------


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    ink: str
    text: str
    muted: str
    rule: str
    faint: str
    accent: str


LIGHT = Theme("light", "#FFFFFF", "#0B0B0B", "#2B2B2B", "#5A5A5A", "#D6D6D6", "#C8C8C8", "#D42A1E")
DARK = Theme("dark", "#0B0B0B", "#FFFFFF", "#E9E9E6", "#9A9A9A", "#2E2E2E", "#5A5A5A", "#FF3B2F")

# --- Fonts ---------------------------------------------------------------------------


def _fetch(name: str) -> Path:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(FONT_URLS[name], path)
    return path


@dataclass
class Face:
    family: str
    font: TTFont

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        cmap = self.font.getBestCmap()
        hmtx = self.font["hmtx"]
        upm = self.font["head"].unitsPerEm
        units = sum(hmtx[cmap.get(ord(ch), cmap[ord("?")])][0] for ch in text)
        return units / upm * size + tracking * size * max(0, len(text) - 1)


def _instance(name: str, family: str, axes: dict[str, float]) -> Face:
    font = TTFont(_fetch(name))
    return Face(family, instancer.instantiateVariableFont(font, axes))


DISPLAY = _instance("BodoniModa.ttf", "AR Display", {"wght": 500, "opsz": 72})
SANS = _instance("HankenGrotesk.ttf", "AR Sans", {"wght": 400})
SANS_BOLD = _instance("HankenGrotesk.ttf", "AR Sans Bold", {"wght": 600})


def _woff2(face: Face, chars: str) -> str:
    buf = io.BytesIO()
    face.font.save(buf)
    buf.seek(0)
    font = TTFont(buf)
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["kern", "liga"]
    sub = subset.Subsetter(options)
    sub.populate(text=chars + "?")
    sub.subset(font)
    out = io.BytesIO()
    font.flavor = "woff2"
    font.save(out)
    return base64.b64encode(out.getvalue()).decode()


# --- SVG builder -------------------------------------------------------------------


class Svg:
    def __init__(self, width: int, height: int, theme: Theme, title: str) -> None:
        self.w, self.h, self.t, self.title = width, height, theme, title
        self.parts: list[str] = []
        self.used: dict[str, set[str]] = {}

    def _use(self, face: Face, text: str) -> None:
        self.used.setdefault(face.family, set()).update(text)

    def text(
        self,
        x: float,
        y: float,
        s: str,
        *,
        face: Face = SANS,
        size: float = 18,
        fill: str | None = None,
        anchor: str = "start",
        tracking: float = 0.0,
        italic: bool = False,
    ) -> None:
        self._use(face, s)
        ls = f' letter-spacing="{tracking * size:.2f}"' if tracking else ""
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{face.family}" font-size="{size}"'
            f' fill="{fill or self.t.text}" text-anchor="{anchor}"{ls}>{escape(s)}</text>'
        )

    def label(self, x: float, y: float, s: str, *, fill: str | None = None, anchor: str = "start",
              size: float = 13) -> None:
        self.text(x, y, s.upper(), face=SANS_BOLD, size=size, fill=fill or self.t.muted,
                  anchor=anchor, tracking=0.16)

    def line(self, x1: float, y1: float, x2: float, y2: float, *, stroke: str | None = None,
             width: float = 1, dash: str | None = None) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"'
            f' stroke="{stroke or self.t.rule}" stroke-width="{width}"{d}/>'
        )

    def rect(self, x: float, y: float, w: float, h: float, fill: str) -> None:
        self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"/>')

    def circle(self, cx: float, cy: float, r: float, *, fill: str, stroke: str | None = None,
               width: float = 0) -> None:
        s = f' stroke="{stroke}" stroke-width="{width}"' if stroke else ""
        self.parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}"{s}/>')

    def render(self) -> str:
        faces = {f.family: f for f in (DISPLAY, SANS, SANS_BOLD)}
        css = "".join(
            f"@font-face{{font-family:'{fam}';src:url(data:font/woff2;base64,"
            f"{_woff2(faces[fam], ''.join(sorted(chars)))}) format('woff2');}}"
            for fam, chars in sorted(self.used.items())
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}"'
            f' viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(self.title)}">'
            f"<title>{escape(self.title)}</title><style>{css}</style>"
            f'<rect width="100%" height="100%" fill="{self.t.bg}"/>'
            + "".join(self.parts)
            + "</svg>\n"
        )


M = 56  # outer margin


def pct(v: float, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%"


# --- Figures -------------------------------------------------------------------------


def hero(t: Theme) -> Svg:
    s = Svg(1200, 490, t, "artifact-rot — an observatory of research-link survival")
    s.line(M, 56, 1200 - M, 56, stroke=t.ink, width=2)
    s.label(M, 86, "Open measurement · Preregistered · 2026")
    s.label(1200 - M, 86, "v0.1.0-preregistration", anchor="end")

    size = 150
    left, right = "artifact", "rot"
    wl = DISPLAY.width(left, size)
    # Bodoni's hyphen is a hairline at this size: the one accent of the page is drawn as a
    # solid bar instead, at x-height middle.
    gap = 18
    y = 252
    s.text(M - 6, y, left, face=DISPLAY, size=size, fill=t.ink)
    bar_x = M - 6 + wl + 8
    s.rect(bar_x, y - 44, 44, 11, t.accent)
    s.text(bar_x + 44 + gap - 8, y, right, face=DISPLAY, size=size, fill=t.ink)

    s.text(M, 312, "Do the code and data links announced in scientific papers still resolve,",
           size=24, fill=t.text)
    s.text(M, 344, "and how fast do they die?", size=24, fill=t.text)

    s.line(M, 384, 1200 - M, 384, stroke=t.rule)
    stats = [
        ("40,000", "papers in a frozen sample"),
        ("20", "strata · 5 years × 4 fields"),
        ("3,988", "links, probed on 3 dates"),
        ("98.6%", "control-set accuracy"),
    ]
    col = (1200 - 2 * M) / len(stats)
    for i, (big, small) in enumerate(stats):
        x = M + i * col
        if i:
            s.line(x, 384, x, 446, stroke=t.rule)
        pad = 0 if i == 0 else 20
        s.text(x + pad, 424, big, face=DISPLAY, size=30, fill=t.ink)
        s.label(x + pad, 446, small, size=11)
    return s


def by_kind(t: Theme) -> Svg:
    s = Svg(1200, 560, t, "Dead-link rate by kind of link, S1 run")
    s.label(M, 64, "Finding 1 · exploratory contrast")
    s.text(M, 118, "Repositories survive. The open web does not.", face=DISPLAY, size=46, fill=t.ink)
    s.text(M, 154, "Share of links confirmed dead after three probes on three dates · S1 run, "
           "3,988 links, Sept–Oct 2026", size=17, fill=t.muted)

    rows = [
        ("Generic web URLs", "generic_url", t.accent),
        ("Dataset DOIs", "dataset_doi", t.faint),
        ("Code repositories", "code_repo", t.ink),
        ("Data repositories", "data_repo", t.ink),
    ]
    x0, x1 = 330, 1010
    scale = (x1 - x0) / 0.60
    top, row_h = 206, 66
    for tick in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        x = x0 + tick * scale
        s.line(x, top - 14, x, top + row_h * len(rows) - 10, stroke=t.rule)
        s.text(x, top + row_h * len(rows) + 12, pct(tick, 0), size=13, fill=t.muted, anchor="middle")

    for i, (name, key, color) in enumerate(rows):
        r, low, high, n = rate(BY_KIND[key])
        y = top + i * row_h
        s.text(M, y + 18, name, face=SANS_BOLD, size=19, fill=t.ink)
        s.text(M, y + 40, f"n = {n:,}" + ("  · too few to read" if n < 30 else ""), size=14,
               fill=t.muted)
        s.rect(x0, y + 4, r * scale, 30, color)
        # Wilson 95% interval: drawn in the bar's contrast colour where it crosses the bar,
        # in ink outside it, so that it stays legible on red, black and grey alike.
        on_bar = t.ink if color == t.faint else t.bg
        inside = (low, min(high, r))
        outside = (max(low, r), high)
        if inside[1] > inside[0]:
            s.line(x0 + inside[0] * scale, y + 19, x0 + inside[1] * scale, y + 19,
                   stroke=on_bar, width=1.5)
        if outside[1] > outside[0]:
            s.line(x0 + outside[0] * scale, y + 19, x0 + outside[1] * scale, y + 19,
                   stroke=t.ink, width=1.5)
        for b in (low, high):
            s.line(x0 + b * scale, y + 12, x0 + b * scale, y + 26,
                   stroke=on_bar if b < r else t.ink, width=1.5)
        s.text(1200 - M, y + 30, pct(r), face=DISPLAY, size=34,
               fill=t.accent if key == "generic_url" else t.ink, anchor="end")

    s.line(M, 500, 1200 - M, 500, stroke=t.rule)
    s.text(M, 528, "Bars: point estimate. Whiskers: Wilson 95% interval. Unknown (crawler failed) "
           "is never in a denominator; restricted counts as alive.", size=14, fill=t.muted)
    return s


def by_year(t: Theme) -> Svg:
    s = Svg(1200, 600, t, "Dead-link rate by publication year, S1 run")
    s.label(M, 64, "Finding 2 · preregistered test, S1 run")
    s.text(M, 118, "An age effect exists, but it is too small.", face=DISPLAY, size=46, fill=t.ink)
    s.text(M, 154, "Dead-link rate by year of publication, all link kinds", size=17, fill=t.muted)

    base, topv = 500, 200
    scale = (base - topv) / 0.40
    x0, x1 = M + 50, 690
    for tick in (0, 0.1, 0.2, 0.3, 0.4):
        y = base - tick * scale
        s.line(x0, y, x1, y, stroke=t.rule)
        s.text(x0 - 12, y + 5, pct(tick, 0), size=13, fill=t.muted, anchor="end")

    years = list(BY_YEAR)
    step = (x1 - x0) / len(years)
    bw = 64
    for i, year in enumerate(years):
        r, low, high, n = rate(BY_YEAR[year])
        cx = x0 + step * (i + 0.5)
        s.rect(cx - bw / 2, base - r * scale, bw, r * scale, t.ink)
        s.line(cx, base - high * scale, cx, base - low * scale, stroke=t.muted, width=1.5)
        for b in (low, high):
            s.line(cx - 9, base - b * scale, cx + 9, base - b * scale, stroke=t.muted, width=1.5)
        s.text(cx, base - high * scale - 12, pct(r), face=SANS_BOLD, size=16, fill=t.ink,
               anchor="middle")
        s.text(cx, base + 34, str(year), face=DISPLAY, size=28, fill=t.ink, anchor="middle")
        s.text(cx, base + 56, f"n = {n}", size=13, fill=t.muted, anchor="middle")

    ty = base - 0.20 * scale
    s.line(x0, ty, x1, ty, stroke=t.accent, width=2, dash="8 6")
    s.label(x1 + 10, ty - 4, "H1", fill=t.accent, size=12)
    s.label(x1 + 10, ty + 14, "20%", fill=t.accent, size=12)

    px = 820
    s.line(px - 30, 196, px - 30, 556, stroke=t.rule)
    s.label(px, 214, "Preregistered verdict")
    s.text(px, 274, "Grey zone", face=DISPLAY, size=54, fill=t.ink)
    items = [
        ("2018 dead rate", pct(REF_RATE), f"95% CI {pct(REF_CI[0])}–{pct(REF_CI[1])}", "needs > 20%: met"),
        ("2010 vs 2025 gap", f"{GAP * 100:.1f} pts", f"95% CI {GAP_CI[0] * 100:.1f}–{GAP_CI[1] * 100:.1f}",
         "needs ≥ 15 pts: missed"),
    ]
    y = 330
    for name, value, ci, verdict in items:
        s.label(px, y, name, size=11)
        s.text(px, y + 38, value, face=DISPLAY, size=36, fill=t.ink)
        s.text(px, y + 62, ci, size=14, fill=t.muted)
        s.text(px, y + 84, verdict, face=SANS_BOLD, size=14,
               fill=t.accent if verdict.endswith("missed") else t.ink)
        y += 118
    s.text(px, 572, f"Unknown: {pct(UNKNOWN_RATE)} of links (criterion < 5%).", size=13,
           fill=t.muted)
    return s


def pipeline(t: Theme) -> Svg:
    s = Svg(1200, 520, t, "Method: from sample to survival curve")
    s.label(M, 64, "Method")
    s.text(M, 118, "Six steps, each with a pass criterion.", face=DISPLAY, size=46, fill=t.ink)

    steps = [
        ("01", "Sample", "OpenAlex, seeded and frozen", "40,000 papers · 20 strata"),
        ("02", "Full text", "Open copies only, never forced", "repository first, publisher last"),
        ("03", "Extract", "Text ∪ publisher link markup", "on-request, malformed: apart"),
        ("04", "Probe", "APIs first, never the HTML", "three dates spanning ≥ 10 days"),
        ("05", "Resolve", "alive · dead · restricted · unknown", "unknown never in a rate"),
        ("06", "Analyse", "Isotonic survival, Wilson CIs", "rule frozen on 21 Sept 2026"),
    ]
    cols, top, cell_h = 3, 160, 160
    cw = (1200 - 2 * M) / cols
    s.line(M, top, 1200 - M, top, stroke=t.ink, width=2)
    for i, (num, name, a, b) in enumerate(steps):
        r, c = divmod(i, cols)
        x, y = M + c * cw, top + r * cell_h
        if c:
            s.line(x, y + 18, x, y + cell_h - 18, stroke=t.rule)
        pad = 0 if c == 0 else 28
        s.text(x + pad, y + 64, num, face=DISPLAY, size=44, fill=t.accent if num == "04" else t.ink)
        s.label(x + pad + 78, y + 56, name, fill=t.ink, size=14)
        s.text(x + pad, y + 104, a, size=17, fill=t.text)
        s.text(x + pad, y + 130, b, size=15, fill=t.muted)
    s.line(M, top + cell_h, 1200 - M, top + cell_h, stroke=t.rule)
    s.line(M, top + 2 * cell_h, 1200 - M, top + 2 * cell_h, stroke=t.ink, width=2)
    return s


def timeline(t: Theme) -> Svg:
    s = Svg(1200, 400, t, "Preregistration timeline")
    s.label(M, 64, "Preregistration")
    s.text(M, 118, "The rule was written before the data.", face=DISPLAY, size=46, fill=t.ink)

    import datetime as dt

    start, end = dt.date(2026, 9, 18), dt.date(2026, 10, 17)
    x0, x1, axis = M + 10, 1200 - M - 10, 250
    per_day = (x1 - x0) / (end - start).days

    def xd(d: dt.date) -> float:
        return x0 + (d - start).days * per_day

    s.line(x0, axis, x1, axis, stroke=t.ink, width=1.5)
    for k in range((end - start).days + 1):
        d = start + dt.timedelta(days=k)
        h = 7 if d.day in (1, 10, 20) or d.weekday() == 0 else 3
        s.line(xd(d), axis - h, xd(d), axis + h, stroke=t.faint)
    for d, txt in ((dt.date(2026, 9, 18), "Sept"), (dt.date(2026, 10, 1), "Oct")):
        s.label(xd(d), axis + 26, txt, size=11)

    events = [  # date, above?, lines, pending
        (dt.date(2026, 9, 20), True, ["20 Sept", "Sample frozen"], False),
        (dt.date(2026, 9, 21), False, ["21 Sept", "Analysis and decision", "code written · pass 1"], False),
        (dt.date(2026, 9, 26), True, ["26 Sept", "Pass 2"], False),
        (dt.date(2026, 10, 4), False, ["4 Oct", "Pass 3 → grey zone", "Extension declared"], False),
        (dt.date(2026, 10, 10), True, ["10 Oct", "Software Heritage", "archive"], False),
        (dt.date(2026, 10, 15), False, ["15 Oct", "Extension verdict"], True),
    ]
    for d, above, lines, pending in events:
        x = xd(d)
        anchor = "end" if x > 1000 else "start"
        tx = x + (-10 if anchor == "end" else 10)
        if above:
            s.line(x, axis - 10, x, axis - 74, stroke=t.ink)
            for j, ln in enumerate(lines):
                y = axis - 92 + j * 22 - 22 * (len(lines) - 2)
                s.text(tx, y, ln, face=SANS_BOLD if j == 0 else SANS, size=15 if j else 14,
                       fill=t.ink if j == 0 else t.text, anchor=anchor)
        else:
            s.line(x, axis + 10, x, axis + 50, stroke=t.accent if pending else t.ink)
            for j, ln in enumerate(lines):
                s.text(tx, axis + 66 + j * 22, ln, face=SANS_BOLD if j == 0 else SANS,
                       size=15 if j else 14,
                       fill=(t.accent if pending else t.ink) if j == 0 else t.text, anchor=anchor)
        if pending:
            s.circle(x, axis, 7, fill=t.bg, stroke=t.accent, width=2.5)
        else:
            s.circle(x, axis, 6, fill=t.ink)
    return s


FIGURES = {
    "hero": hero,
    "by-kind": by_kind,
    "by-year": by_year,
    "method": pipeline,
    "timeline": timeline,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in FIGURES.items():
        for theme in (LIGHT, DARK):
            path = OUT / f"{name}-{theme.name}.svg"
            path.write_text(build(theme).render(), encoding="utf-8")
            print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
