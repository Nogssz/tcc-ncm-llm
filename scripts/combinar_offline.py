"""Testa, sem rodar o modelo, regras para combinar as opções do LLM (de uma
avaliação gravada) com os votos da base de conhecimento (kNN).

Uso: python scripts/combinar_offline.py data/avaliacoes/<devtudo...>.json loja_a
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ncm import conhecimento  # noqa: E402


def mesclar(*listas, n=3):
    saida = []
    for lista in listas:
        for c in lista:
            if c not in saida:
                saida.append(c)
    return saida[:n]


def main():
    dados = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    base = sys.argv[2]
    casos = [c for c in dados["casos"] if "erro" not in c]
    knn = {c["descricao"]: conhecimento.parecidos(c["descricao"], 10, bases=[base]) for c in casos}

    def regra(limiar_voto, limiar_pont):
        def f(c):
            viz = knn[c["descricao"]]
            votos = conhecimento.votar(viz)
            confiante = votos and votos[0][1] >= limiar_voto and viz[0]["pontuacao"] >= limiar_pont
            kn = [n for n, _ in votos[:2]] if confiante else []
            return mesclar(kn, c["opcoes"])
        return f

    regras = {"so LLM": lambda c: c["opcoes"][:3],
              "so kNN": lambda c: [n for n, _ in conhecimento.votar(knn[c["descricao"]])][:3]}
    for lv in (0.0, 1.0, 1.5, 2.0):
        for lp in (0.0, 4.0, 8.0):
            regras[f"kNN 1o se voto>={lv} e pont>={lp}"] = regra(lv, lp)
    for nome, f in regras.items():
        t1 = t3 = 0
        for c in casos:
            ops = f(c)
            t1 += bool(ops) and ops[0] in c["esperados"]
            t3 += any(o in c["esperados"] for o in ops[:3])
        print(f"{nome:36} 1º {100 * t1 / len(casos):5.1f}% | top-3 {100 * t3 / len(casos):5.1f}%")


if __name__ == "__main__":
    main()
