"""Poster artwork. Real poster URLs are used when available; otherwise an original generated
SVG poster (gradient + title typography) is shown. CSS layers the generated art underneath the
remote image, so a broken or blocked poster URL falls back gracefully without JavaScript."""
from __future__ import annotations

import base64
import hashlib
import html
import textwrap
from functools import lru_cache

FALLBACK = ["#E50914", "#1F1F2E"]


def _palette(movie: dict) -> tuple[str, str]:
    cols = (movie.get("poster_colors") or []) + FALLBACK
    return cols[0], cols[1]


def _fit(line: str, size: int) -> str:
    """Squeeze long lines so they never overflow the poster, whatever font is available."""
    estimate = len(line) * size * 0.62
    return f' textLength="{min(260, estimate):.0f}" lengthAdjust="spacingAndGlyphs"' if estimate > 200 else ""


@lru_cache(maxsize=256)
def _svg(title: str, subtitle: str, c1: str, c2: str) -> str:
    seed = int(hashlib.md5(title.encode()).hexdigest(), 16)
    cx, cy, r = 120 + seed % 120, 120 + (seed >> 8) % 150, 90 + (seed >> 16) % 70
    lines = textwrap.wrap(title.upper(), 11)[:3]
    size = 40 if max((len(x) for x in lines), default=0) <= 9 else 34
    y0 = 404 - (len(lines) - 1) * size * 1.05  # last line sits just above the genre caption
    text = "".join(
        f'<text x="150" y="{y0 + i * size * 1.05:.0f}" text-anchor="middle" font-family="Bebas Neue, Impact, '
        f'Arial Narrow, sans-serif" font-size="{size}" letter-spacing="2" fill="#fff"'
        f'{_fit(t, size)}>{html.escape(t)}</text>'
        for i, t in enumerate(lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c2}"/>
<stop offset="1" stop-color="#07070A"/></linearGradient>
<radialGradient id="o" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{c1}" stop-opacity=".95"/>
<stop offset="1" stop-color="{c1}" stop-opacity="0"/></radialGradient></defs>
<rect width="300" height="450" fill="url(#g)"/>
<circle cx="{cx}" cy="{cy}" r="{r * 1.9:.0f}" fill="url(#o)"/>
<circle cx="{cx}" cy="{cy}" r="{r * 0.62:.0f}" fill="{c1}" opacity=".9"/>
<g opacity=".18" stroke="#fff">{''.join(f'<line x1="0" y1="{y}" x2="300" y2="{y - 60}"/>' for y in range(40, 520, 26))}</g>
<rect x="0" y="330" width="300" height="120" fill="#000" opacity=".35"/>
{text}
<text x="150" y="434" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="11" letter-spacing="3"
fill="#ddd">{html.escape(subtitle.upper())}</text></svg>"""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def poster_data_uri(movie: dict) -> str:
    c1, c2 = _palette(movie)
    title = movie.get("title") or "CineBook"
    subtitle = " · ".join((movie.get("genres") or [])[:2])
    return _svg(title, subtitle, c1, c2)


def poster_css(movie: dict) -> str:
    """Value for a CSS background-image: remote poster first, generated art underneath."""
    fallback = f"url('{poster_data_uri(movie)}')"
    url = movie.get("poster_url")
    if url and url.startswith(("http://", "https://")):
        return f"url('{html.escape(url, quote=True)}'), {fallback}"
    return fallback
