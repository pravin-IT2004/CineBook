"""Cross-cutting helpers: booking policy settings, audit logs, in-app notifications and optional e-mail."""
from __future__ import annotations

import copy
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from pymongo.database import Database

from ..config import get_settings
from ..models.constants import DEFAULT_POLICY
from ..utils.timeutils import to_local, utcnow

log = logging.getLogger("cinebook")
POLICY_ID = "booking_policy"


# ---------------------------------------------------------------- settings
def get_policy(db: Database) -> dict[str, Any]:
    policy = copy.deepcopy(DEFAULT_POLICY)
    stored = db.settings.find_one({"_id": POLICY_ID}) or {}
    for key, value in stored.items():
        if key == "_id":
            continue
        if key == "default_prices" and isinstance(value, dict):
            policy["default_prices"].update(value)
        elif key in policy:
            policy[key] = value
    return policy


def update_policy(db: Database, data: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    data = {k: v for k, v in data.items() if k in DEFAULT_POLICY}
    db.settings.update_one({"_id": POLICY_ID}, {"$set": {**data, "updated_at": utcnow()}}, upsert=True)
    audit(db, actor, "settings.update", "settings", POLICY_ID, data)
    return get_policy(db)


# ---------------------------------------------------------------- audit log
def audit(db: Database, actor: dict[str, Any] | None, action: str, entity: str, entity_id: Any = None,
          details: dict[str, Any] | None = None) -> None:
    try:
        db.audit_logs.insert_one(
            {
                "actor_id": actor.get("_id") if actor else None,
                "actor_email": actor.get("email") if actor else "system",
                "action": action,
                "entity": entity,
                "entity_id": str(entity_id) if entity_id is not None else None,
                "details": details or {},
                "created_at": utcnow(),
            }
        )
    except Exception:  # noqa: BLE001 - auditing must never break the main action
        log.exception("Failed to write audit log for %s", action)


# ---------------------------------------------------------------- notifications
def notify(db: Database, user_id: Any, title: str, message: str, kind: str = "info") -> None:
    try:
        db.notifications.insert_one(
            {"user_id": user_id, "title": title, "message": message, "kind": kind, "read": False, "created_at": utcnow()}
        )
    except Exception:  # noqa: BLE001
        log.exception("Failed to store notification")


# ---------------------------------------------------------------- e-mail (optional)
def email_enabled() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def send_booking_email(to_email: str, booking: dict[str, Any]) -> None:
    """Best-effort confirmation e-mail. Runs as a FastAPI background task; never raises."""
    if not email_enabled():
        return
    s = get_settings()
    try:
        show = to_local(booking["show_start"]).strftime("%a %d %b %Y, %I:%M %p")
        seats = ", ".join(x["seat_id"] for x in booking["seats"])
        msg = EmailMessage()
        msg["Subject"] = f"CineBook booking {booking['reference']} – {booking['movie_snapshot']['title']}"
        msg["From"] = s.smtp_from
        msg["To"] = to_email
        msg.set_content(
            f"Your CineBook booking is confirmed.\n\n"
            f"Reference: {booking['reference']}\nMovie: {booking['movie_snapshot']['title']}\n"
            f"Cinema: {booking['cinema_snapshot']['name']} – {booking['screen_snapshot']['name']}\n"
            f"Show: {show}\nSeats: {seats}\nAmount payable: {s.currency_symbol}{booking['total']:.2f}\n\n"
            f"No online payment was taken. Please pay at the cinema counter.\n"
            f"Open 'My Bookings' in CineBook to view or download your QR ticket."
        )
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            if s.smtp_use_tls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        log.info("Confirmation e-mail sent for booking %s", booking["reference"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not send confirmation e-mail for %s: %s", booking.get("reference"), exc)
