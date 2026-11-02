"""Mede só a busca (sem chamar o modelo): o código certo está entre os
candidatos? Reaproveita as interpretações técnicas gravadas numa avaliação
anterior (scripts/avaliar.py), então dá para comparar variações da busca em
segundos. Uso: python scripts/recall_busca.py data/avaliacoes/<arquivo>.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.ncm_suggester import _fundir_rankings  # noqa: E402
from src.ncm.abreviacoes import expandir  # noqa: E402
from src.ncm.lookup import search_by_description  # noqa: E402
from src.ncm.radicais import search_radicais  # noqa: E402


def lexical(t, n):
    return [c for c in search_by_description(t, limit=n) if "codigo" in c]


VARIANTES = {
    "atual (40)": lambda d, i: _fundir_rankings([lexical(d, 40), lexical(i, 40)], 40),
    "atual (60)": lambda d, i: _fundir_rankings([lexical(d, 60), lexical(i, 60)], 60),
    "+radicais (40)": lambda d, i: _fundir_rankings(
        [lexical(d, 40), lexical(i, 40), search_radicais(d, 40), search_radicais(i, 40)], 40),
    "+radicais (60)": lambda d, i: _fundir_rankings(
        [lexical(d, 60), lexical(i, 60), search_radicais(d, 60), search_radicais(i, 60)], 60),
    "+radicais so interp. (40)": lambda d, i: _fundir_rankings(
        [lexical(d, 40), lexical(i, 40), search_radicais(i, 40)], 40),
}


def main():
    dados = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    casos = [c for c in dados["casos"] if "erro" not in c]
    for nome, f in VARIANTES.items():
        achou = 0
        for c in casos:
            d = expandir(c["descricao"])
            i = c.get("interpretacao") or d
            cods = {x["codigo"] for x in f(d, i)}
            achou += any(e in cods for e in c["esperados"])
        print(f"{nome:28} {achou}/{len(casos)} = {100 * achou / len(casos):.1f}%")


if __name__ == "__main__":
    main()
