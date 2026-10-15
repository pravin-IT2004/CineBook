import streamlit as st

from components.ui import badge, call, empty_state, esc, fmt_dt, money, page_header

from services import api_client as api

page_header("Offers", "Apply a coupon code at checkout. Discounts are validated by the server.", "Save more")
offers = call(api.cached_get, "/api/offers")
if offers is None:
    st.stop()
if not offers:
    empty_state("🏷️", "No offers right now", "There are no active promotions at the moment. Check back soon!")
    st.stop()

COLS = 3
for start in range(0, len(offers), COLS):
    for col, o in zip(st.columns(COLS), offers[start:start + COLS]):
        with col:
            status = badge("Live", "green") if o.get("is_live") else badge(f"Starts {fmt_dt(o['start_date'], '%d %b')}", "blue")
            extras = [f"Min. booking {money(o.get('min_booking_value', 0))}"]
            if o.get("per_user_limit"):
                extras.append(f"{o['per_user_limit']} use(s) per customer")
            if o.get("remaining_uses") is not None:
                extras.append(f"{o['remaining_uses']} left")
            st.markdown(f"""<div class="cb-offer">{status}<div class="label">{esc(o['label'])}</div>
<div class="code">{esc(o['code'])}</div><div><b>{esc(o['title'])}</b></div>
<div class="desc">{esc(o.get('description') or '')}</div>
<div class="desc">{' · '.join(esc(x) for x in extras)}<br/>Valid until {fmt_dt(o['end_date'], '%d %b %Y')}</div></div>""",
                        unsafe_allow_html=True)
            st.code(o["code"], language=None)
