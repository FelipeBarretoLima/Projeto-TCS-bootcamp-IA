"""User account: profile name and account deletion (the password is changed directly in Supabase Auth)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from database.repository import Database

from ..auth import User, current_user, forget_token, forget_user
from ..dependencies import database
from ..schemas import NewName, Profile

router = APIRouter(tags=["conta"])


@router.patch("/perfil")
def rename_user(
    new: NewName, user: Annotated[User, Depends(current_user)], db: Annotated[Database, Depends(database)]
) -> Profile:
    """Saves the name in the profile (the frontend saves the same name in the login metadata)."""
    name = new.nome.strip()
    if not name:
        raise HTTPException(400, "o nome não pode ficar vazio")
    db.ensure_user(user.id, user.email, name)
    db.rename_user(user.id, name)
    return Profile(nome=name, email=user.email)


@router.delete("/conta", status_code=204)
def delete_account(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Deletes the login and everything that belongs to the user (statements, transactions, conversations), for good. LGPD."""
    db.delete_account(user.id)
    forget_token(authorization)
    forget_user(user.id)  # and the tokens of the same account on other devices
    return Response(status_code=204)
