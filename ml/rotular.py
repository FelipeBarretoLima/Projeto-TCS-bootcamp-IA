"""Rotulagem do treino: CSV do parser + coluna `categoria` (regras + mapa de estabelecimentos).

    python -m ml.rotular
        [--entrada data/saida/transacoes.csv] [--saida ml/dados/transacoes_rotuladas.csv]
        [--privado data/privado]

Entrada: exatamente o CSV do parser (contrato de 8 colunas). Saída: as mesmas colunas, na mesma
ordem e com os mesmos valores, mais `categoria` no fim. Nada mais muda: na aplicação, o parser
entrega o mesmo CSV sem a categoria e o classificador acrescenta a coluna.

Mapa de estabelecimentos (data/privado, fora do git — tem nomes reais), mantido pelo usuário:
    estabelecimentos_revisar.csv   primeiro mapa (prioridade)
    estabelecimentos_novos.csv     acrescido a cada rotulagem com o que ainda não está mapeado
    Nos dois, classe em branco = aceita a classe sugerida (decisão do usuário em 2026-11-04).
O mapa é casado pelo nome-base do estabelecimento (o mesmo que o parser grava na contraparte).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from extrato.estabelecimentos import nome_base, parece_pessoa
from extrato.modelos import COLUNAS, PESSOA_FISICA, Meio, Tipo
from extrato.normalizacao import sem_acento

from .classes import Categoria, por_regra

ARQ_REVISADO = "estabelecimentos_revisar.csv"
ARQ_NOVOS = "estabelecimentos_novos.csv"
COLUNAS_MAPA = ["contraparte", "linhas", "classe_sugerida", "regra_achou_classe", "nome_canonico_sugerido",
                "parece_pessoa", "classe", "nome_canonico", "e_pessoa"]
COLUNAS_ROTULADAS = (*COLUNAS, "categoria")


def _le(caminho: Path) -> list[dict[str, str]]:
    if not caminho.exists():
        return []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def carrega_mapa(dir_privado: Path) -> dict[str, Categoria]:
    """nome-base do estabelecimento -> classe. Classe inválida é erro (corrigir na planilha).

    Se duas linhas do mapa caem no mesmo nome-base com classes diferentes, vale a do arquivo
    revisado e, dentro do mesmo arquivo, a de mais ocorrências.
    """
    mapa: dict[str, Categoria] = {}
    peso: dict[str, tuple[int, int]] = {}
    for prioridade, arquivo in enumerate((ARQ_REVISADO, ARQ_NOVOS)):
        for n, r in enumerate(_le(dir_privado / arquivo), start=2):
            classe = (r.get("classe") or "").strip() or r.get("classe_sugerida", "")
            if not classe:
                continue
            if classe not in Categoria.__members__.values():
                raise ValueError(f"{arquivo}, linha {n}: classe inválida (use uma das 8 classes)")
            chaves = {nome_base(r["contraparte"])}
            if (r.get("nome_canonico") or "").strip():
                chaves.add(nome_base(r["nome_canonico"]))
            p = (-prioridade, int(r.get("linhas") or 0))
            for k in chaves:
                if k and (k not in peso or p > peso[k]):
                    mapa[k], peso[k] = Categoria(classe), p
    return mapa


def categoria(linha: dict[str, str], mapa: dict[str, Categoria]) -> Categoria | None:
    regra = por_regra(Meio(linha["meio"]), Tipo(linha["tipo"]), linha["historico"], linha["contraparte"])
    # o mapa é indexado pelo nome-base (PIX para empresa chega sem a padronização do cartão)
    return regra if regra is not None else mapa.get(nome_base(linha["contraparte"]))


# --- sugestões para o que ainda não está no mapa ---

_REGRAS_CLASSE = [
    (Categoria.ALIMENTACAO_FORA, r"\bIFD\b|IFOOD|LANCH|RESTAUR|PIZZ|BURG|FOODS?\b|\bBAR\b|BEER|CAFE|SORVET|CHURRAS|"
                                 r"ACAI|PASTEL|SUSHI|OUTBACK|MC ?DONALD|\bBK\b|SUBWAY|ESPETO|CHOPP|BISTRO|COZINHA"),
    (Categoria.MERCADO, r"SUPER|MERCAD|SACOLAO|ASSAI|ATACAD|HORTI|PADARIA|PANIF|ACOUGUE|EMPORIO|"
                        r"BEBID|CONVENIENC|FRUT|QUITANDA|ARMAZEM"),
    (Categoria.TRANSPORTE, r"UBER|\b99\b|POSTO|COMBUST|PEDAGIO|SEM PARAR|ESTACION|AUTO ?PECAS|PNEU|MECANIC"),
    (Categoria.CONTAS_SERVICOS, r"TOTALPASS|NETFLIX|SPOTIFY|BYTEDANCE|GOOGLE|APPLE|PRIME|DISNEY|YOUTUBE|DEEZER|"
                                r"OPENAI|MICROSOFT|FARMA|DROGA|RAIA|PACHECO|CLINIC|ODONTO|HOSPITAL|LABORAT|"
                                r"CLARO|VIVO|\bTIM\b|\bOI\b|ENERGIA|SANEAMENTO|ACADEMIA|SMART ?FIT"),
    (Categoria.COMPRAS, r"SHOPEE|SHPP|MERCADO ?LIVRE|AMAZON|MAGAZINE|MAGALU|AMERICANAS|ALIEXPRESS|SHEIN|RENNER|"
                        r"RIACHUELO|\bC ?& ?A\b|LOJA|MODAS?|CALCAD|ELETRO|PAPELAR"),
]


def sugere_classe(contraparte: str) -> Categoria | None:
    c = sem_acento(contraparte).upper()
    return next((k for k, rx in _REGRAS_CLASSE if re.search(rx, c)), None)


def atualiza_novos(dir_privado: Path, sem_categoria: Iterable[str]) -> int:
    """Acrescenta a estabelecimentos_novos.csv o que ainda não está em nenhum mapa.

    Nunca apaga nem altera linhas existentes (o usuário pode estar preenchendo). Devolve quantos entraram.
    """
    caminho = dir_privado / ARQ_NOVOS
    ja = {nome_base(r["contraparte"]) for arq in (ARQ_REVISADO, ARQ_NOVOS) for r in _le(dir_privado / arq)}
    contagem = Counter(c for c in sem_categoria if c and c != PESSOA_FISICA and nome_base(c) not in ja)
    if not contagem:
        return 0
    novas = []
    for c, n in contagem.most_common():
        sug = sugere_classe(c)
        novas.append({"contraparte": c, "linhas": str(n), "classe_sugerida": sug.value if sug else "compras",
                      "regra_achou_classe": "sim" if sug else "não (padrão: compras)",
                      "nome_canonico_sugerido": c, "parece_pessoa": "sim" if parece_pessoa(c) else "",
                      "classe": "", "nome_canonico": "", "e_pessoa": ""})
    existe = caminho.exists()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_MAPA, lineterminator="\n")
        if not existe:
            w.writeheader()
        w.writerows(novas)
    return len(novas)


# --- rotulagem ---

@dataclass
class Resultado:
    linhas: int = 0
    por_categoria: Counter[str] = field(default_factory=Counter)
    novos_no_mapa: int = 0


def rotula(entrada: Path, saida: Path, dir_privado: Path) -> Resultado:
    with open(entrada, encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f)
        if tuple(leitor.fieldnames or ()) != COLUNAS:
            raise ValueError("a entrada não está no contrato do parser (cabeçalho diferente)")
        linhas = list(leitor)
    mapa = carrega_mapa(dir_privado)
    res = Resultado(linhas=len(linhas))
    sem: list[str] = []
    saida.parent.mkdir(parents=True, exist_ok=True)
    temporario = saida.with_name(saida.name + ".tmp")
    with open(temporario, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUNAS_ROTULADAS)
        for l in linhas:
            c = categoria(l, mapa)
            if c is None:
                sem.append(l["contraparte"])
            res.por_categoria[c.value if c else "(sem categoria)"] += 1
            w.writerow([*(l[k] for k in COLUNAS), c.value if c else ""])
    temporario.replace(saida)
    res.novos_no_mapa = atualiza_novos(dir_privado, sem)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ml.rotular", description="rotula o CSV do parser para o treino")
    ap.add_argument("--entrada", type=Path, default=Path("data/saida/transacoes.csv"))
    ap.add_argument("--saida", type=Path, default=Path("ml/dados/transacoes_rotuladas.csv"))
    ap.add_argument("--privado", type=Path, default=Path("data/privado"))
    args = ap.parse_args(argv)
    try:
        res = rotula(args.entrada, args.saida, args.privado)
    except (OSError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 3
    print(f"{res.linhas} linha(s) rotuladas em {args.saida}")
    for k, v in res.por_categoria.most_common():
        print(f"  {k:22} {v:6}  {100 * v / max(res.linhas, 1):5.1f}%")
    if res.novos_no_mapa:
        print(f"{res.novos_no_mapa} estabelecimento(s) novo(s) em {args.privado / ARQ_NOVOS} "
              "(classe em branco = aceita a sugerida)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
