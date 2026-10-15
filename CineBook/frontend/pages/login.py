import streamlit as st

from components.ui import page_header
from services import api_client as api
from services import state
from services.state import PAGES

if state.logged_in():
    st.info(f"You are logged in as {state.user()['email']}.")
    if st.button("Go to home", type="primary"):
        state.goto("home")
    st.stop()


def after_login() -> None:
    target = st.session_state.pop("after_login", None)
    if state.is_admin():
        state.goto("admin")
    elif target and target in PAGES and target not in ("login",) and not target.startswith("admin"):
        state.goto(target)
    else:
        state.goto("home")


_, mid, _ = st.columns([1, 1.6, 1])
with mid:
    page_header("Welcome to CineBook", "Log in to book seats, or create a free account.", "Account")
    login_tab, register_tab = st.tabs(["Log in", "Create account"])
    with login_tab:
        with st.form("login_form"):
            email = st.text_input("E-mail", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary", width="stretch"):
                if not email or not password:
                    st.error("Please enter your e-mail and password.")
                else:
                    try:
                        state.login(api.post("/api/auth/login", {"email": email, "password": password}, auth=False))
                        state.flash(f"Welcome back, {state.user()['name'].split()[0]}!")
                        after_login()
                    except api.ApiError as err:
                        st.error(err.message)
        st.caption("Administrators log in here too, using the ADMIN_EMAIL / ADMIN_PASSWORD from the .env file.")
    with register_tab:
        with st.form("register_form"):
            name = st.text_input("Full name", max_chars=60)
            r_email = st.text_input("E-mail", key="reg_email")
            phone = st.text_input("Phone (optional)", max_chars=20)
            r_pw = st.text_input("Password", type="password", help="At least 8 characters, including a letter and a number.")
            r_pw2 = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create account", type="primary", width="stretch"):
                if r_pw != r_pw2:
                    st.error("Passwords do not match.")
                else:
                    try:
                        state.login(api.post("/api/auth/register", {"name": name, "email": r_email, "password": r_pw,
                                                                    "phone": phone or None}, auth=False))
                        state.flash("Account created - welcome to CineBook!")
                        after_login()
                    except api.ApiError as err:
                        st.error(err.message)
