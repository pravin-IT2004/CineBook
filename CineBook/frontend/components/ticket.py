"""Digital ticket rendering."""
from __future__ import annotations

import base64

import streamlit as st

from components.posters import poster_css
from components.ui import esc, money, status_badge
from services import api_client as api


def render_ticket(b: dict) -> None:
    movie = b["movie_snapshot"]
    qr_html = ""
    if b["status"] == "confirmed":
        try:
            png = api.get(f"/api/bookings/{b['id']}/qr.png", raw=True)
            qr_html = f'<img alt="Ticket QR code" src="data:image/png;base64,{base64.b64encode(png).decode()}"/>'
        except api.ApiError:
            qr_html = '<div style="color:#aaa">QR unavailable</div>'
    else:
        qr_html = '<div style="font-size:42px">🚫</div><div style="color:#ff8a8a">Not valid for entry</div>'
    seats = ", ".join(s["seat_id"] for s in b["seats"])
    cats: dict[str, list[float]] = {}
    for s in b["seats"]:
        cats.setdefault(s["category"], []).append(s["price"])
    price_rows = "".join(
        f'<div class="row"><span>{esc(c.title())} × {len(p)} @ {money(p[0])}</span><span>{money(sum(p))}</span></div>'
        for c, p in cats.items())
    disc = (f'<div class="row disc"><span>Discount ({esc(b["offer"]["code"])})</span><span>− {money(b["discount"])}</span></div>'
            if b.get("offer") else "")
    refund = ""
    if b.get("refund"):
        refund = (f'<div class="row" style="color:#B91C1C"><span>Refund (simulated · pending)</span>'
                  f'<span>{money(b["refund"]["amount"])}</span></div>')
    cls = "cb-ticket cancelled" if b["status"] == "cancelled" else "cb-ticket"
    st.markdown(f"""
<div class="{cls}">
  <div class="main">
    <div class="thumb" style="background-image:{poster_css(movie)}"></div>
    <div class="brand">CINEBOOK</div>
    <div class="movie">{esc(movie['title'])}</div>
    <div class="meta">{esc(movie.get('certificate') or '')} · {esc(b['language'])} · {esc(b['format'])} · {movie.get('duration_minutes') or '?'} min &nbsp; {status_badge(b['status'])}</div>
    <div class="grid">
      <div><div class="k">Cinema</div><div class="v">{esc(b['cinema_snapshot']['name'])}</div></div>
      <div><div class="k">Screen</div><div class="v">{esc(b['screen_snapshot']['name'])}</div></div>
      <div><div class="k">Date</div><div class="v">{esc(b['local_show_date'])}</div></div>
      <div><div class="k">Show time</div><div class="v">{esc(b['local_show_time'])}</div></div>
      <div><div class="k">Seats</div><div class="v">{esc(seats)}</div></div>
      <div><div class="k">Tickets</div><div class="v">{b['seat_count']}</div></div>
    </div>
    <div class="cb-pricebox">{price_rows}
      <div class="row"><span>Subtotal</span><span>{money(b['subtotal'])}</span></div>{disc}
      <div class="row total"><span>Total payable at cinema</span><span>{money(b['total'])}</span></div>{refund}
      <div style="color:#6B6B7B;font-size:11.5px;margin-top:6px">{esc(b['payment']['note'])}</div>
    </div>
  </div>
  <div class="stub">
    {qr_html}
    <div class="ref">{esc(b['reference'])}</div>
    <div style="font-size:11px;color:#aaa">Booking reference · show this QR at the entrance</div>
  </div>
</div>""", unsafe_allow_html=True)


def pdf_download(b: dict, key: str) -> None:
    """Fetch the PDF only when the user asks for it, then offer the download."""
    cache_key = f"pdf_{b['id']}_{b['status']}"
    if cache_key not in st.session_state:
        if st.button("📄 Prepare PDF ticket", key=f"prep_{key}"):
            try:
                st.session_state[cache_key] = api.get(f"/api/bookings/{b['id']}/ticket.pdf", raw=True)
                st.rerun()
            except api.ApiError as err:
                st.error(err.message)
    else:
        st.download_button("⬇️ Download PDF ticket", st.session_state[cache_key], file_name=f"CineBook-{b['reference']}.pdf",
                           mime="application/pdf", key=f"dl_{key}", type="primary")
