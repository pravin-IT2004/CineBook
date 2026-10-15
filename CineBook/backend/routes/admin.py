"""Administrator API: catalogue management, operations, users, settings and analytics."""
from datetime import date

from fastapi import APIRouter, Depends, Query, status

from ..auth import require_admin
from ..models.constants import BookingStatus
from ..schemas.auth import AdminUserUpdateIn
from ..schemas.booking import CancelIn, OfferIn, OfferUpdateIn, PolicyIn
from ..schemas.catalog import (CinemaIn, CinemaUpdateIn, MovieIn, MovieUpdateIn, ScreenIn, ScreenUpdateIn,
                               ShowtimeBulkIn, ShowtimeIn, ShowtimeUpdateIn)
from ..schemas.common import page_response
from ..services import (analytics_service, auth_service, booking_service, cinema_service, movie_service,
                        offer_service, showtime_service, support_service, ticket_service)
from ..utils.errors import bad_request
from ..utils.ids import serialize
from . import db_dep, page_params

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------- analytics
@router.get("/analytics")
def analytics(date_from: date | None = None, date_to: date | None = None, movie_id: str | None = None,
              cinema_id: str | None = None, status: str | None = None, db=Depends(db_dep)):
    if status and status not in BookingStatus.ALL:
        raise bad_request("Unknown booking status")
    return serialize(analytics_service.dashboard(db, date_from=date_from, date_to=date_to, movie_id=movie_id,
                                                 cinema_id=cinema_id, status=status))


# ---------------------------------------------------------------- movies
@router.get("/movies")
def movies(q: str | None = None, status: str | None = None, paging=Depends(page_params), db=Depends(db_dep)):
    page, size = paging
    items, total = movie_service.list_movies(db, q=q, status=status, page=page, page_size=size,
                                             include_unpublished=True)
    return page_response(items, total, page, size)


@router.get("/movies/{movie_id}")
def movie(movie_id: str, db=Depends(db_dep)):
    return movie_service.get_movie(db, movie_id, admin=True)


@router.post("/movies", status_code=status.HTTP_201_CREATED)
def create_movie(body: MovieIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return movie_service.create_movie(db, admin, body.model_dump())


@router.put("/movies/{movie_id}")
def update_movie(movie_id: str, body: MovieUpdateIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return movie_service.update_movie(db, admin, movie_id, body.model_dump(exclude_unset=True))


@router.post("/movies/{movie_id}/publish")
def publish_movie(movie_id: str, publish: bool = True, admin=Depends(require_admin), db=Depends(db_dep)):
    return movie_service.update_movie(db, admin, movie_id, {"is_published": publish})


@router.delete("/movies/{movie_id}")
def delete_movie(movie_id: str, admin=Depends(require_admin), db=Depends(db_dep)):
    return movie_service.delete_movie(db, admin, movie_id)


# ---------------------------------------------------------------- cinemas & screens
@router.get("/cinemas")
def cinemas(db=Depends(db_dep)):
    return cinema_service.list_cinemas(db, include_inactive=True)


@router.post("/cinemas", status_code=status.HTTP_201_CREATED)
def create_cinema(body: CinemaIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return cinema_service.create_cinema(db, admin, body.model_dump())


@router.put("/cinemas/{cinema_id}")
def update_cinema(cinema_id: str, body: CinemaUpdateIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return cinema_service.update_cinema(db, admin, cinema_id, body.model_dump(exclude_unset=True))


@router.delete("/cinemas/{cinema_id}")
def delete_cinema(cinema_id: str, admin=Depends(require_admin), db=Depends(db_dep)):
    cinema_service.delete_cinema(db, admin, cinema_id)
    return {"message": "Cinema deleted"}


@router.post("/screens", status_code=status.HTTP_201_CREATED)
def create_screen(body: ScreenIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return cinema_service.create_screen(db, admin, body.model_dump())


@router.put("/screens/{screen_id}")
def update_screen(screen_id: str, body: ScreenUpdateIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return cinema_service.update_screen(db, admin, screen_id, body.model_dump(exclude_unset=True))


@router.delete("/screens/{screen_id}")
def delete_screen(screen_id: str, admin=Depends(require_admin), db=Depends(db_dep)):
    cinema_service.delete_screen(db, admin, screen_id)
    return {"message": "Screen deleted"}


# ---------------------------------------------------------------- showtimes
@router.get("/showtimes")
def showtimes(movie_id: str | None = None, cinema_id: str | None = None, date_from: date | None = None,
              date_to: date | None = None, upcoming_only: bool = True, paging=Depends(page_params),
              db=Depends(db_dep)):
    page, size = paging
    items, total = showtime_service.admin_list(db, movie_id=movie_id, cinema_id=cinema_id, date_from=date_from,
                                               date_to=date_to, upcoming_only=upcoming_only, page=page,
                                               page_size=size)
    return page_response(items, total, page, size)


@router.post("/showtimes", status_code=status.HTTP_201_CREATED)
def create_showtime(body: ShowtimeIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return showtime_service.create_showtime(db, admin, body.model_dump())


@router.post("/showtimes/bulk", status_code=status.HTTP_201_CREATED, summary="Schedule several dates × times at once")
def bulk_showtimes(body: ShowtimeBulkIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return showtime_service.bulk_create(db, admin, body.model_dump())


@router.put("/showtimes/{showtime_id}")
def update_showtime(showtime_id: str, body: ShowtimeUpdateIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return showtime_service.update_showtime(db, admin, showtime_id, body.model_dump(exclude_unset=True))


@router.delete("/showtimes/{showtime_id}")
def delete_showtime(showtime_id: str, admin=Depends(require_admin), db=Depends(db_dep)):
    showtime_service.delete_showtime(db, admin, showtime_id)
    return {"message": "Showtime deleted"}


# ---------------------------------------------------------------- bookings
@router.get("/bookings")
def bookings(reference: str | None = Query(None, max_length=20), status: str | None = None,
             movie_id: str | None = None, cinema_id: str | None = None, date_from: date | None = None,
             date_to: date | None = None, paging=Depends(page_params), db=Depends(db_dep)):
    page, size = paging
    if status and status not in BookingStatus.ALL:
        raise bad_request("Unknown booking status")
    items, total = booking_service.admin_search(db, reference=reference, status=status, movie_id=movie_id,
                                                cinema_id=cinema_id, date_from=date_from, date_to=date_to,
                                                page=page, page_size=size)
    return page_response(items, total, page, size)


@router.post("/bookings/{booking_id}/cancel")
def admin_cancel(booking_id: str, body: CancelIn | None = None, admin=Depends(require_admin), db=Depends(db_dep)):
    return booking_service.present(db, booking_service.cancel_booking(db, admin, booking_id,
                                                                      body.reason if body else "Cancelled by cinema"))


@router.get("/tickets/{reference}", summary="Look up a ticket by reference (staff)")
def lookup_ticket(reference: str, db=Depends(db_dep)):
    return serialize(ticket_service.verify(db, reference, None, trusted=True))


@router.post("/tickets/{reference}/check-in", summary="Mark a valid ticket as used")
def check_in(reference: str, admin=Depends(require_admin), db=Depends(db_dep)):
    return booking_service.present(db, booking_service.check_in(db, admin, reference))


# ---------------------------------------------------------------- offers
@router.get("/offers")
def offers(db=Depends(db_dep)):
    return offer_service.admin_list(db)


@router.post("/offers", status_code=status.HTTP_201_CREATED)
def create_offer(body: OfferIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return offer_service.create_offer(db, admin, body.model_dump())


@router.put("/offers/{offer_id}")
def update_offer(offer_id: str, body: OfferUpdateIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return offer_service.update_offer(db, admin, offer_id, body.model_dump(exclude_unset=True))


@router.post("/offers/{offer_id}/deactivate")
def deactivate_offer(offer_id: str, admin=Depends(require_admin), db=Depends(db_dep)):
    return offer_service.deactivate_offer(db, admin, offer_id)


# ---------------------------------------------------------------- users
@router.get("/users")
def users(q: str | None = Query(None, max_length=80), role: str | None = None, paging=Depends(page_params),
          db=Depends(db_dep)):
    import re

    page, size = paging
    query: dict = {}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"name": rx}, {"email": rx}]
    if role:
        query["role"] = role
    total = db.users.count_documents(query)
    docs = list(db.users.find(query).sort("created_at", -1).skip((page - 1) * size).limit(size))
    counts: dict = {}
    for b in db.bookings.find({"user_id": {"$in": [u["_id"] for u in docs]}, "status": BookingStatus.CONFIRMED},
                              {"user_id": 1, "total": 1}):
        c = counts.setdefault(b["user_id"], {"bookings": 0, "spent": 0.0})
        c["bookings"] += 1
        c["spent"] += b["total"]
    items = []
    for u in docs:
        item = auth_service.public_user(u)
        c = counts.get(u["_id"], {})
        item["confirmed_bookings"] = c.get("bookings", 0)
        item["booking_value"] = round(c.get("spent", 0), 2)
        items.append(item)
    return page_response(items, total, page, size)


@router.put("/users/{user_id}")
def update_user(user_id: str, body: AdminUserUpdateIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return auth_service.admin_update_user(db, admin, user_id, body.model_dump(exclude_unset=True))


# ---------------------------------------------------------------- settings & audit
@router.get("/settings")
def get_settings_(db=Depends(db_dep)):
    return support_service.get_policy(db)


@router.put("/settings")
def put_settings(body: PolicyIn, admin=Depends(require_admin), db=Depends(db_dep)):
    return support_service.update_policy(db, body.model_dump(), admin)


@router.get("/audit-logs")
def audit_logs(action: str | None = None, paging=Depends(page_params), db=Depends(db_dep)):
    page, size = paging
    import re

    q = {"action": {"$regex": "^" + re.escape(action)}} if action else {}
    total = db.audit_logs.count_documents(q)
    items = db.audit_logs.find(q).sort("created_at", -1).skip((page - 1) * size).limit(size)
    return page_response([serialize(i) for i in items], total, page, size)


@router.post("/maintenance/cleanup", summary="Release expired holds and stuck bookings now")
def cleanup(db=Depends(db_dep)):
    return booking_service.cleanup(db)
