"""Padrões de dados pessoais, compartilhados pela anonimização e pelo validador.

Todos os padrões rodam sobre texto já em maiúsculas (ver `normaliza_texto`).
`X`, `*` e `•` são tratados como caracteres de máscara usados pelos bancos.
"""

from __future__ import annotations

import re

from .normalizacao import normaliza_texto, sem_acento

_M = r"[\d*•X]"  # dígito ou máscara

# A ordem importa na remoção: padrões mais longos primeiro, para um curto não
# cortar um pedaço de outro (ex.: CNPJ dentro de uma linha digitável).
PADROES: dict[str, re.Pattern[str]] = {
    # linha digitável (47/48 dígitos) ou código de barras (44)
    "boleto": re.compile(r"\d(?:[\s.]?\d){43,47}"),
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    # UUID: formato das chaves PIX aleatórias
    "chave_pix_aleatoria": re.compile(
        r"\b[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\b"
    ),
    "cnpj": re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}\s?/?\s?\d{4}-?\d{2}\b"),  # barra às vezes vira espaço
    # CPF completo ou mascarado (•••.123.456-••, ***.123.456-**)
    "cpf": re.compile(rf"(?<![\w*•]){_M}{{3}}\.\s?{_M}{{3}}\.\s?{_M}{{3}}\s?-\s?{_M}{{2}}(?![\w*•])"),
    "cartao": re.compile(
        r"(?<![\w*•])\d{4}(?:[\s.-]?[\d*•X]{4}){2}[\s.-]?\d{4}\b"  # 16 posições, completo ou mascarado
        r"|(?<![A-Z])(?:[*•X]{2,}[\s.-]*)+\d{4}\b"  # **** 1234 / XXXX.1234
        r"|\b\d{4}[\s.-]*[*•X]{2,}(?![A-Z])"  # 1234 ****
        r"|\bFINAL\s*:?\s*\d{4}\b"  # "FINAL 1234"
        r"|\bCART[ÃA]O\s*(?:N[º°O.]?\s*)?:?\s*\d{4}\b"  # "CARTÃO 1234"
    ),
    "agencia_conta": re.compile(
        r"\bAG(?:[ÊE]NCIA|\.)?\s*:?\s*\d[\d-]*"
        r"|\b(?:CONTA|C/C|CC)\s*(?:CORRENTE\s*)?(?:N[º°O.]?\s*)?:?\s*\d[\d.-]*"
    ),
    "telefone": re.compile(r"(?:\+?55\s?)?(?:\(\d{2}\)|\b\d{2})\s?9?\d{4}[\s-]?\d{4}\b"),
    "cep": re.compile(r"\b\d{5}-?\d{3}\b"),
    "endereco": re.compile(
        r"\b(?:RUA|R\.|AV\.?|AVENIDA|TRAVESSA|TV\.|ALAMEDA|AL\.|RODOVIA|ROD\.|ESTRADA|PRA[ÇC]A|LARGO)"
        r"\s+[^\d,;]{2,}?,?\s*(?:N[º°O.]?\s*)?\d+"
    ),
    # qualquer sequência de 6+ dígitos (conta, documento, código, protocolo)
    "codigo_numerico": re.compile(r"\d(?:[.\-/]?\d){5,}"),
}

# Palavras que não identificam ninguém sozinhas e não entram nos pares de nome.
_CONECTIVOS = {"DE", "DA", "DO", "DAS", "DOS", "E", "D"}


def variantes_de_nome(nome: str) -> list[str]:
    """Formas de um nome que não podem aparecer na saída.

    Nome completo + cada par de tokens consecutivos (ignorando conectivos):
    "MARIA DA SILVA SOUZA" -> "MARIA DA SILVA SOUZA", "MARIA SILVA", "SILVA SOUZA".
    Tokens soltos não entram: um sobrenome sozinho aparece em nome de empresa
    e bloquearia linhas legítimas.
    """
    base = sem_acento(normaliza_texto(nome))
    tokens = [t for t in re.findall(r"[A-Z]+", base) if t not in _CONECTIVOS and len(t) > 1]
    variantes = {base} if base else set()
    variantes.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    return sorted(variantes, key=len, reverse=True)


def regex_de_nomes(nomes: list[str]) -> re.Pattern[str] | None:
    """Regex única (sobre texto sem acento) para todas as variantes dos nomes."""
    variantes: set[str] = set()
    for nome in nomes:
        variantes.update(variantes_de_nome(nome))
    if not variantes:
        return None
    partes = []
    for v in sorted(variantes, key=len, reverse=True):
        # entre tokens aceita espaço e conectivos ("MARIA SILVA" casa "MARIA DA SILVA")
        tokens = [re.escape(t) for t in v.split(" ")]
        partes.append(r"(?:\s+(?:(?:DE|DA|DO|DAS|DOS|E)\s+)*)".join(tokens))
    return re.compile(r"\b(?:" + "|".join(partes) + r")\b")


def _sem_acento_mesmo_tamanho(texto: str) -> str:
    """`sem_acento` que preserva posições (texto em NFC: 1 caractere -> 1 caractere)."""
    convertido = "".join(sem_acento(c)[:1] or c for c in texto)
    assert len(convertido) == len(texto)
    return convertido


def encontra(texto: str, nomes: re.Pattern[str] | None = None) -> list[str]:
    """Tipos de dado pessoal presentes no texto (só os nomes dos tipos, nunca o trecho)."""
    texto = normaliza_texto(texto)
    achados = [tipo for tipo, rx in PADROES.items() if rx.search(texto)]
    if nomes is not None and nomes.search(_sem_acento_mesmo_tamanho(texto)):
        achados.append("nome_titular")
    return achados


def remove(texto: str, nomes: re.Pattern[str] | None = None) -> str:
    """Apaga todos os trechos que casam com algum padrão (e os nomes dos titulares)."""
    texto = normaliza_texto(texto)
    for rx in PADROES.values():
        texto = rx.sub(" ", texto)
    if nomes is not None:
        base = _sem_acento_mesmo_tamanho(texto)
        # apaga do fim para o começo para não deslocar as posições
        for m in reversed(list(nomes.finditer(base))):
            texto = texto[: m.start()] + " " + texto[m.end():]
    return texto
