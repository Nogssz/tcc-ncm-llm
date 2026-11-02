"""kNN cruzado entre lojas: o conhecimento de uma loja serve para outra?
Sorteia até 1000 produtos de uma base e consulta só a outra. Também mede
cada base contra si mesma (80/20).

Uso: python scripts/avaliar_knn_cruzado.py loja_a loja_b
"""
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.avaliar_knn import medir  # noqa: E402
from src.ncm import conhecimento  # noqa: E402


def amostra(base, n=1000):
    con = sqlite3.connect(conhecimento.CAMINHO)
    linhas = con.execute("SELECT codigo, descricao, ncm FROM produtos WHERE base = ?", (base,)).fetchall()
    con.close()
    rng = random.Random(2026)
    rng.shuffle(linhas)
    return linhas


def main():
    a, b = sys.argv[1], sys.argv[2]
    for origem, alvo in [(a, b), (b, a)]:
        casos = [(d, {n}) for _, d, n in amostra(origem)[:1000]]
        print(f"{origem} consultando {alvo}:".ljust(34), medir(casos, lambda d: conhecimento.parecidos(d, 10, bases=[alvo])))
    for base in (a, b):
        linhas = amostra(base)
        corte = int(len(linhas) * 0.8)
        conhecimento.salvar_base(f"{base}_treino", linhas[:corte])
        casos = [(d, {n}) for _, d, n in linhas[corte:][:1000]]
        print(f"{base} 80/20:".ljust(34), medir(casos, lambda d: conhecimento.parecidos(d, 10, bases=[f"{base}_treino"])))
    linhas = amostra(b)
    casos = [(d, {n}) for _, d, n in linhas[int(len(linhas) * 0.8):][:1000]]  # só os 20% de teste
    print(f"{b} consultando {a}+{b}_treino:".ljust(34),
          medir(casos, lambda d: conhecimento.parecidos(d, 10, bases=[a, f"{b}_treino"])))


if __name__ == "__main__":
    main()
