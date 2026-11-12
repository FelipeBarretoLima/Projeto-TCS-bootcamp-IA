"""Conta do usuário: nome do perfil e exclusão da conta (a senha é trocada direto no Supabase Auth)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from database.repository import Banco

from ..auth import Usuario, esquece_token, usuario_atual
from ..dependencies import banco
from ..schemas import NovoNome, Perfil

router = APIRouter(tags=["conta"])


@router.patch("/perfil")
def muda_nome(
    novo: NovoNome, usuario: Annotated[Usuario, Depends(usuario_atual)], db: Annotated[Banco, Depends(banco)]
) -> Perfil:
    """Guarda o nome no perfil (o frontend grava o mesmo nome nos metadados do login)."""
    nome = novo.nome.strip()
    if not nome:
        raise HTTPException(400, "o nome não pode ficar vazio")
    db.garante_usuario(usuario.id, usuario.email, nome)
    db.muda_nome(usuario.id, nome)
    return Perfil(nome=nome, email=usuario.email)


@router.delete("/conta", status_code=204)
def apaga_conta(
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    db: Annotated[Banco, Depends(banco)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Apaga o login e tudo o que é do usuário (extratos, transações, conversas), sem volta. LGPD."""
    db.apaga_conta(usuario.id)
    esquece_token(authorization)
    return Response(status_code=204)
