"""Avalia a base de conhecimento sozinha (kNN, sem modelo de linguagem).

1. Dentro de uma base de cliente: sorteia 20% dos produtos como teste e
   consulta só os outros 80% (base "<nome>_treino"). Mede também a versão
   sem vizinhos de descrição idêntica, que é o cenário mais difícil.
2. Nos conjuntos curados (dev, dev2, teste): consulta a base inteira.

Uso: python scripts/avaliar_knn.py loja_a
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ncm import conhecimento  # noqa: E402


def medir(casos, consulta, k=10):
    top1 = top3 = 0
    for descricao, esperados in casos:
        votos = [n for n, _ in conhecimento.votar(consulta(descricao), k)]
        top1 += bool(votos) and votos[0] in esperados
        top3 += any(v in esperados for v in votos[:3])
    n = len(casos)
    return f"1º lugar {100 * top1 / n:.1f}% | top-3 {100 * top3 / n:.1f}% (n={n})"


def main():
    nome = sys.argv[1]
    import sqlite3

    con = sqlite3.connect(conhecimento.CAMINHO)
    linhas = con.execute("SELECT codigo, descricao, ncm FROM produtos WHERE base = ?", (nome,)).fetchall()
    con.close()
    rng = random.Random(2026)
    rng.shuffle(linhas)
    corte = int(len(linhas) * 0.8)
    treino, teste = linhas[:corte], linhas[corte:]
    conhecimento.salvar_base(f"{nome}_treino", treino)

    print(f"== {nome}: {len(treino)} para consulta, {len(teste)} para teste")
    casos = [(d, {n}) for _, d, n in teste]
    print("  kNN (vizinhos dos 80%):          ", medir(casos, lambda d: conhecimento.parecidos(d, 10, bases=[f"{nome}_treino"])))
    limpas = {conhecimento.limpar_descricao(d).upper() for _, d, _ in treino}
    sem_ident = [(d, s) for d, s in casos if conhecimento.limpar_descricao(d).upper() not in limpas]
    print("  só itens sem descrição idêntica: ", medir(sem_ident, lambda d: conhecimento.parecidos(d, 10, bases=[f"{nome}_treino"])))

    from scripts.avaliar import DEV
    from scripts.conjuntos_v2 import DEV2
    from scripts.seed_produtos_teste import PRODUTOS

    for rotulo, conj in [("dev", DEV), ("dev2", DEV2), ("teste (33)", PRODUTOS)]:
        casos = [(d, set(e)) for d, e, _ in conj]
        print(f"  {rotulo:32}", medir(casos, lambda d: conhecimento.parecidos(d, 10, bases=[nome])))
    auto = [(d, set(e)) for d, e, s in DEV + DEV2 + PRODUTOS if s == "automotivo"]
    print(f"  {'só automotivos (dev+dev2+teste)':32}", medir(auto, lambda d: conhecimento.parecidos(d, 10, bases=[nome])))


if __name__ == "__main__":
    main()
