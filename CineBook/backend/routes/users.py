"""Customer profile, watchlist, recently viewed and notifications."""
from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user
from ..schemas.auth import PasswordChangeIn, ProfileUpdateIn, UserOut
from ..schemas.common import page_response
from ..services import auth_service, movie_service
from ..utils.ids import serialize
from . import db_dep

router = APIRouter(prefix="/api/me", tags=["Profile"])


@router.get("", response_model=UserOut)
def profile(user=Depends(get_current_user)):
    return auth_service.public_user(user)


@router.put("", response_model=UserOut)
def update_profile(body: ProfileUpdateIn, user=Depends(get_current_user), db=Depends(db_dep)):
    return auth_service.update_profile(db, user, body.model_dump())


@router.post("/password")
def change_password(body: PasswordChangeIn, user=Depends(get_current_user), db=Depends(db_dep)):
    auth_service.change_password(db, user, body.current_password, body.new_password)
    return {"message": "Password updated"}


@router.get("/watchlist")
def watchlist(user=Depends(get_current_user), db=Depends(db_dep)):
    return movie_service.movies_by_ids(db, list(reversed(user.get("favourites") or [])))


@router.post("/watchlist/{movie_id}")
def add_watchlist(movie_id: str, user=Depends(get_current_user), db=Depends(db_dep)):
    return {"favourites": movie_service.set_watchlist(db, user, movie_id, True)}


@router.delete("/watchlist/{movie_id}")
def remove_watchlist(movie_id: str, user=Depends(get_current_user), db=Depends(db_dep)):
    return {"favourites": movie_service.set_watchlist(db, user, movie_id, False)}


@router.get("/recently-viewed")
def recently_viewed(user=Depends(get_current_user), db=Depends(db_dep)):
    return movie_service.movies_by_ids(db, user.get("recently_viewed") or [])


@router.get("/notifications")
def notifications(unread_only: bool = False, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  user=Depends(get_current_user), db=Depends(db_dep)):
    q = {"user_id": user["_id"]}
    if unread_only:
        q["read"] = False
    total = db.notifications.count_documents(q)
    items = db.notifications.find(q).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size)
    out = page_response([serialize(n) for n in items], total, page, page_size)
    out["unread"] = db.notifications.count_documents({"user_id": user["_id"], "read": False})
    return out


@router.post("/notifications/read-all")
def mark_all_read(user=Depends(get_current_user), db=Depends(db_dep)):
    res = db.notifications.update_many({"user_id": user["_id"], "read": False}, {"$set": {"read": True}})
    return {"updated": res.modified_count}
