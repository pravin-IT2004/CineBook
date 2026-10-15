from fastapi import APIRouter, Depends, status

from ..auth import get_current_user
from ..schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from ..services import auth_service
from . import db_dep

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED,
             summary="Create a customer account and log in")
def register(body: RegisterIn, db=Depends(db_dep)):
    return auth_service.register(db, body.model_dump())


@router.post("/login", response_model=TokenOut, summary="Log in with e-mail and password (customers and admins)")
def login(body: LoginIn, db=Depends(db_dep)):
    return auth_service.login(db, body.email, body.password)


@router.get("/me", response_model=UserOut, summary="Current user")
def me(user=Depends(get_current_user)):
    return auth_service.public_user(user)


@router.post("/logout", summary="Log out (stateless JWT - the client discards its token)")
def logout(user=Depends(get_current_user)):
    return {"message": "Logged out. Discard the access token on the client."}
