"""Dashboard e chat do Assistente TAS."""

import logging
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from agent import queries
from agent.assistant import responde
from agent.transcription import SemFala, transcreve
from database.repository import Banco, ConversaApagada

from ..auth import Usuario, usuario_atual
from ..dependencies import AbreBanco, abre_banco, banco, modelo_do_assistente
from ..schemas import Conversa, Mensagem, NovoTitulo, Painel, Pergunta, RespostaChat, Transcricao
from ..rate_limit import limita_chat, limita_transcricao

router = APIRouter(tags=["assistente"])
log = logging.getLogger(__name__)

TAMANHO_TITULO = 60

# mensagem de voz: até 15 s gravados no navegador (~120 KB em Opus, ~250 KB em AAC no iPhone);
# 1 MB deixa folga para aparelhos que gravam com mais qualidade
TAMANHO_MAXIMO_AUDIO = 1024 * 1024
# o que o MediaRecorder grava em cada navegador (Chrome/Firefox: webm ou ogg; Safari: mp4) e o Gemini lê
AUDIOS_ACEITOS = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/aac", "audio/wav", "audio/x-m4a"}


@router.get("/painel")
def painel(
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    db: Annotated[Banco, Depends(banco)],
    mes: Annotated[str | None, Query(description="Mês dos cartões, AAAA-MM (padrão: o mais recente)")] = None,
) -> Painel:
    """Cartões de um mês e receitas x despesas dos 6 meses até ele."""
    if mes is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        raise HTTPException(400, "mês inválido: use AAAA-MM (ex.: 2024-03)")
    return Painel(**queries.painel(queries.tabela(db.transacoes(usuario.id)), mes))


@router.get("/conversas")
def lista_conversas(
    usuario: Annotated[Usuario, Depends(usuario_atual)], db: Annotated[Banco, Depends(banco)]
) -> list[Conversa]:
    return [Conversa(**c) for c in db.lista_conversas(usuario.id)]


@router.get("/conversas/{conversa_id}/mensagens")
def mensagens(
    conversa_id: UUID, usuario: Annotated[Usuario, Depends(usuario_atual)], db: Annotated[Banco, Depends(banco)]
) -> list[Mensagem]:
    if not db.conversa_e_do_usuario(usuario.id, conversa_id):
        raise HTTPException(404, "conversa não encontrada")
    return [Mensagem(**m) for m in db.mensagens(conversa_id)]


@router.patch("/conversas/{conversa_id}", status_code=204)
def renomeia_conversa(
    conversa_id: UUID,
    novo: NovoTitulo,
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    db: Annotated[Banco, Depends(banco)],
) -> Response:
    titulo = novo.titulo.strip()
    if not titulo:
        raise HTTPException(400, "o nome da conversa não pode ficar vazio")
    if not db.renomeia_conversa(usuario.id, conversa_id, titulo):
        raise HTTPException(404, "conversa não encontrada")
    return Response(status_code=204)


@router.delete("/conversas/{conversa_id}", status_code=204)
def apaga_conversa(
    conversa_id: UUID, usuario: Annotated[Usuario, Depends(usuario_atual)], db: Annotated[Banco, Depends(banco)]
) -> Response:
    if not db.apaga_conversa(usuario.id, conversa_id):
        raise HTTPException(404, "conversa não encontrada")
    return Response(status_code=204)


@router.post("/chat", dependencies=[Depends(limita_chat)])
def chat(
    pergunta: Pergunta,
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    abre: Annotated[AbreBanco, Depends(abre_banco)],
    modelo=Depends(modelo_do_assistente),
) -> RespostaChat:
    """Três fases, para não prender uma conexão do pool enquanto o LLM responde (de 2 a 30 s ou
    mais): com a conexão presa, 5 perguntas lentas esgotavam o pool e todas as outras rotas
    falhavam."""
    texto = pergunta.mensagem.strip()
    if not texto:
        raise HTTPException(400, "mensagem vazia")

    # 1) lê o que o assistente precisa e devolve a conexão ao pool
    with abre() as db:
        historico = []
        if pergunta.conversa_id is not None:
            if not db.conversa_e_do_usuario(usuario.id, pergunta.conversa_id):
                raise HTTPException(404, "conversa não encontrada")
            historico = db.mensagens(pergunta.conversa_id)
        df = queries.tabela(db.transacoes(usuario.id))

    # 2) o LLM, sem nenhuma conexão aberta
    try:
        resposta = responde(modelo, df, texto, historico)
    except Exception:
        # nada foi gravado ainda: o usuário pode tentar de novo
        log.exception("falha no assistente")
        raise HTTPException(502, "o assistente não conseguiu responder agora; tente de novo em instantes") from None

    # 3) grava; a conversa nova só nasce se houve resposta
    with abre() as db:
        db.garante_usuario(usuario.id, usuario.email, usuario.nome)
        if pergunta.conversa_id is None:
            titulo = texto if len(texto) <= TAMANHO_TITULO else texto[: TAMANHO_TITULO - 1].rstrip() + "…"
            conversa_id = db.cria_conversa(usuario.id, titulo)
        else:
            conversa_id = pergunta.conversa_id
        try:
            m_pergunta = db.grava_mensagem(conversa_id, "usuario", texto)
            m_resposta = db.grava_mensagem(conversa_id, "agente", resposta.texto, resposta.grafico)
        except ConversaApagada:
            raise HTTPException(404, "a conversa foi apagada enquanto o assistente respondia") from None
    return RespostaChat(conversa_id=conversa_id, pergunta=Mensagem(**m_pergunta), resposta=Mensagem(**m_resposta))


# `def` (não `async def`): a chamada ao Gemini é bloqueante; o FastAPI roda num thread à parte
@router.post("/chat/transcricao", dependencies=[Depends(limita_transcricao)])
def transcreve_audio(
    audio: Annotated[UploadFile, File(description="Mensagem de voz gravada no navegador (até 15 s)")],
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    modelo=Depends(modelo_do_assistente),
) -> Transcricao:
    """Só transcreve: nada é gravado. O texto volta para o campo do chat, e o usuário confere e
    envia pela rota /chat. O áudio não é salvo em lugar nenhum."""
    tipo = (audio.content_type or "").split(";")[0].strip().lower()  # "audio/webm;codecs=opus" -> "audio/webm"
    if tipo not in AUDIOS_ACEITOS:
        raise HTTPException(415, "formato de áudio não aceito pelo assistente")

    conteudo = audio.file.read(TAMANHO_MAXIMO_AUDIO + 1)
    if len(conteudo) > TAMANHO_MAXIMO_AUDIO:
        raise HTTPException(413, "mensagem de voz longa demais: grave até 15 segundos")
    if not conteudo:
        raise HTTPException(400, "a gravação veio vazia; tente de novo")

    try:
        texto = transcreve(modelo, conteudo, tipo)
    except SemFala:
        raise HTTPException(422, "não deu para entender nenhuma fala no áudio; tente de novo") from None
    except Exception:
        # sem o conteúdo no log: a fala pode ter dados pessoais
        log.exception("falha ao transcrever a mensagem de voz")
        raise HTTPException(502, "não foi possível transcrever o áudio agora; tente de novo em instantes") from None
    return Transcricao(texto=texto[:1000])  # o mesmo limite de uma pergunta digitada
