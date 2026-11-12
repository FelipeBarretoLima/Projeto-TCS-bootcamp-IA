"""Aplicação FastAPI.

uvicorn api.main:app --reload    (na raiz do projeto)

Em desenvolvimento, o Vite serve a página e repassa /api para cá. Para publicar, rode
`npm run build` em frontend/: com frontend/dist presente, esta mesma API serve a página
(um único servidor). Se a página ficar em outro domínio, liste-o em CORS_ORIGENS no .env.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from database.connection import fecha

from . import config
from .routes import assistant, account, statements, health, transactions


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    yield
    fecha()  # fecha o pool de conexões ao desligar


app = FastAPI(title="Projeto TCS – Extratos", version="0.3.0", lifespan=ciclo_de_vida)

MENSAGEM_GRANDE_DEMAIS = "arquivo maior que 10 MB"


class LimiteDeCorpo:
    """Recusa requisições com corpo maior que o limite, antes de o FastAPI ler o upload.

    O FastAPI lê o multipart inteiro (e grava o arquivo em disco) ANTES de conferir o login: sem
    isto, qualquer pessoa, mesmo sem conta, podia enviar um arquivo de vários GB e encher o disco.
    """

    def __init__(self, app, maximo: int):
        self.app, self.maximo = app, maximo

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declarado = dict(scope["headers"]).get(b"content-length", b"")
        if declarado.isdigit() and int(declarado) > self.maximo:
            resposta = JSONResponse({"detail": MENSAGEM_GRANDE_DEMAIS}, status_code=413)
            return await resposta(scope, receive, send)
        lidos = 0

        async def receive_limitado():
            nonlocal lidos
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                lidos += len(mensagem.get("body", b""))
                if lidos > self.maximo:  # corpo enviado em pedaços, sem Content-Length
                    raise HTTPException(413, MENSAGEM_GRANDE_DEMAIS)  # o FastAPI repassa HTTPException
            return mensagem

        await self.app(scope, receive_limitado, send)


# folga para os cabeçalhos do multipart; o tamanho do arquivo em si é conferido de novo na rota
app.add_middleware(LimiteDeCorpo, maximo=config.TAMANHO_MAXIMO + 64 * 1024)

if config.CORS_ORIGENS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGENS, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])

# todas as rotas sob /api: o proxy do Vite repassa esse prefixo para cá
app.include_router(health.router, prefix="/api")
app.include_router(statements.router, prefix="/api")
app.include_router(transactions.router, prefix="/api")
app.include_router(assistant.router, prefix="/api")
app.include_router(account.router, prefix="/api")

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
