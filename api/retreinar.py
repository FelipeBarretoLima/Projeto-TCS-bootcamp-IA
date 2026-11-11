"""Força um retreino do classificador agora, sem esperar as 15 correções.

    python -m api.retreinar             retreina e mostra o resultado
    python -m api.retreinar --historico  só mostra os últimos retreinos
"""

import sys

from .servicos import retreino


def main(argv: list[str]) -> int:
    if argv == ["--historico"]:
        with retreino.abre_banco() as db:
            for t in db.treinos():
                print(f"{t['iniciado_em']:%d/%m/%Y %H:%M}  {t['status']:7} correções={t['correcoes']:4} "
                      f"acerto nas correções: {t['acerto_correcoes_antes']}% -> {t['acerto_correcoes_depois']}% "
                      f"| base {t['acerto_base_depois']}%  {t['mensagem']}")
        return 0
    registro = retreino.executa_retreino()
    if registro is None:
        print("já há um retreino rodando; tente de novo em instantes")
        return 1
    print(registro)
    return 0 if registro["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
