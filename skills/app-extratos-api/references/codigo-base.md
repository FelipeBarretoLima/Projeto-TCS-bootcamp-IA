# Código-base da API

Do projeto de referência (`api/`). As rotas seguem o mesmo padrão: dependências `usuario_atual`
e `banco` em todas as que exigem login, validação na entrada e `HTTPException` com mensagem em
português.

## Sumário

1. `main.py`
2. `config.py`
3. `auth.py`
4. `dependencies.py`
5. `rate_limit.py`
6. `cipher.py`
7. `services/extraction.py`
8. `services/categorization.py`
9. `services/retraining.py`
10. Rota de importação
11. Testes: `conftest.py` e um exemplo

## 1. `main.py`

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database.connection import fecha

from . import config
from .routes import assistant, account, statements, health, transactions


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    yield
    fecha()  # fecha o pool de conexões ao desligar


app = FastAPI(title="Extratos", version="0.3.0", lifespan=ciclo_de_vida)

if config.CORS_ORIGENS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGENS, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])

for modulo in (health, statements, transactions, assistant, account):
    app.include_router(modulo.router, prefix="/api")  # o proxy do Vite repassa /api para cá

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
```

## 2. `config.py`

```python
import os
import re
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ_PROJETO / ".env")

DIR_PRIVADO = RAIZ_PROJETO / "data" / "privado"            # mapas do usuário: só leitura
CAMINHO_MODELO = RAIZ_PROJETO / "ml" / "modelos" / "svm_tfidf.pkl"
CAMINHO_TREINO_BASE = RAIZ_PROJETO / "ml" / "dados" / "transacoes_rotuladas.csv"
DIR_FRONTEND = RAIZ_PROJETO / "frontend" / "dist"

EXTENSOES_ACEITAS = frozenset({".pdf", ".csv"})
TAMANHO_MAXIMO = 10 * 1024 * 1024  # 10 MB
USUARIO_PADRAO = "u01"  # pseudônimo usado pelo parser; o dono real vem do login

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def _url_do_projeto() -> str:
    """https://<ref>.supabase.co: do .env ou deduzido do usuário do DATABASE_URL (postgres.<ref>)."""
    explicita = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if explicita:
        return explicita
    m = re.search(r"://postgres\.([a-z0-9]+):", DATABASE_URL)
    return f"https://{m.group(1)}.supabase.co" if m else ""


SUPABASE_URL = _url_do_projeto()
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
CHAVE_ORIGINAIS = os.environ.get("CHAVE_ORIGINAIS", "").strip()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"
GEMINI_MODELOS_RESERVA = [m.strip() for m in os.environ.get(
    "GEMINI_MODELOS_RESERVA", "gemini-3.6-flash,gemini-3.1-flash-lite").split(",") if m.strip()]
GEMINI_TIMEOUT = float(os.environ.get("GEMINI_TIMEOUT", "").strip() or 10)

CORS_ORIGENS = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGENS", "").split(",") if o.strip()]
```

Os nomes dos modelos padrão foram medidos na referência (mesmas perguntas, 3 vezes): escolha o
principal pela latência e estabilidade, e deixe os reservas configuráveis.

## 3. `auth.py`

```python
import time
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Header, HTTPException

from . import config

_CACHE_SEGUNDOS = 60
_cache: dict[str, tuple[float, "Usuario"]] = {}


@dataclass(frozen=True)
class Usuario:
    id: UUID
    email: str
    nome: str


def _consulta_supabase(token: str) -> Usuario | None:
    if not (config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY):
        raise HTTPException(503, "login não configurado: preencha SUPABASE_PUBLISHABLE_KEY no .env")
    try:
        r = httpx.get(f"{config.SUPABASE_URL}/auth/v1/user", timeout=10,
                      headers={"apikey": config.SUPABASE_PUBLISHABLE_KEY, "Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        raise HTTPException(503, "não foi possível falar com o serviço de login") from None
    if r.status_code != 200:
        return None
    d = r.json()
    return Usuario(UUID(d["id"]), d.get("email") or "", (d.get("user_metadata") or {}).get("nome", ""))


def esquece_token(authorization: str | None) -> None:
    """Logout: o token deixa de valer aqui na hora, sem esperar o cache expirar."""
    if authorization and authorization.lower().startswith("bearer "):
        _cache.pop(authorization[7:].strip(), None)


def usuario_atual(authorization: Annotated[str | None, Header()] = None) -> Usuario:
    """Dependência das rotas que precisam de login."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "faça login para continuar")
    token = authorization[7:].strip()
    agora = time.monotonic()
    em_cache = _cache.get(token)
    if em_cache and em_cache[0] > agora:
        return em_cache[1]
    usuario = _consulta_supabase(token)
    if usuario is None:
        raise HTTPException(401, "sessão expirada: faça login de novo")
    if len(_cache) > 1000:
        _cache.clear()
    _cache[token] = (agora + _CACHE_SEGUNDOS, usuario)
    return usuario
```

## 4. `dependencies.py`

```python
from database.connection import BancoNaoConfigurado, conexao
from database.repository import Banco


def banco() -> Iterator[Banco]:
    """Uma transação por requisição: se a rota der erro, nada fica gravado."""
    try:
        with conexao(config.DATABASE_URL) as con:
            yield Banco(con)
    except BancoNaoConfigurado:
        raise HTTPException(503, "banco não configurado: preencha DATABASE_URL no .env") from None


_modelo = None


def modelo_do_assistente():
    """Os modelos do LLM: principal + reservas (criados uma vez)."""
    global _modelo
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "assistente não configurado: preencha GEMINI_API_KEY no .env")
    if _modelo is None:
        from agent.assistant import modelos_gemini  # importa o LangChain só quando precisa
        _modelo = modelos_gemini(config.GEMINI_API_KEY, config.GEMINI_MODEL, config.GEMINI_MODELOS_RESERVA,
                                 config.GEMINI_TIMEOUT)
    return _modelo
```

## 5. `rate_limit.py`

```python
import time
from collections import defaultdict, deque
from threading import Lock


class Limite:
    def __init__(self, maximo: int, janela_segundos: float, acao: str):
        self.maximo, self.janela, self.acao = maximo, janela_segundos, acao
        self._usos: defaultdict[str, deque[float]] = defaultdict(deque)
        self._trava = Lock()

    def confere(self, chave: str) -> None:
        """Conta um uso; 429 se a chave já usou o máximo dentro da janela."""
        agora = time.monotonic()
        with self._trava:
            usos = self._usos[chave]
            while usos and usos[0] <= agora - self.janela:
                usos.popleft()
            if len(usos) >= self.maximo:
                espera = int(usos[0] + self.janela - agora) + 1
                raise HTTPException(429, f"muitas {self.acao} seguidas: espere {espera} s e tente de novo")
            usos.append(agora)

    def zera(self) -> None:
        with self._trava:
            self._usos.clear()


LIMITE_CHAT = Limite(10, 60, "perguntas")            # 10 perguntas por minuto
LIMITE_IMPORTACAO = Limite(20, 600, "importações")   # 20 extratos a cada 10 minutos


def limita_chat(usuario: Annotated[Usuario, Depends(usuario_atual)]) -> None:
    LIMITE_CHAT.confere(str(usuario.id))


def limita_importacao(usuario: Annotated[Usuario, Depends(usuario_atual)]) -> None:
    LIMITE_IMPORTACAO.confere(str(usuario.id))
```

Use como `@router.post("/chat", dependencies=[Depends(limita_chat)])`. A contagem é por processo
e reinicia junto com a API: serve contra cliques repetidos e scripts, não como cota de cobrança.

## 6. `cipher.py`

```python
import json
import logging

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


class ChaveInvalida(Exception):
    """CHAVE_ORIGINAIS está preenchida, mas não é uma chave Fernet válida."""


def _fernet() -> Fernet | None:
    if not config.CHAVE_ORIGINAIS:
        return None
    try:
        return Fernet(config.CHAVE_ORIGINAIS.encode())
    except ValueError:
        raise ChaveInvalida("CHAVE_ORIGINAIS inválida no .env: gere com python -m api.cipher --nova-chave") from None


def cifra(original: dict[str, str]) -> str | None:
    """{"historico", "contraparte"} -> texto cifrado; None se não houver chave."""
    f = _fernet()
    return None if f is None else f.encrypt(json.dumps(original, ensure_ascii=False).encode()).decode()


def decifra(cifrado: str | None) -> dict[str, str] | None:
    """None se vazio, sem chave ou cifrado com outra chave (aí a tela mostra o anonimizado)."""
    if not cifrado:
        return None
    f = _fernet()
    if f is None:
        return None
    try:
        return json.loads(f.decrypt(cifrado.encode()))
    except (InvalidToken, ValueError):
        log.warning("texto original não pôde ser decifrado (chave diferente?)")
        return None


if __name__ == "__main__":
    if sys.argv[1:] == ["--nova-chave"]:
        print(Fernet.generate_key().decode())
    else:
        print(__doc__)
```

## 7. `services/extraction.py`

```python
import tempfile
from dataclasses import asdict
from pathlib import Path

from statement.merchants import declared_people
from statement.parsers.base import first_line, pdf_text
from statement.pipeline import run


class VazamentoNaSaida(Exception):
    """O validador achou possível dado pessoal: nenhuma linha pode ser devolvida."""


def processa_extrato(conteudo: bytes, extensao: str, usuario: str) -> ResultadoUpload:
    """Roda o pipeline num diretório temporário, apagado no fim. Nada fica gravado."""
    pessoas = declared_people(config.DIR_PRIVADO)
    try:
        with tempfile.TemporaryDirectory(prefix="extrato_") as tmp:
            pasta = Path(tmp)
            arquivo = pasta / f"extrato{extensao}"  # nome fixo: o original pode ter dado pessoal
            arquivo.write_bytes(conteudo)
            execucao = run(arquivo, usuario, pasta / "saida.csv", pasta / "privado", people=pessoas)
    finally:
        pdf_text.cache_clear()  # os caches de leitura guardam o texto do arquivo
        first_line.cache_clear()

    if execucao.leak is not None:
        raise VazamentoNaSaida(str(execucao.leak))

    dados = asdict(execucao.reports[0])
    relatorio = Relatorio(**{campo: dados[campo] for campo in Relatorio.model_fields})
    transacoes = [
        Transacao(**linha.model_dump(exclude={"id_usuario"}),
                  historico_original=original["historico"], contraparte_original=original["contraparte"])
        for linha, original in zip(execucao.lines, execucao.originals, strict=True)
    ]
    return ResultadoUpload(relatorio=relatorio, transacoes=transacoes)
```

As linhas de revisão e os históricos desconhecidos vão para a pasta privada **temporária** e
somem com ela: na API, nada disso fica gravado.

## 8. `services/categorization.py`

```python
_cache_modelo: dict[Path, tuple[float, object]] = {}  # caminho -> (data de modificação, modelo)


def carrega_modelo(caminho: Path):
    """O classificador do .pkl, ou None se ele não existir ou não carregar."""
    try:
        modificado = caminho.stat().st_mtime
    except FileNotFoundError:
        return None
    em_cache = _cache_modelo.get(caminho)
    if em_cache is not None and em_cache[0] == modificado:
        return em_cache[1]
    try:
        modelo = joblib.load(caminho)
    except Exception:  # versão diferente do scikit-learn, arquivo corrompido...
        log.exception("não foi possível carregar o classificador %s; seguindo sem ele", caminho)
        return None
    _cache_modelo[caminho] = (modificado, modelo)
    return modelo


def _entrada_e_receita(t: Transacao) -> Transacao:
    if t.tipo == "entrada":
        return t.model_copy(update={"categoria": Category.INCOME.value, "origem_categoria": "regra"})
    return t


def _pelo_modelo(transacoes: list[Transacao], modelo) -> list[Transacao]:
    pendentes = [i for i, t in enumerate(transacoes) if t.categoria is None]
    if not pendentes:
        return transacoes
    linhas = []
    for i in pendentes:
        t = transacoes[i]
        linha = t.model_dump(include=set(COLUMNS) - {"id_usuario"})
        linha.update(id_usuario="", data=t.data.isoformat(), valor=float(t.valor))
        linhas.append(linha)
    previstas = modelo.predict(pd.DataFrame(linhas, columns=list(COLUMNS)))
    resultado = list(transacoes)
    for i, categoria in zip(pendentes, previstas):
        resultado[i] = transacoes[i].model_copy(update={"categoria": str(categoria), "origem_categoria": "modelo"})
    return resultado


def categoriza(resultado: ResultadoUpload) -> ResultadoUpload:
    transacoes = [_entrada_e_receita(t) for t in resultado.transacoes]
    modelo = carrega_modelo(config.CAMINHO_MODELO)
    if modelo is not None:
        transacoes = _pelo_modelo(transacoes, modelo)
    else:
        log.warning("classificador ausente (%s): as saídas ficam sem categoria", config.CAMINHO_MODELO)
    return resultado.model_copy(update={"transacoes": transacoes,
                                        "sem_categoria": sum(t.categoria is None for t in transacoes)})
```

## 9. `services/retraining.py`

```python
_um_por_vez = threading.Lock()


@contextmanager
def _abre_banco():
    with conexao(config.DATABASE_URL) as con:
        yield Banco(con)


abre_banco = _abre_banco  # trocado nos testes por um banco falso


def precisa_retreinar(db) -> bool:
    return db.correcoes_desde_ultimo_treino() >= CORRECTIONS_TO_RETRAIN and not db.treino_rodando()


def _como_tabela(linhas) -> pd.DataFrame:
    df = pd.DataFrame(linhas, columns=[*COLUMNS, "categoria", "corrigida_em"])
    df["id_usuario"] = ""
    df["data"] = df["data"].astype(str)
    df["valor"] = df["valor"].astype(float)
    return df


def _salva(modelo) -> None:
    """Grava ao lado e troca de uma vez: quem carrega o .pkl nunca pega um arquivo pela metade."""
    destino = config.CAMINHO_MODELO
    novo = destino.with_name(destino.stem + ".novo.pkl")
    joblib.dump(modelo, novo)
    if destino.exists():
        shutil.copy2(destino, destino.with_name(destino.stem + ".anterior.pkl"))
    os.replace(novo, destino)


def executa_retreino() -> dict | None:
    """Roda um retreino agora. None se outro já estiver rodando."""
    if not _um_por_vez.acquire(blocking=False):
        return None
    try:
        with abre_banco() as db:
            if db.treino_rodando():
                return None
            treino_id = db.inicia_treino()
            correcoes = _como_tabela(db.correcoes_para_treino())
        try:
            r = retrain(read_base(config.CAMINHO_TREINO_BASE), correcoes, carrega_modelo(config.CAMINHO_MODELO))
            _salva(r.model)
            registro = dict(status="ok", correcoes=r.correcoes, linhas_treino=r.linhas_treino,
                            acerto_correcoes_antes=r.acerto_correcoes_antes,
                            acerto_correcoes_depois=r.acerto_correcoes_depois,
                            acerto_base_depois=r.acerto_base_depois)
        except (OSError, ValueError) as exc:  # CSV base ausente, sem categoria... (mensagens nossas)
            registro = dict(status="erro", correcoes=len(correcoes), mensagem=f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # outra falha: só o tipo (a mensagem pode trazer valores dos dados)
            log.exception("retreino falhou")
            registro = dict(status="erro", correcoes=len(correcoes), mensagem=type(exc).__name__)
        with abre_banco() as db:
            db.conclui_treino(treino_id, **registro)
        return registro
    finally:
        _um_por_vez.release()


def _em_segundo_plano(alvo) -> None:
    threading.Thread(target=alvo, name="retreino", daemon=True).start()


inicia_em_segundo_plano = _em_segundo_plano  # trocado nos testes para rodar na hora


def dispara_se_preciso(db) -> bool:
    """Chamado depois de gravar uma correção (já confirmada no banco). True se disparou."""
    try:
        if not precisa_retreinar(db):
            return False
    except Exception:  # o retreino nunca pode atrapalhar a correção do usuário
        log.exception("não foi possível verificar se precisa retreinar")
        return False
    inicia_em_segundo_plano(executa_retreino)
    return True
```

## 10. Rota de importação

```python
router = APIRouter(tags=["extratos"])


def _para_gravar(t: Transacao) -> dict:
    """Campos anonimizados + o original só cifrado (nunca em texto puro)."""
    linha = t.model_dump(exclude={"historico_original", "contraparte_original"})
    if t.historico_original is not None or t.contraparte_original is not None:
        linha["original_cifrado"] = cipher.cifra(
            {"historico": t.historico_original or "", "contraparte": t.contraparte_original or ""})
    return linha


# def (não async def): a extração é pesada e bloqueante; o FastAPI roda numa thread à parte
@router.post("/extratos", dependencies=[Depends(limita_importacao)])
def envia_extrato(
    arquivo: Annotated[UploadFile, File(description="Extrato em PDF ou CSV")],
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    db: Annotated[Banco, Depends(banco)],
    pseudonimo: Annotated[str, Form(alias="usuario", description="Pseudônimo uNN")] = USUARIO_PADRAO,
) -> ResultadoImportacao:
    if not re.fullmatch(r"u\d{2}", pseudonimo):
        raise HTTPException(400, "usuário deve ser 'u' + 2 dígitos (ex.: u07)")
    nome = PurePath(arquivo.filename or "")
    extensao = nome.suffix.lower()
    if extensao not in EXTENSOES_ACEITAS:
        raise HTTPException(400, "formato não aceito: envie um arquivo .pdf ou .csv")
    conteudo = arquivo.file.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(400, "arquivo maior que 10 MB")
    if not conteudo:
        raise HTTPException(400, "arquivo vazio")
    try:
        resultado = processa_extrato(conteudo, extensao, pseudonimo)
    except VazamentoNaSaida:
        raise HTTPException(422, "possível dado pessoal detectado na saída: nenhuma transação foi devolvida") from None
    resultado = categoriza(resultado)

    gravacao = None
    if resultado.relatorio.status == "aceito" and resultado.transacoes:
        db.garante_usuario(usuario.id, usuario.email, usuario.nome)
        try:
            g = db.grava_extrato(
                usuario.id, nome_arquivo=nome.name[:200], hash_arquivo=hashlib.sha256(conteudo).hexdigest(),
                parser=resultado.relatorio.parser,
                periodo_inicio=_data_ou_none(resultado.relatorio.periodo_inicio),
                periodo_fim=_data_ou_none(resultado.relatorio.periodo_fim),
                transacoes=[_para_gravar(t) for t in resultado.transacoes])
        except ExtratoRepetido:
            raise HTTPException(409, "este arquivo já foi importado") from None
        except cipher.ChaveInvalida as exc:
            raise HTTPException(500, str(exc)) from None
        gravacao = Gravacao(extrato_id=g.extrato_id, gravadas=g.gravadas, repetidas=g.repetidas)
    return ResultadoImportacao(**resultado.model_dump(), gravacao=gravacao)
```

A correção de categoria segue o mesmo estilo: valida a categoria contra `ml.classes.Category`,
chama `db.muda_categoria` (404 se não for do usuário), `db.confirma()` e
`retraining.dispara_se_preciso(db)`.

## 11. Testes

`api/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def dir_privado(tmp_path, monkeypatch):
    """Nunca ler os mapas reais de data/privado: cada teste tem uma pasta vazia."""
    pasta = tmp_path / "privado"
    pasta.mkdir()
    monkeypatch.setattr(config, "DIR_PRIVADO", pasta)
    return pasta


@pytest.fixture(autouse=True)
def sem_modelo_real(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CAMINHO_MODELO", tmp_path / "nao_existe.pkl")
    monkeypatch.setattr(config, "CAMINHO_TREINO_BASE", tmp_path / "nao_existe.csv")


@pytest.fixture(autouse=True)
def chave_originais(monkeypatch):
    chave = Fernet.generate_key().decode()  # nunca a do .env
    monkeypatch.setattr(config, "CHAVE_ORIGINAIS", chave)
    return chave


@pytest.fixture(autouse=True)
def db():
    falso = BancoFalso()  # mesma interface do Banco, em memória
    app.dependency_overrides[banco] = lambda: falso
    app.dependency_overrides[usuario_atual] = lambda: USUARIO
    yield falso
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def retreino_no_banco_falso(db, monkeypatch):
    from contextlib import nullcontext
    from api.services import retraining
    monkeypatch.setattr(retraining, "abre_banco", lambda: nullcontext(db))
    monkeypatch.setattr(retraining, "inicia_em_segundo_plano", lambda alvo: alvo())  # sem thread


@pytest.fixture
def logado_como():
    def troca(usuario):
        app.dependency_overrides[usuario_atual] = lambda: usuario
    return troca


@pytest.fixture(autouse=True)
def limites_zerados():
    LIMITE_CHAT.zera()
    LIMITE_IMPORTACAO.zera()
```

Exemplo de ponta a ponta com um CSV inventado:

```python
from fastapi.testclient import TestClient

cliente = TestClient(app)
CSV = ("Data,Valor,Identificador,Descrição\n"
       "02/01/2024,-12.50,11111111-2222-4333-8444-555555555555,Compra no débito - PADARIA MODELO\n")


def test_importa_grava_e_recusa_repetido(db):
    r = cliente.post("/api/extratos", files={"arquivo": ("extrato.csv", CSV.encode(), "text/csv")})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["relatorio"]["status"] == "aceito" and corpo["gravacao"]["gravadas"] == 1
    assert corpo["transacoes"][0]["categoria"] is None  # sem .pkl nos testes: saída sem categoria
    assert db.linhas[0]["original_cifrado"]             # o original foi para o banco só cifrado
    r2 = cliente.post("/api/extratos", files={"arquivo": ("outro_nome.csv", CSV.encode(), "text/csv")})
    assert r2.status_code == 409
```
