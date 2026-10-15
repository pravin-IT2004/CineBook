"""Seat holds, bookings, tickets, offers (customer side) and ticket verification."""
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

from ..auth import get_current_user, require_customer
from ..schemas.booking import BookingIn, BookingOut, CancelIn, HoldIn, HoldOut, OfferValidateIn
from ..schemas.common import page_response
from ..services import booking_service, offer_service, seat_service, support_service, ticket_service
from ..utils.errors import AppError, not_found
from ..utils.ids import serialize, to_oid
from ..utils.timeutils import as_utc, utcnow
from . import db_dep, page_params

router = APIRouter(tags=["Bookings"])


# ---------------------------------------------------------------- holds
@router.post("/api/holds", response_model=HoldOut, status_code=status.HTTP_201_CREATED,
             summary="Temporarily hold seats (default 5 minutes)")
def create_hold(body: HoldIn, user=Depends(require_customer), db=Depends(db_dep)):
    return seat_service.create_hold(db, user, body.showtime_id, body.seats)


@router.get("/api/holds/{hold_id}", response_model=HoldOut)
def get_hold(hold_id: str, user=Depends(get_current_user), db=Depends(db_dep)):
    return seat_service.get_hold(db, user, hold_id)


@router.delete("/api/holds/{hold_id}", response_model=HoldOut, summary="Release held seats")
def release_hold(hold_id: str, user=Depends(get_current_user), db=Depends(db_dep)):
    return seat_service.release_hold(db, user, hold_id)


# ---------------------------------------------------------------- offers (customer)
@router.get("/api/offers", tags=["Offers"], summary="Active promotional offers")
def offers(db=Depends(db_dep)):
    return offer_service.list_public(db)


@router.post("/api/offers/validate", tags=["Offers"], summary="Check a coupon against a seat hold")
def validate_offer(body: OfferValidateIn, user=Depends(require_customer), db=Depends(db_dep)):
    hold = db.seat_holds.find_one({"_id": to_oid(body.hold_id, "Seat hold")})
    if not hold or hold["user_id"] != user["_id"]:
        raise not_found("Seat hold")
    if hold["status"] != "active" or as_utc(hold["expires_at"]) <= utcnow():
        raise AppError(410, "Your seat hold has expired. Please select your seats again.", "hold_expired")
    offer = offer_service.get_by_code(db, body.code)
    discount = offer_service.evaluate(db, offer, hold["subtotal"], user["_id"])
    return {"valid": True, "code": offer["code"], "title": offer["title"], "subtotal": hold["subtotal"],
            "discount": discount, "total": round(hold["subtotal"] - discount, 2)}


# ---------------------------------------------------------------- bookings
@router.get("/api/settings/policy", tags=["Bookings"], summary="Booking & cancellation policy")
def policy(db=Depends(db_dep)):
    return booking_service.policy_summary(db)


@router.post("/api/bookings", response_model=BookingOut, status_code=status.HTTP_201_CREATED,
             summary="Confirm a booking from a seat hold")
def create_booking(body: BookingIn, background: BackgroundTasks, user=Depends(require_customer), db=Depends(db_dep)):
    booking = booking_service.create_booking(db, user, body.hold_id, body.offer_code)
    background.add_task(support_service.send_booking_email, user["email"], booking)
    return booking_service.present(db, booking)


@router.get("/api/bookings", summary="My bookings")
def my_bookings(scope: str = Query("all", pattern="^(all|upcoming|past|cancelled)$"), paging=Depends(page_params),
                user=Depends(get_current_user), db=Depends(db_dep)):
    page, size = paging
    items, total = booking_service.list_for_user(db, user, scope, page, size)
    return page_response(items, total, page, size)


@router.get("/api/bookings/{booking_id}", response_model=BookingOut)
def booking_detail(booking_id: str, user=Depends(get_current_user), db=Depends(db_dep)):
    b = booking_service.get_booking(db, user, booking_id)
    out = booking_service.present(db, b)
    out["verification_url"] = ticket_service.verification_url(b["reference"]) if b["status"] == "confirmed" else None
    return out


@router.post("/api/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel(booking_id: str, body: CancelIn | None = None, user=Depends(get_current_user), db=Depends(db_dep)):
    b = booking_service.cancel_booking(db, user, booking_id, body.reason if body else None)
    return booking_service.present(db, b)


@router.get("/api/bookings/{booking_id}/qr.png", response_class=Response, summary="QR code image for a ticket")
def qr(booking_id: str, user=Depends(get_current_user), db=Depends(db_dep)):
    b = booking_service.get_booking(db, user, booking_id)
    return Response(ticket_service.qr_png(b["reference"]), media_type="image/png")


@router.get("/api/bookings/{booking_id}/ticket.pdf", response_class=Response, summary="Download the ticket as PDF")
def ticket_pdf(booking_id: str, user=Depends(get_current_user), db=Depends(db_dep)):
    b = booking_service.get_booking(db, user, booking_id)
    if b["status"] not in ("confirmed", "cancelled"):
        raise AppError(409, "A ticket is only available for confirmed bookings", "no_ticket")
    return Response(ticket_service.ticket_pdf(b), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="CineBook-{b["reference"]}.pdf"'})


# ---------------------------------------------------------------- verification
@router.get("/api/tickets/verify", tags=["Tickets"], summary="Verify a ticket from its QR code (no personal data)")
def verify(ref: str = Query(..., min_length=3, max_length=20), sig: str = Query(..., min_length=8, max_length=64),
           db=Depends(db_dep)):
    return serialize(ticket_service.verify(db, ref, sig))
