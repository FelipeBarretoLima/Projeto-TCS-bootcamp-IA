"""Aplicação FastAPI.

uvicorn api.main:app --reload    (na raiz do projeto)
"""

from fastapi import FastAPI

from .rotas import extratos, saude

app = FastAPI(title="Projeto TCS – Extratos", version="0.1.0")

# todas as rotas sob /api: o proxy do Vite repassa esse prefixo para cá
app.include_router(saude.router, prefix="/api")
app.include_router(extratos.router, prefix="/api")
