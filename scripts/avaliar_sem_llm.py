"""Linhas de base SEM modelo de linguagem, nos mesmos conjuntos de
scripts/avaliar.py. Servem para isolar a contribuição do LLM:

- busca: BM25 (FTS5) + sinônimos, pela descrição original e pela descrição
  com abreviações expandidas, fundidas por RRF -- a mesma busca que entrega
  candidatos ao modelo, mas sem a descrição técnica que o modelo gera;
- knn: voto dos produtos parecidos da base de conhecimento (só a Loja A);
- knn+busca: o voto do kNN e, para completar 3 opções (ou quando a base não
  acha nada), os primeiros da busca.

Uso: python scripts/avaliar_sem_llm.py --conjunto devtudo
     python scripts/avaliar_sem_llm.py --conjunto teste2 --final
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.avaliar import _conjunto  # noqa: E402
from src.agent.ncm_suggester import _fundir_rankings  # noqa: E402
from src.ncm import conhecimento  # noqa: E402
from src.ncm.abreviacoes import expandir  # noqa: E402
from src.ncm.lookup import search_by_description  # noqa: E402


def busca(descricao: str, n: int = 40) -> list[str]:
    listas = [[c for c in search_by_description(t, limit=n) if "codigo" in c]
              for t in dict.fromkeys([descricao, expandir(descricao)])]
    return [c["codigo"] for c in _fundir_rankings(listas, n)]


def knn(descricao: str) -> list[str]:
    return [n for n, _ in conhecimento.votar(conhecimento.parecidos(descricao, 10, bases=["loja_a"]))]


def knn_mais_busca(descricao: str) -> list[str]:
    return list(dict.fromkeys(knn(descricao)[:3] + busca(descricao)))


METODOS = {"busca (BM25+RRF)": busca, "knn (base Loja A)": knn, "knn + busca": knn_mais_busca}


def main():
    nome = sys.argv[sys.argv.index("--conjunto") + 1] if "--conjunto" in sys.argv else "devtudo"
    casos = _conjunto(nome)
    resultado = {}
    for metodo, f in METODOS.items():
        top1 = top3 = 0
        inicio = time.time()
        por_caso = []
        for descricao, esperados, grupo in casos:
            ops = f(descricao)
            a1, a3 = ops[:1] and ops[0] in esperados, any(e in ops[:3] for e in esperados)
            top1 += bool(a1)
            top3 += bool(a3)
            por_caso.append({"descricao": descricao, "esperados": esperados, "setor": grupo, "opcoes": ops[:3]})
        n = len(casos)
        resultado[metodo] = {"top1": round(100 * top1 / n, 1), "top3": round(100 * top3 / n, 1),
                             "ms_por_caso": round(1000 * (time.time() - inicio) / n), "casos": por_caso}
        print(f"{metodo:20} top-1 {top1}/{n} = {100 * top1 / n:.1f}%   top-3 {top3}/{n} = {100 * top3 / n:.1f}%"
              f"   ({resultado[metodo]['ms_por_caso']} ms/caso)")
    saida = Path("data/avaliacoes") / f"sem_llm_{nome}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Salvo em {saida}")


if __name__ == "__main__":
    main()
