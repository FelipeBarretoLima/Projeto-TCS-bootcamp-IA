# Acesso ao banco: conexão, migrações, deduplicação e repositório

Código do projeto de referência (`database/`).

## Sumário

1. `connection.py`
2. `migrate.py`
3. `deduplication.py`
4. `repository.py` (métodos principais)
5. Testes de contrato e contra o banco real

## 1. `connection.py`

```python
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


class BancoNaoConfigurado(Exception):
    """DATABASE_URL vazio no .env."""


def _abre(url: str) -> ConnectionPool:
    # prepare_threshold=None: sem prepared statements, que o pooler do Supabase pode não aceitar
    return ConnectionPool(url, min_size=1, max_size=5, open=True, timeout=15,
                          kwargs={"prepare_threshold": None, "connect_timeout": 10})


@contextmanager
def conexao(url: str) -> Iterator[psycopg.Connection]:
    """Uma conexão do pool. Sai sem erro: commit. Sai com erro: rollback."""
    global _pool
    if not url:
        raise BancoNaoConfigurado
    if _pool is None:
        _pool = _abre(url)
    with _pool.connection() as con:
        yield con


def fecha() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
```

## 2. `migrate.py`

```python
PASTA = Path(__file__).parent / "migrations"

_CRIA_REGISTRO = """
create table if not exists public.migracoes_aplicadas (
    nome       text primary key,
    aplicada_em timestamptz not null default now()
);
alter table public.migracoes_aplicadas enable row level security;
"""


def migracoes(pasta: Path = PASTA) -> list[Path]:
    return sorted(pasta.glob("*.sql"))


def url_do_banco() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("erro: DATABASE_URL vazio. Preencha o arquivo .env na raiz do projeto.")
    return url


def aplica(conexao: psycopg.Connection, pasta: Path = PASTA) -> list[str]:
    """Aplica as pendentes, uma transação por arquivo. Devolve os nomes aplicados agora."""
    with conexao.transaction():
        conexao.execute(_CRIA_REGISTRO)
    feitas = {n for (n,) in conexao.execute("select nome from public.migracoes_aplicadas")}
    aplicadas = []
    for arquivo in migracoes(pasta):
        if arquivo.name in feitas:
            continue
        with conexao.transaction():
            conexao.execute(arquivo.read_text("utf-8"))
            conexao.execute("insert into public.migracoes_aplicadas (nome) values (%s)", (arquivo.name,))
        aplicadas.append(arquivo.name)
    return aplicadas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m database.migrate")
    ap.add_argument("--status", action="store_true", help="só mostra o que já foi aplicado e o que falta")
    args = ap.parse_args(argv)
    with psycopg.connect(url_do_banco(), autocommit=True) as conexao:
        if args.status:
            existe = conexao.execute("select to_regclass('public.migracoes_aplicadas')").fetchone()[0]
            feitas = {n for (n,) in conexao.execute("select nome from public.migracoes_aplicadas")} if existe else set()
            for arquivo in migracoes():
                print(f"  {'aplicada' if arquivo.name in feitas else 'PENDENTE':9} {arquivo.name}")
            return 0
        aplicadas = aplica(conexao)
    print("\n".join(f"aplicada: {n}" for n in aplicadas) or "nada a aplicar: o banco já está em dia")
    return 0
```

`autocommit=True` + `conexao.transaction()` por arquivo: cada migração é atômica e
independente. O SQL inteiro do arquivo vai num `execute` só (sem parâmetros, o psycopg aceita
vários comandos).

## 3. `deduplication.py`

```python
from collections import defaultdict
from decimal import Decimal

Chave = tuple[str, date, Decimal, str, str, str, str]


def chave(t) -> Chave:
    return (t["banco"], t["data"], Decimal(t["valor"]).quantize(Decimal("0.01")), t["tipo"], t["meio"],
            t["historico"], t["contraparte"] or "")


def separa_novas_com_ids(existentes, novas):
    """(as que devem ser gravadas, os ids das existentes que casaram com as repetidas)."""
    restam: defaultdict[Chave, list] = defaultdict(list)
    for t in existentes:
        restam[chave(t)].append(t.get("id"))
    gravar, ids_repetidas = [], []
    for t in novas:
        fila = restam.get(chave(t))
        if fila:
            ids_repetidas.append(fila.pop(0))   # cada existente "absorve" uma repetida só: contagem
        else:
            gravar.append(t)
    return gravar, ids_repetidas
```

## 4. `repository.py` (métodos principais)

```python
COLUNAS_TRANSACAO = ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco",
                     "categoria", "origem_categoria")
COLUNA_ORIGINAL = "original_cifrado"


class ExtratoRepetido(Exception): ...
class ConversaApagada(Exception): ...


@dataclass(frozen=True)
class Gravacao:
    extrato_id: UUID
    gravadas: int
    repetidas: int


class Banco:
    def __init__(self, conexao):
        self.con = conexao

    def confirma(self):
        self.con.commit()

    def _todas(self, sql, *args):
        with self.con.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, args).fetchall()

    def _uma(self, sql, *args):
        with self.con.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, args).fetchone()

    def garante_usuario(self, usuario_id, email, nome=""):
        self.con.execute("insert into public.usuarios (id, email, nome) values (%s, %s, %s) "
                         "on conflict (id) do nothing", (usuario_id, email, nome))

    def apaga_conta(self, usuario_id):
        """Apaga o login no Supabase Auth; o resto vai em cascata."""
        self.con.execute("delete from auth.users where id = %s", (usuario_id,))

    def grava_extrato(self, usuario_id, *, nome_arquivo, hash_arquivo, parser, periodo_inicio,
                      periodo_fim, transacoes) -> Gravacao:
        # importações do mesmo usuário em fila até o commit: sem isto, dois extratos sobrepostos
        # enviados ao mesmo tempo duplicavam as transações repetidas
        self.con.execute("select pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (str(usuario_id),))
        if self._uma("select 1 from public.extratos where usuario_id = %s and hash_arquivo = %s",
                     usuario_id, hash_arquivo):
            raise ExtratoRepetido
        existentes = []
        if transacoes:
            datas = [t["data"] for t in transacoes]
            existentes = self._todas(
                "select id, banco, data, valor, tipo, meio, historico, contraparte from public.transacoes "
                "where usuario_id = %s and banco = any(%s) and data between %s and %s order by id",
                usuario_id, sorted({t["banco"] for t in transacoes}), min(datas), max(datas))
        gravar, ids_repetidas = separa_novas_com_ids(existentes, transacoes)
        bancos = Counter(t["banco"] for t in transacoes)
        banco = bancos.most_common(1)[0][0] if bancos else ""
        try:
            extrato_id = self._uma(
                "insert into public.extratos (usuario_id, nome_arquivo, hash_arquivo, banco, parser, "
                "periodo_inicio, periodo_fim, linhas_gravadas) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
                usuario_id, nome_arquivo, hash_arquivo, banco, parser, periodo_inicio, periodo_fim, len(gravar))["id"]
        except psycopg.errors.UniqueViolation:
            raise ExtratoRepetido from None  # o mesmo arquivo chegou duas vezes ao mesmo tempo
        if gravar:
            colunas = (*COLUNAS_TRANSACAO, COLUNA_ORIGINAL)
            with self.con.cursor() as cur:
                cur.executemany(
                    f"insert into public.transacoes (usuario_id, extrato_id, {', '.join(colunas)}) "
                    f"values (%s, %s, {', '.join(['%s'] * len(colunas))})",
                    [(usuario_id, extrato_id, *(t[c] for c in COLUNAS_TRANSACAO), t.get(COLUNA_ORIGINAL))
                     for t in gravar])
        self.con.execute(  # vínculos: as gravadas agora...
            "insert into public.extrato_transacoes (extrato_id, transacao_id) "
            "select %s, id from public.transacoes where extrato_id = %s", (extrato_id, extrato_id))
        if ids_repetidas:  # ...e as repetidas, que já estavam no banco vindas de outro extrato
            self.con.execute(
                "insert into public.extrato_transacoes (extrato_id, transacao_id) "
                "select %s, unnest(%s::bigint[]) on conflict do nothing", (extrato_id, ids_repetidas))
        return Gravacao(extrato_id, len(gravar), len(ids_repetidas))

    def apaga_extrato(self, usuario_id, extrato_id) -> bool:
        """Apaga o extrato e as transações que só ele trouxe; as que outro extrato também trouxe
        passam para o mais antigo desses outros."""
        if not self._uma("select 1 from public.extratos where id = %s and usuario_id = %s",
                         extrato_id, usuario_id):
            return False
        herdeiros = self._todas(
            "update public.transacoes t set extrato_id = o.extrato_id "
            "from (select distinct on (et.transacao_id) et.transacao_id, et.extrato_id "
            "      from public.extrato_transacoes et "
            "      join public.extratos e on e.id = et.extrato_id and e.usuario_id = %s "
            "      where et.extrato_id <> %s and et.transacao_id in "
            "            (select id from public.transacoes where extrato_id = %s) "
            "      order by et.transacao_id, e.enviado_em) o "
            "where t.id = o.transacao_id returning t.extrato_id",
            usuario_id, extrato_id, extrato_id)
        if herdeiros:
            self.con.execute(
                "update public.extratos e set linhas_gravadas = "
                "(select count(*) from public.transacoes t where t.extrato_id = e.id) where e.id = any(%s)",
                (sorted({h["extrato_id"] for h in herdeiros}),))
        cur = self.con.execute("delete from public.extratos where id = %s and usuario_id = %s",
                               (extrato_id, usuario_id))
        return cur.rowcount > 0

    def transacoes(self, usuario_id):
        """Para o painel e o chat: sem o original cifrado."""
        return self._todas(
            "select data, historico, contraparte, valor, tipo, meio, banco, categoria from public.transacoes "
            "where usuario_id = %s order by data, id", usuario_id)

    def busca_transacoes(self, usuario_id, *, inicio=None, fim=None, categoria=None, sem_categoria=False):
        """Aba Extrato, da mais recente para a mais antiga, com o original cifrado."""
        condicoes, args = ["usuario_id = %s"], [usuario_id]
        if inicio is not None:
            condicoes.append("data >= %s"); args.append(inicio)
        if fim is not None:
            condicoes.append("data <= %s"); args.append(fim)
        if sem_categoria:
            condicoes.append("categoria is null")
        elif categoria is not None:
            condicoes.append("categoria = %s"); args.append(categoria)
        return self._todas(
            "select id, data, historico, contraparte, valor, tipo, meio, banco, categoria, original_cifrado "
            f"from public.transacoes where {' and '.join(condicoes)} order by data desc, id desc", *args)

    def muda_categoria(self, usuario_id, transacao_id, categoria) -> bool:
        """Correção do usuário (origem 'usuario'); None = sem categoria. Também grava em
        public.correcoes, onde sobrevive à exclusão do extrato."""
        linha = self._uma(
            "update public.transacoes set categoria = %s, "
            "origem_categoria = case when %s::text is null then null else 'usuario' end, "
            "corrigida_em = case when %s::text is null then null else now() end "
            "where id = %s and usuario_id = %s "
            "returning data, historico, contraparte, valor, tipo, meio, banco",
            categoria, categoria, categoria, transacao_id, usuario_id)
        if linha is None:
            return False
        if categoria is None:
            self.con.execute("delete from public.correcoes where transacao_id = %s", (transacao_id,))
            return True
        campos = tuple(linha[c] for c in _CAMPOS_DA_CORRECAO)  # data, historico, ..., banco
        lista, marcas = ", ".join(_CAMPOS_DA_CORRECAO), ", ".join(["%s"] * len(_CAMPOS_DA_CORRECAO))
        # correção órfã da mesma transação (extrato excluído e reimportado): dá lugar a esta
        self.con.execute(f"delete from public.correcoes where usuario_id = %s and transacao_id is null "
                         f"and ({lista}) = ({marcas})", (usuario_id, *campos))
        self.con.execute(
            f"insert into public.correcoes (usuario_id, transacao_id, {lista}, categoria) "
            f"values (%s, %s, {marcas}, %s) "
            "on conflict (transacao_id) do update set categoria = excluded.categoria, corrigida_em = now()",
            (usuario_id, transacao_id, *campos, categoria))
        return True

    # --- retreino: lê as correções de todos (só campos anonimizados) ---

    def correcoes_para_treino(self):
        return self._todas(  # inclui as de extratos já excluídos
            "select data, historico, contraparte, valor, tipo, meio, banco, categoria, corrigida_em "
            "from public.correcoes order by corrigida_em, id")

    def correcoes_desde_ultimo_treino(self) -> int:
        return self._uma(
            "select count(*) as n from public.correcoes "
            "where corrigida_em > coalesce((select max(iniciado_em) from public.treinos_modelo "
            "where status <> 'rodando'), '-infinity')")["n"]  # desde a última tentativa concluída

    def inicia_treino_se_livre(self) -> int | None:
        """Atômico entre processos: a trava vale até o commit de quem chamou."""
        self.con.execute("select pg_advisory_xact_lock(%s)", (7_242_001,))
        return None if self.treino_rodando() else self.inicia_treino()

    def treino_rodando(self) -> bool:
        """Um 'rodando' de mais de 30 min é considerado travado."""
        return self._uma("select 1 from public.treinos_modelo where status = 'rodando' "
                         "and iniciado_em > now() - interval '30 minutes'") is not None

    # inicia_treino() -> id; conclui_treino(id, status=..., correcoes=..., ...); treinos(limite)

    # --- conversas ---
    # lista_conversas, cria_conversa(usuario_id, titulo) -> id, conversa_e_do_usuario,
    # renomeia_conversa, apaga_conversa (todos com "where ... and usuario_id = %s"),
    # mensagens(conversa_id) ordenadas por (criada_em, id)

    def grava_mensagem(self, conversa_id, papel, texto, grafico=None):
        try:
            return self._uma(
                "insert into public.mensagens (conversa_id, papel, texto, grafico) values (%s, %s, %s, %s) "
                "returning id, papel, texto, grafico, criada_em",
                conversa_id, papel, texto, json.dumps(grafico, default=_json) if grafico else None)
        except psycopg.errors.ForeignKeyViolation:
            raise ConversaApagada from None


def _json(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    raise TypeError(type(valor))
```

A contagem do retreino conta transações, não cliques: corrigir a mesma transação duas vezes
conta uma vez, porque só atualiza `corrigida_em`.

## 5. Testes de contrato e contra o banco real

Contrato, sem banco (`database/tests/test_migrations.py`):

```python
SQL = "\n".join(m.read_text("utf-8") for m in migracoes())


def _valores_do_check(coluna: str) -> set[str]:
    m = re.search(rf"\b{coluna}\b[^\n]*?check \({coluna} in \((.*?)\)\)", SQL, re.S)
    assert m, f"check de {coluna} não encontrado"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_categorias_iguais_as_do_modelo():
    assert _valores_do_check("categoria") == {c.value for c in Category}


def test_meios_e_tipos_iguais_aos_do_parser():
    assert _valores_do_check("meio") == {m.value for m in PaymentMethod}
    assert _valores_do_check("tipo") == {t.value for t in TransactionType}


def test_nenhuma_coluna_de_senha():
    codigo = re.sub(r"--[^\n]*", "", SQL)  # só o código, sem os comentários
    assert not re.search(r"senha|password", codigo, re.I)
```

Banco real, só com `TESTE_BANCO=1`, tudo desfeito no fim:

```python
pytestmark = pytest.mark.skipif(os.environ.get("TESTE_BANCO") != "1", reason="defina TESTE_BANCO=1")


@pytest.fixture
def db():
    con = psycopg.connect(url_do_banco(), prepare_threshold=None)
    try:
        yield Banco(con)
    finally:
        con.rollback()
        con.close()


def _usuario(db):
    uid = uuid.uuid4()
    db.con.execute("insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
                   (uid, f"{uid}@teste.invalid"))
    return uid  # o gatilho cria o perfil
```
