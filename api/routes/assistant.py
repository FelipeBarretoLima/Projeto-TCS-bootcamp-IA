"""Dashboard and chat of the TAS Assistant."""

import logging
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from agent import queries
from agent.assistant import answer
from database.repository import Database, ConversationDeleted

from ..auth import User, current_user
from ..dependencies import OpenDatabase, assistant_model, database, open_database
from ..schemas import ChatAnswer, Conversation, Dashboard, Message, NewTitle, Question
from ..rate_limit import limit_chat

router = APIRouter(tags=["assistente"])
log = logging.getLogger(__name__)

TITLE_LENGTH = 60


@router.get("/painel")
def dashboard(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
    month: Annotated[str | None, Query(alias="mes", description="Mês dos cartões, AAAA-MM (padrão: o mais recente)")] = None,
) -> Dashboard:
    """Cards of one month and income vs expenses of the 6 months up to it."""
    if month is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(400, "mês inválido: use AAAA-MM (ex.: 2024-03)")
    return Dashboard(**queries.dashboard(queries.to_dataframe(db.transactions(user.id)), month))


@router.get("/conversas")
def list_conversations(
    user: Annotated[User, Depends(current_user)], db: Annotated[Database, Depends(database)]
) -> list[Conversation]:
    return [Conversation(**c) for c in db.list_conversations(user.id)]


@router.get("/conversas/{conversa_id}/mensagens")
def messages(
    conversation_id: Annotated[UUID, Path(alias="conversa_id")],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
) -> list[Message]:
    if not db.conversation_belongs_to_user(user.id, conversation_id):
        raise HTTPException(404, "conversa não encontrada")
    return [Message(**m) for m in db.messages(conversation_id)]


@router.patch("/conversas/{conversa_id}", status_code=204)
def rename_conversation(
    conversation_id: Annotated[UUID, Path(alias="conversa_id")],
    new: NewTitle,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
) -> Response:
    title = new.titulo.strip()
    if not title:
        raise HTTPException(400, "o nome da conversa não pode ficar vazio")
    if not db.rename_conversation(user.id, conversation_id, title):
        raise HTTPException(404, "conversa não encontrada")
    return Response(status_code=204)


@router.delete("/conversas/{conversa_id}", status_code=204)
def delete_conversation(
    conversation_id: Annotated[UUID, Path(alias="conversa_id")],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
) -> Response:
    if not db.delete_conversation(user.id, conversation_id):
        raise HTTPException(404, "conversa não encontrada")
    return Response(status_code=204)


@router.post("/chat", dependencies=[Depends(limit_chat)])
def chat(
    question: Question,
    user: Annotated[User, Depends(current_user)],
    open_db: Annotated[OpenDatabase, Depends(open_database)],
    model=Depends(assistant_model),
) -> ChatAnswer:
    """Three phases, so a pool connection is not held while the LLM answers (from 2 to 30 s or
    more): with the connection held, 5 slow questions exhausted the pool and every other route
    failed."""
    text = question.mensagem.strip()
    if not text:
        raise HTTPException(400, "mensagem vazia")

    # 1) reads what the assistant needs and gives the connection back to the pool
    with open_db() as db:
        history = []
        if question.conversa_id is not None:
            if not db.conversation_belongs_to_user(user.id, question.conversa_id):
                raise HTTPException(404, "conversa não encontrada")
            history = db.messages(question.conversa_id)
        df = queries.to_dataframe(db.transactions(user.id))

    # 2) the LLM, with no connection open
    try:
        reply = answer(model, df, text, history)
    except Exception:
        # nothing was saved yet: the user can try again
        log.exception("falha no assistente")
        raise HTTPException(502, "o assistente não conseguiu responder agora; tente de novo em instantes") from None

    # 3) saves; a new conversation is only created if there was an answer
    with open_db() as db:
        db.ensure_user(user.id, user.email, user.name)
        if question.conversa_id is None:
            title = text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"
            conversation_id = db.create_conversation(user.id, title)
        else:
            conversation_id = question.conversa_id
        try:
            question_msg = db.save_message(conversation_id, "usuario", text)
            answer_msg = db.save_message(conversation_id, "agente", reply.text, reply.chart)
        except ConversationDeleted:
            raise HTTPException(404, "a conversa foi apagada enquanto o assistente respondia") from None
    return ChatAnswer(conversa_id=conversation_id, pergunta=Message(**question_msg), resposta=Message(**answer_msg))
