"""Public catalogue: movies, showtimes, seat maps, cinemas and reviews."""
from datetime import date

from fastapi import APIRouter, Depends, Query

from ..auth import get_optional_user, require_customer
from ..schemas.catalog import ReviewIn
from ..schemas.common import page_response
from ..services import cinema_service, movie_service, seat_service, showtime_service
from . import db_dep, page_params

router = APIRouter(tags=["Movies & Showtimes"])


@router.get("/api/movies", summary="List published movies with search, filters and pagination")
def list_movies(q: str | None = Query(None, max_length=80), genre: str | None = None, language: str | None = None,
                status: str | None = Query(None, description="now_showing | coming_soon"),
                availability: str | None = Query(None, pattern="^(with_shows|no_shows)$"),
                paging=Depends(page_params), db=Depends(db_dep)):
    page, size = paging
    items, total = movie_service.list_movies(db, q=q, genre=genre, language=language, status=status,
                                             availability=availability, page=page, page_size=size)
    return page_response(items, total, page, size)


@router.get("/api/movies/filters", summary="Available genres and languages")
def filters(db=Depends(db_dep)):
    return movie_service.filter_options(db)


@router.get("/api/movies/{movie_id}")
def movie_detail(movie_id: str, viewer=Depends(get_optional_user), db=Depends(db_dep)):
    return movie_service.get_movie(db, movie_id, viewer=viewer)


@router.get("/api/movies/{movie_id}/showtimes", summary="Upcoming bookable showtimes grouped by cinema")
def movie_showtimes(movie_id: str, day: date | None = Query(None, alias="date"), cinema_id: str | None = None,
                    db=Depends(db_dep)):
    return showtime_service.list_for_movie(db, movie_id, day=day, cinema_id=cinema_id)


@router.get("/api/movies/{movie_id}/reviews")
def reviews(movie_id: str, paging=Depends(page_params), db=Depends(db_dep)):
    page, size = paging
    items, total = movie_service.list_reviews(db, movie_id, page, size)
    return page_response(items, total, page, size)


@router.post("/api/movies/{movie_id}/reviews", summary="Rate a movie (only after attending a confirmed show)")
def add_review(movie_id: str, body: ReviewIn, user=Depends(require_customer), db=Depends(db_dep)):
    return movie_service.upsert_review(db, user, movie_id, body.rating, body.comment)


@router.get("/api/showtimes/{showtime_id}")
def showtime(showtime_id: str, db=Depends(db_dep)):
    return showtime_service.get_showtime_details(db, showtime_id)


@router.get("/api/showtimes/{showtime_id}/seats", summary="Live seat availability (server is the source of truth)")
def seats(showtime_id: str, viewer=Depends(get_optional_user), db=Depends(db_dep)):
    return seat_service.seat_map(db, showtime_id, viewer)


@router.get("/api/cinemas")
def cinemas(db=Depends(db_dep)):
    return cinema_service.list_cinemas(db)


@router.get("/api/cinemas/{cinema_id}")
def cinema(cinema_id: str, db=Depends(db_dep)):
    c = cinema_service.get_cinema(db, cinema_id)
    if not c.get("is_active", True):
        from ..utils.errors import not_found

        raise not_found("Cinema")
    return c
