"""Thin HTTP client for the CineBook FastAPI backend.

The frontend never talks to MongoDB directly; every read and write goes through the API,
which performs all validation, pricing and seat-locking.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
CURRENCY = os.getenv("CURRENCY_SYMBOL", "₹")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0, code: str = "error", data: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.data = data or {}


@st.cache_resource
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "User-Agent": "CineBook-Streamlit"})
    return s


def request(method: str, path: str, *, params: dict | None = None, json: Any = None, auth: bool = True,
            raw: bool = False, timeout: float = 20) -> Any:
    headers = {}
    token = st.session_state.get("token")
    if auth and token:
        headers["Authorization"] = f"Bearer {token}"
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "", [])}
    try:
        resp = _session().request(method, f"{API_BASE_URL}{path}", params=params, json=json, headers=headers,
                                  timeout=timeout)
    except requests.ConnectionError:
        raise ApiError(f"Cannot reach the CineBook API at {API_BASE_URL}. Make sure the backend is running "
                       "(see README, Terminal 1) and refresh this page.", 0, "api_unreachable") from None
    except requests.Timeout:
        raise ApiError("The server took too long to respond. Please try again.", 0, "timeout") from None
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except ValueError:
            data = {"detail": resp.text[:200] or resp.reason}
        message = data.get("detail") if isinstance(data.get("detail"), str) else "Request failed"
        if resp.status_code == 401 and token:
            # Token expired or invalid: drop the session so the user can log in again.
            for key in ("token", "user"):
                st.session_state.pop(key, None)
        raise ApiError(message, resp.status_code, data.get("code", "error"), data)
    if raw:
        return resp.content
    if not resp.content:
        return None
    return resp.json()


def get(path: str, **kw: Any) -> Any:
    return request("GET", path, **kw)


def post(path: str, json: Any = None, **kw: Any) -> Any:
    return request("POST", path, json=json, **kw)


def put(path: str, json: Any = None, **kw: Any) -> Any:
    return request("PUT", path, json=json, **kw)


def delete(path: str, **kw: Any) -> Any:
    return request("DELETE", path, **kw)


@st.cache_data(ttl=60, show_spinner=False)
def cached_get(path: str, params_items: tuple = ()) -> Any:
    """Cache public, non-personal GET requests briefly (movie lists, filters, offers)."""
    return request("GET", path, params=dict(params_items), auth=False)
