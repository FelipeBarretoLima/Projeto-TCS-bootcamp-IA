"""Dashboard and chat of the TAS Assistant."""

import logging
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, Response, UploadFile

from agent import queries
from agent.assistant import answer
from agent.transcription import NoSpeech, transcribe
from database.repository import Database, ConversationDeleted

from ..auth import User, current_user
from ..dependencies import OpenDatabase, assistant_model, database, open_database
from ..schemas import ChatAnswer, Conversation, Dashboard, Message, NewTitle, Question, Transcription
from ..rate_limit import limit_chat, limit_transcription

router = APIRouter(tags=["assistente"])
log = logging.getLogger(__name__)

TITLE_LENGTH = 60

# voice message: up to 15 s recorded in the browser (~120 KB in Opus, ~250 KB in AAC on the iPhone);
# 1 MB leaves room for devices that record with higher quality
MAX_AUDIO_SIZE = 1024 * 1024
# what MediaRecorder records in each browser (Chrome/Firefox: webm or ogg; Safari: mp4) and Gemini reads
ACCEPTED_AUDIO = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/aac", "audio/wav", "audio/x-m4a"}


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


# `def` (not `async def`): the Gemini call is blocking; FastAPI runs it in a separate thread
@router.post("/chat/transcricao", dependencies=[Depends(limit_transcription)])
def transcribe_audio(
    audio: Annotated[UploadFile, File(description="Mensagem de voz gravada no navegador (até 15 s)")],
    user: Annotated[User, Depends(current_user)],
    model=Depends(assistant_model),
) -> Transcription:
    """Only transcribes: nothing is saved. The text goes back to the chat field, and the user checks
    it and sends it through the /chat route. The audio is not stored anywhere."""
    kind = (audio.content_type or "").split(";")[0].strip().lower()  # "audio/webm;codecs=opus" -> "audio/webm"
    if kind not in ACCEPTED_AUDIO:
        raise HTTPException(415, "formato de áudio não aceito pelo assistente")

    content = audio.file.read(MAX_AUDIO_SIZE + 1)
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(413, "mensagem de voz longa demais: grave até 15 segundos")
    if not content:
        raise HTTPException(400, "a gravação veio vazia; tente de novo")

    try:
        text = transcribe(model, content, kind)
    except NoSpeech:
        raise HTTPException(422, "não deu para entender nenhuma fala no áudio; tente de novo") from None
    except Exception:
        # without the content in the log: the speech may contain personal data
        log.exception("falha ao transcrever a mensagem de voz")
        raise HTTPException(502, "não foi possível transcrever o áudio agora; tente de novo em instantes") from None
    return Transcription(texto=text[:1000])  # the same limit as a typed question
