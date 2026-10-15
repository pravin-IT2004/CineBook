from urllib.parse import parse_qs, urlparse

import streamlit as st

from components.ui import call, esc, page_header
from services import api_client as api
from services import state

state.require_admin()
page_header("Verify tickets", "Paste the QR link or type the booking reference printed on the ticket.", "Entrance")

raw = st.text_input("QR link or booking reference", placeholder="CB-XXXXXXXX or http://.../api/tickets/verify?ref=...")
ref = raw.strip()
if ref.startswith("http"):
    qs = parse_qs(urlparse(ref).query)
    ref = (qs.get("ref") or [""])[0]
    sig = (qs.get("sig") or [""])[0]
    result = call(api.get, "/api/tickets/verify", params={"ref": ref, "sig": sig}, auth=False) if ref else None
elif ref:
    result = call(api.get, f"/api/admin/tickets/{ref.upper()}")
else:
    result = None

if result:
    ok = result["valid"]
    color = "#22C55E" if ok else "#E50914"
    seats = ", ".join(result.get("seats", []))
    st.markdown(f"""<div class="cb-panel" style="border-color:{color};border-width:2px">
<div style="font-size:42px;font-weight:800;color:{color}">{'✅ VALID' if ok else '⛔ NOT VALID'}</div>
<div style="font-size:16px">{esc(result['reason'])}</div><br/>
<div class="cb-kv"><div class="k">Reference</div><div><b>{esc(result['reference'])}</b></div>
<div class="k">Movie</div><div>{esc(result.get('movie_title', '—'))}</div>
<div class="k">Cinema</div><div>{esc(result.get('cinema', '—'))} · {esc(result.get('screen', ''))}</div>
<div class="k">Show</div><div>{esc(result.get('local_show', '—'))}</div>
<div class="k">Seats</div><div>{esc(seats or '—')} ({result.get('seat_count', 0)})</div></div></div>""",
                unsafe_allow_html=True)
    if ok and st.button("Check in (mark ticket as used)", type="primary"):
        if call(api.post, f"/api/admin/tickets/{result['reference']}/check-in"):
            state.flash(f"{result['reference']} checked in.")
            st.rerun()
