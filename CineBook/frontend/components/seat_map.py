"""Interactive seat map built from native Streamlit buttons, styled per seat status with CSS."""
from __future__ import annotations

import streamlit as st

from components.ui import esc, money

CATEGORY_COLORS = {"regular": "#2DD4BF", "premium": "#F5C542", "recliner": "#A78BFA"}


def _css(rows: list[dict], selected: set[str]) -> str:
    groups: dict[str, list[str]] = {}
    for r in rows:
        for s in r["seats"]:
            status = "selected" if s["seat_id"] in selected and s["status"] == "available" else s["status"]
            key = f"cat_{r['category']}" if status == "available" else status
            groups.setdefault(key, []).append(f".st-key-s_{s['seat_id']} button")
    rules = []
    for cat, color in CATEGORY_COLORS.items():
        if f"cat_{cat}" in groups:
            rules.append(f"{', '.join(groups[f'cat_{cat}'])}{{background:#191922 !important; color:#E9E9F1 !important;"
                         f" border:1.5px solid {color} !important;}}")
            rules.append(f"{', '.join(s + ':hover' for s in groups[f'cat_{cat}'])}{{background:{color}33 !important;}}")
    styles = {
        "selected": "background:#E50914 !important; color:#fff !important; border:1.5px solid #FF4D57 !important;"
                    "box-shadow:0 0 12px rgba(229,9,20,.6);",
        "booked": "background:#2B2B35 !important; color:#5E5E6E !important; border:1px solid #2B2B35 !important; opacity:1 !important;",
        "held": "background:repeating-linear-gradient(45deg,#5A4410,#5A4410 4px,#3A2C0A 4px,#3A2C0A 8px) !important;"
                "color:#E7C66A !important; border:1px dashed #F59E0B !important; opacity:1 !important;",
        "mine": "background:#1D4ED8 !important; color:#fff !important; border:1px solid #60A5FA !important; opacity:1 !important;",
        "blocked": "background:transparent !important; color:transparent !important; border:1px dashed #22222C !important; opacity:1 !important;",
    }
    for status, css in styles.items():
        if status in groups:
            rules.append(f"{', '.join(groups[status])}{{{css}}}")
    return "<style>" + "\n".join(rules) + "</style>"


def legend(prices: dict, currency_fmt=money) -> None:
    items = [f'<span><i style="border:1.5px solid {c};background:#191922"></i>{cat.title()} · {currency_fmt(prices.get(cat, 0))}</span>'
             for cat, c in CATEGORY_COLORS.items() if cat in prices]
    items += [
        '<span><i style="background:#E50914"></i>Selected</span>',
        '<span><i style="background:#1D4ED8"></i>Held by you</span>',
        '<span><i style="background:repeating-linear-gradient(45deg,#5A4410,#5A4410 3px,#3A2C0A 3px,#3A2C0A 6px);'
        'border:1px dashed #F59E0B"></i>Temporarily reserved</span>',
        '<span><i style="background:#2B2B35"></i>Booked</span>',
    ]
    st.markdown(f'<div class="cb-legend">{"".join(items)}</div>', unsafe_allow_html=True)


def _toggle(seat_id: str, max_seats: int) -> None:
    sel: list = st.session_state.selected_seats
    if seat_id in sel:
        sel.remove(seat_id)
    elif len(sel) >= max_seats:
        st.session_state["seat_warning"] = f"You can select up to {max_seats} seats per booking."
    else:
        sel.append(seat_id)


def render(seat_data: dict, *, interactive: bool = True) -> None:
    rows = seat_data["rows"]
    selected = set(st.session_state.get("selected_seats", []))
    st.markdown(_css(rows, selected), unsafe_allow_html=True)
    st.markdown('<div class="cb-screen"><div class="curve"></div><div class="lbl">SCREEN THIS WAY</div></div>',
                unsafe_allow_html=True)
    max_seats = seat_data.get("max_seats_per_booking", 10)
    with st.container(key="seatgrid"):
        last_cat = None
        for r in rows:
            if r["category"] != last_cat:
                st.markdown(f'<div class="cb-catlabel">{esc(r["category"])} · {money(r["price"])}</div>',
                            unsafe_allow_html=True)
                last_cat = r["category"]
            with st.container(horizontal=True, wrap=False, horizontal_alignment="center", vertical_alignment="center",
                              gap=None, key=f"row_{r['row']}"):
                st.markdown(f'<div class="cb-rowlabel">{esc(r["row"])}</div>', unsafe_allow_html=True, width="content")
                for s in r["seats"]:
                    status = s["status"]
                    clickable = interactive and status == "available"
                    label = str(s["number"]) if status != "blocked" else "·"
                    st.button(label, key=f"s_{s['seat_id']}", disabled=not clickable, on_click=_toggle,
                              args=(s["seat_id"], max_seats), help=f"{s['seat_id']} · {r['category'].title()} · "
                              f"{status.replace('held', 'temporarily reserved').replace('mine', 'held by you')}")
                    if s.get("aisle_after"):
                        st.markdown('<div class="cb-aisle"></div>', unsafe_allow_html=True, width="content")
                st.markdown(f'<div class="cb-rowlabel">{esc(r["row"])}</div>', unsafe_allow_html=True, width="content")
    legend(seat_data["prices"])


def static_preview(layout: dict, prices: dict | None = None) -> None:
    """Read-only HTML preview for the admin layout editor."""
    blocked = set(layout.get("blocked_seats") or [])
    aisles = set(layout.get("aisles_after") or [])
    html_rows = []
    for r in layout["rows"]:
        color = CATEGORY_COLORS.get(r["category"], "#888")
        cells = [f'<span style="width:20px;display:inline-block;color:#888;font-size:11px">{esc(r["row"])}</span>']
        for n in range(1, int(r["seats"]) + 1):
            sid = f"{r['row']}{n}"
            style = ("border:1px dashed #333;background:transparent" if sid in blocked
                     else f"border:1.5px solid {color};background:#191922")
            cells.append(f'<span title="{sid}" style="display:inline-block;width:16px;height:14px;margin:2px;'
                         f'border-radius:4px 4px 2px 2px;{style}"></span>')
            if n in aisles:
                cells.append('<span style="display:inline-block;width:12px"></span>')
        html_rows.append(f'<div style="white-space:nowrap;text-align:center">{"".join(cells)}</div>')
    st.markdown('<div class="cb-screen" style="width:60%"><div class="curve"></div><div class="lbl">SCREEN</div></div>'
                f'<div style="overflow-x:auto">{"".join(html_rows)}</div>', unsafe_allow_html=True)
    if prices:
        legend(prices)
