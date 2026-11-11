"""Aplicação FastAPI.

uvicorn api.main:app --reload    (na raiz do projeto)

Em desenvolvimento, o Vite serve a página e repassa /api para cá. Para publicar, rode
`npm run build` em frontend/: com frontend/dist presente, esta mesma API serve a página
(um único servidor). Se a página ficar em outro domínio, liste-o em CORS_ORIGENS no .env.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from banco.conexao import fecha

from . import config
from .rotas import assistente, conta, extratos, saude, transacoes


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    yield
    fecha()  # fecha o pool de conexões ao desligar


app = FastAPI(title="Projeto TCS – Extratos", version="0.3.0", lifespan=ciclo_de_vida)

if config.CORS_ORIGENS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGENS, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])

# todas as rotas sob /api: o proxy do Vite repassa esse prefixo para cá
app.include_router(saude.router, prefix="/api")
app.include_router(extratos.router, prefix="/api")
app.include_router(transacoes.router, prefix="/api")
app.include_router(assistente.router, prefix="/api")
app.include_router(conta.router, prefix="/api")

# página já compilada (npm run build): servida pela própria API
if (config.DIR_FRONTEND / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=config.DIR_FRONTEND / "assets"), name="assets")

    @app.get("/{caminho:path}", include_in_schema=False)
    def pagina(caminho: str) -> FileResponse:
        if caminho.startswith("api/"):
            raise HTTPException(404, "rota não encontrada")
        arquivo = (config.DIR_FRONTEND / caminho).resolve()
        # arquivos soltos de public/ (ícone etc.); o resto é rota do React (/login, /extrato...)
        if caminho and arquivo.is_file() and arquivo.is_relative_to(config.DIR_FRONTEND.resolve()):
            return FileResponse(arquivo)
        return FileResponse(config.DIR_FRONTEND / "index.html")
