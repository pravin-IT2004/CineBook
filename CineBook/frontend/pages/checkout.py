import streamlit as st
import streamlit.components.v1 as components

from components.posters import poster_css
from components.ui import call, empty_state, esc, money, nice_date, page_header
from services import api_client as api
from services import state

state.require_customer()
hold = st.session_state.get("hold")
if not hold and st.session_state.get("hold_error"):
    msg, sid = st.session_state.hold_error
    empty_state("⌛", "Seats no longer held", msg)
    if st.button("Choose seats again", type="primary"):
        st.session_state.hold_error = None
        state.goto("seats", showtime_id=sid)
    st.stop()
if not hold:
    empty_state("🛒", "Nothing to check out", "Select seats for a showtime first.")
    if st.button("Browse movies", type="primary"):
        state.goto("movies")
    st.stop()

fresh = call(api.get, f"/api/holds/{hold['id']}")
if not fresh:
    st.stop()
if fresh["status"] != "active" or fresh["seconds_left"] <= 0:
    empty_state("⌛", "Your seat hold has expired", "Seats are only held for a few minutes. Please select them again.")
    if st.button("Choose seats again", type="primary"):
        state.goto("seats", showtime_id=fresh["showtime_id"], hold=None)
    st.stop()
hold = fresh
st.session_state.hold = hold

show = call(api.get, f"/api/showtimes/{hold['showtime_id']}")
if not show:
    st.stop()
policy = call(api.get, "/api/settings/policy") or {}

page_header("Review & confirm", "Check your booking details, apply an offer and confirm.", "Checkout")

# Client-side countdown (the server enforces the real expiry).
components.html(f"""
<div style="font-family:Inter,sans-serif;background:#1B1B25;border:1px solid #2A2A37;border-radius:12px;padding:10px 14px;color:#F4F4F6;display:flex;align-items:center;gap:12px">
  <span style="font-size:20px">⏳</span>
  <div style="flex:1"><div style="font-size:13px;color:#A0A0B4">Seats held for you</div>
  <div style="height:6px;background:#2A2A37;border-radius:4px;margin-top:6px;overflow:hidden"><div id="bar" style="height:6px;background:#E50914;width:100%"></div></div></div>
  <b id="t" style="font-size:22px;min-width:64px;text-align:right">--:--</b>
</div>
<script>
const total = {hold['seconds_left']}; let left = total;
function tick(){{ const m=Math.floor(Math.max(left,0)/60), s=Math.max(left,0)%60;
  document.getElementById('t').textContent = (m<10?'0':'')+m+':'+(s<10?'0':'')+s;
  document.getElementById('bar').style.width = (100*Math.max(left,0)/{max(1, policy.get('hold_minutes', 5) * 60)})+'%';
  if(left<=0){{ document.getElementById('t').textContent='Expired'; document.getElementById('t').style.color='#FF5C66'; return; }}
  left -= 1; setTimeout(tick, 1000); }}
tick();
</script>""", height=70)

left, right = st.columns([1.7, 1.2], gap="large")
with left:
    m = show["movie"]
    st.markdown(f"""<div class="cb-panel" style="display:flex;gap:16px">
<div style="width:90px;min-width:90px;align-self:flex-start;aspect-ratio:2/3;border-radius:10px;background-size:cover;background-position:center;background-image:{poster_css(m)}"></div>
<div><div class="cb-display" style="font-size:30px;line-height:1">{esc(m['title'])}</div>
<div class="cb-muted" style="margin-bottom:10px">{esc(m.get('certificate') or '')} · {esc(show['language'])} · {esc(show['format'])}</div>
<div class="cb-kv"><div class="k">Cinema</div><div>{esc(show['cinema_name'])}</div>
<div class="k">Screen</div><div>{esc(show['screen_name'])}</div>
<div class="k">Date</div><div>{esc(nice_date(show['local_date']))}</div>
<div class="k">Time</div><div>{esc(show['local_time'])}</div>
<div class="k">Seats</div><div><b>{esc(', '.join(hold['seats']))}</b></div></div></div></div>""", unsafe_allow_html=True)
    st.write("")
    st.markdown("#### Offers & coupons")
    applied = st.session_state.get("applied_offer")
    with st.form("coupon_form", border=False):
        cc1, cc2 = st.columns([2, 1], vertical_alignment="bottom")
        code = cc1.text_input("Coupon code", value=applied["code"] if applied else "", placeholder="e.g. WELCOME10",
                              label_visibility="collapsed").strip().upper()
        apply_clicked = cc2.form_submit_button("Apply", width="stretch")
    if apply_clicked:
        if not code:
            st.warning("Enter a coupon code first.")
        else:
            try:
                st.session_state.applied_offer = api.post("/api/offers/validate", {"code": code, "hold_id": hold["id"]})
                st.rerun()
            except api.ApiError as err:
                st.session_state.applied_offer = None
                st.error(err.message)
    if applied:
        st.success(f"**{applied['code']}** applied — {applied['title']} (you save {money(applied['discount'])})")
        if st.button("Remove coupon"):
            st.session_state.applied_offer = None
            st.rerun()
    offers = call(api.cached_get, "/api/offers") or []
    live = [o for o in offers if o.get("is_live")]
    if live:
        with st.expander(f"Available offers ({len(live)})"):
            for o in live:
                st.markdown(f"**{o['code']}** · {o['label']} · min. booking {money(o.get('min_booking_value', 0))}  \n"
                            f"<span class='cb-muted'>{esc(o.get('description') or o['title'])}</span>",
                            unsafe_allow_html=True)

with right:
    st.markdown("#### Price breakdown")
    cats: dict[str, list[float]] = {}
    for li in hold["line_items"]:
        cats.setdefault(li["category"], []).append(li["price"])
    rows = "".join(f"<div style='display:flex;justify-content:space-between'><span>{c.title()} × {len(p)} @ {money(p[0])}"
                   f"</span><span>{money(sum(p))}</span></div>" for c, p in cats.items())
    discount = applied["discount"] if applied else 0.0
    total = round(hold["subtotal"] - discount, 2)
    disc_row = (f"<div style='display:flex;justify-content:space-between;color:#4ADE80'><span>Discount ({esc(applied['code'])})"
                f"</span><span>− {money(discount)}</span></div>") if applied else ""
    st.markdown(f"""<div class="cb-panel">{rows}
<div style="display:flex;justify-content:space-between;border-top:1px solid #2A2A37;margin-top:8px;padding-top:8px">
<span>Original price</span><span>{money(hold['subtotal'])}</span></div>{disc_row}
<div style="display:flex;justify-content:space-between;font-size:22px;font-weight:800;margin-top:8px"><span>Final amount</span>
<span>{money(total)}</span></div></div>""", unsafe_allow_html=True)
    st.info("💳 **No online payment is taken.** This demo has no payment gateway — the final amount is payable at "
            "the cinema counter.")
    if policy.get("text"):
        st.caption(policy["text"])
    agree = st.checkbox("I have read the booking & cancellation policy")
    if st.button("Confirm booking", type="primary", width="stretch", disabled=not agree):
        with st.spinner("Confirming your seats..."):
            try:
                booking = api.post("/api/bookings", {"hold_id": hold["id"],
                                                     "offer_code": applied["code"] if applied else None})
                state.flash(f"Booking confirmed! Reference {booking['reference']}", "success")
                state.goto("ticket", booking_id=booking["id"], hold=None, applied_offer=None, selected_seats=[])
            except api.ApiError as err:
                if err.code in ("hold_expired", "seats_unavailable", "hold_used", "booking_closed"):
                    st.session_state.hold = None
                    st.session_state.hold_error = (err.message, hold["showtime_id"])
                    st.rerun()
                elif err.code.startswith("offer_"):
                    st.session_state.applied_offer = None
                    st.error(f"{err.message}. The coupon was removed - you can confirm without it.")
                else:
                    st.error(err.message)
    if st.button("Release seats", width="stretch"):
        call(api.delete, f"/api/holds/{hold['id']}")
        state.flash("Your seats were released.", "info")
        state.goto("seats", showtime_id=hold["showtime_id"], hold=None, applied_offer=None)
