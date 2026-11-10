"""Aplicação FastAPI.

uvicorn api.main:app --reload    (na raiz do projeto)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from banco.conexao import fecha

from .rotas import assistente, extratos, saude, transacoes


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    yield
    fecha()  # fecha o pool de conexões ao desligar


app = FastAPI(title="Projeto TCS – Extratos", version="0.2.0", lifespan=ciclo_de_vida)

# todas as rotas sob /api: o proxy do Vite repassa esse prefixo para cá
app.include_router(saude.router, prefix="/api")
app.include_router(extratos.router, prefix="/api")
app.include_router(transacoes.router, prefix="/api")
app.include_router(assistente.router, prefix="/api")
