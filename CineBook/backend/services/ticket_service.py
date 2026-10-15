"""QR codes, signed verification links and PDF tickets."""
from __future__ import annotations

import hashlib
import hmac
import io
from typing import Any
from urllib.parse import urlencode

import qrcode
from pymongo.database import Database
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..config import get_settings
from ..models.constants import BookingStatus
from ..utils.timeutils import as_utc, to_local, utcnow

RED = colors.HexColor("#E50914")
INK = colors.HexColor("#111118")
MUTED = colors.HexColor("#6B6B78")


def ticket_signature(reference: str) -> str:
    key = get_settings().jwt_secret.encode("utf-8")
    return hmac.new(key, f"ticket:{reference}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def verification_url(reference: str) -> str:
    base = get_settings().public_api_url.rstrip("/")
    return f"{base}/api/tickets/verify?{urlencode({'ref': reference, 'sig': ticket_signature(reference)})}"


def qr_png(reference: str, box_size: int = 8) -> bytes:
    """The QR encodes only a signed verification URL - no customer personal data."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=2)
    qr.add_data(verification_url(reference))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def verify(db: Database, reference: str, sig: str | None, *, trusted: bool = False) -> dict[str, Any]:
    ref = (reference or "").strip().upper()
    if not trusted and (not sig or not hmac.compare_digest(sig, ticket_signature(ref))):
        return {"valid": False, "reference": ref, "reason": "Invalid or tampered ticket code"}
    b = db.bookings.find_one({"reference": ref})
    if not b:
        return {"valid": False, "reference": ref, "reason": "Ticket not found"}
    now = utcnow()
    info = {
        "reference": ref,
        "status": b["status"],
        "movie_title": b["movie_snapshot"]["title"],
        "cinema": b["cinema_snapshot"]["name"],
        "screen": b["screen_snapshot"]["name"],
        "show_start": b["show_start"],
        "local_show": to_local(b["show_start"]).strftime("%a %d %b %Y, %I:%M %p"),
        "seats": [s["seat_id"] for s in b["seats"]],
        "seat_count": b["seat_count"],
        "checked_in": bool(b.get("checked_in_at")),
    }
    if b["status"] != BookingStatus.CONFIRMED:
        return {"valid": False, **info, "reason": f"Ticket is {b['status']} and not valid for entry"}
    if as_utc(b["show_end"]) < now:
        return {"valid": False, **info, "reason": "This show has already ended"}
    if b.get("checked_in_at"):
        return {"valid": False, **info, "reason": "Ticket has already been used for entry"}
    return {"valid": True, **info, "reason": "Valid ticket"}


def _poster_block(c: canvas.Canvas, x: float, y: float, w: float, h: float, b: dict[str, Any]) -> None:
    cols = (b["movie_snapshot"].get("poster_colors") or ["#E50914", "#1F1F2E"]) + ["#1F1F2E"]
    c.setFillColor(colors.HexColor(cols[1]))
    c.roundRect(x, y, w, h, 4 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor(cols[0]))
    c.circle(x + w * 0.72, y + h * 0.7, w * 0.38, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 30)
    title = b["movie_snapshot"]["title"] or "?"
    initials = "".join(wd[0] for wd in title.split()[:2]).upper()
    c.drawCentredString(x + w / 2, y + h / 2 - 10, initials)


def ticket_pdf(b: dict[str, Any]) -> bytes:
    s = get_settings()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"CineBook ticket {b['reference']}")
    W, H = A4
    left, top = 18 * mm, H - 18 * mm

    # Header band
    c.setFillColor(INK)
    c.rect(0, H - 40 * mm, W, 40 * mm, fill=1, stroke=0)
    c.setFillColor(RED)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(left, H - 22 * mm, "CINEBOOK")
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 10)
    c.drawString(left, H - 30 * mm, "Smart Movie Ticket Booking · E-ticket")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(W - left, H - 22 * mm, b["reference"])
    status = b["status"].upper()
    c.setFillColor(colors.HexColor("#2ECC71") if b["status"] == BookingStatus.CONFIRMED else RED)
    c.drawRightString(W - left, H - 30 * mm, status)

    # Poster + movie
    y0 = top - 40 * mm
    _poster_block(c, left, y0 - 50 * mm, 36 * mm, 50 * mm, b)
    tx = left + 44 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(tx, y0 - 10 * mm, (b["movie_snapshot"]["title"] or "")[:40])
    c.setFont("Helvetica", 10)
    c.setFillColor(MUTED)
    meta = f"{b['movie_snapshot'].get('certificate') or ''} · {b['language']} · {b['format']} · " \
           f"{b['movie_snapshot'].get('duration_minutes') or '?'} min"
    c.drawString(tx, y0 - 17 * mm, meta)

    rows = [
        ("Cinema", f"{b['cinema_snapshot']['name']} – {b['cinema_snapshot'].get('city') or ''}"),
        ("Screen", f"{b['screen_snapshot']['name']} ({b['screen_snapshot'].get('screen_type') or ''})"),
        ("Date", to_local(b["show_start"]).strftime("%A, %d %B %Y")),
        ("Show time", to_local(b["show_start"]).strftime("%I:%M %p")),
        ("Seats", ", ".join(x["seat_id"] for x in b["seats"])),
        ("Tickets", str(b["seat_count"])),
    ]
    yy = y0 - 27 * mm
    for label, value in rows:
        c.setFont("Helvetica", 9)
        c.setFillColor(MUTED)
        c.drawString(tx, yy, label.upper())
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(INK)
        c.drawString(tx + 26 * mm, yy, value[:70])
        yy -= 7 * mm

    # Price breakdown
    yy = y0 - 80 * mm
    c.setStrokeColor(colors.HexColor("#DDDDE3"))
    c.line(left, yy + 6 * mm, W - left, yy + 6 * mm)
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(INK)
    c.drawString(left, yy, "Price breakdown")
    yy -= 8 * mm
    cur = s.currency_symbol if s.currency_symbol.isascii() else "Rs."
    by_cat: dict[str, list[float]] = {}
    for seat in b["seats"]:
        by_cat.setdefault(seat["category"], []).append(seat["price"])
    c.setFont("Helvetica", 10)
    for cat, prices in by_cat.items():
        c.drawString(left, yy, f"{cat.title()} × {len(prices)} @ {cur} {prices[0]:.2f}")
        c.drawRightString(W - left - 70 * mm, yy, f"{cur} {sum(prices):.2f}")
        yy -= 6 * mm
    c.drawString(left, yy, "Subtotal")
    c.drawRightString(W - left - 70 * mm, yy, f"{cur} {b['subtotal']:.2f}")
    yy -= 6 * mm
    if b.get("offer"):
        c.setFillColor(colors.HexColor("#1E8E3E"))
        c.drawString(left, yy, f"Discount ({b['offer']['code']})")
        c.drawRightString(W - left - 70 * mm, yy, f"- {cur} {b['discount']:.2f}")
        c.setFillColor(INK)
        yy -= 6 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, yy, "Total payable at cinema")
    c.drawRightString(W - left - 70 * mm, yy, f"{cur} {b['total']:.2f}")
    if b.get("refund"):
        yy -= 7 * mm
        c.setFont("Helvetica", 9)
        c.setFillColor(RED)
        c.drawString(left, yy, f"Refund: {cur} {b['refund']['amount']:.2f} – simulated / pending (no payment gateway)")

    # QR code
    qr = ImageReader(io.BytesIO(qr_png(b["reference"], box_size=6)))
    qsize = 55 * mm
    c.drawImage(qr, W - left - qsize, y0 - 80 * mm - qsize + 12 * mm, qsize, qsize)
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawCentredString(W - left - qsize / 2, y0 - 80 * mm - qsize + 8 * mm, "Scan at the entrance to verify")

    # Footer
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    notes = [
        "Payment: not collected online. No payment gateway is integrated in this application – pay at the cinema counter.",
        "This ticket is valid only for the show, screen and seats printed above. Cancelled tickets are not valid for entry.",
        f"Generated {to_local(utcnow()).strftime('%d %b %Y %I:%M %p')} · CineBook",
    ]
    fy = 22 * mm
    for n in notes:
        c.drawString(left, fy, n)
        fy -= 5 * mm
    c.showPage()
    c.save()
    return buf.getvalue()
