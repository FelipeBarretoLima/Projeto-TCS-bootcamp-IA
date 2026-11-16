"""FastAPI application.

uvicorn api.main:app --reload    (at the project root)

In development, Vite serves the page and forwards /api here. To deploy, run `npm run build` in
frontend/: with frontend/dist present, this same API serves the page (a single server). If the
page lives on another domain, list it in CORS_ORIGENS in .env.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from database.connection import close_pool

from . import config
from .routes import assistant, account, statements, health, transactions


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    close_pool()  # closes the connection pool on shutdown


app = FastAPI(title="Projeto TCS – Extratos", version="0.3.0", lifespan=lifespan)

TOO_LARGE_MESSAGE = "arquivo maior que 10 MB"


class BodySizeLimit:
    """Refuses requests whose body is larger than the limit, before FastAPI reads the upload.

    FastAPI reads the whole multipart body (and writes the file to disk) BEFORE checking the login:
    without this, anyone, even without an account, could send a file of several GB and fill the disk.
    """

    def __init__(self, app, max_size: int):
        self.app, self.max_size = app, max_size

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_size:
            response = JSONResponse({"detail": TOO_LARGE_MESSAGE}, status_code=413)
            return await response(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_size:  # body sent in chunks, without Content-Length
                    raise HTTPException(413, TOO_LARGE_MESSAGE)  # FastAPI passes HTTPException on
            return message

        await self.app(scope, limited_receive, send)


# room for the multipart headers; the file size itself is checked again in the route
app.add_middleware(BodySizeLimit, max_size=config.MAX_SIZE + 64 * 1024)

if config.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])

# every route under /api: the Vite proxy forwards this prefix here
app.include_router(health.router, prefix="/api")
app.include_router(statements.router, prefix="/api")
app.include_router(transactions.router, prefix="/api")
app.include_router(assistant.router, prefix="/api")
app.include_router(account.router, prefix="/api")

# already compiled page (npm run build): served by the API itself
if (config.FRONTEND_DIR / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "rota não encontrada")
        file = (config.FRONTEND_DIR / path).resolve()
        # loose files from public/ (icon etc.); the rest are React routes (/login, /extrato...)
        if path and file.is_file() and file.is_relative_to(config.FRONTEND_DIR.resolve()):
            return FileResponse(file)
        return FileResponse(config.FRONTEND_DIR / "index.html")
