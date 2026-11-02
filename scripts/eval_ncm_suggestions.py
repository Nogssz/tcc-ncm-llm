"""Avaliacao da camada de busca (sem LLM) contra um conjunto de casos com
gabarito verificado manualmente na tabela oficial. Mede a "taxa de deteccao"
citada na metodologia do TCC: o codigo correto aparece entre os candidatos
que a ferramenta buscar_ncm_por_descricao devolveria pro agente (limit=15,
o mesmo usado em producao)?

Cada caso documenta se e um cenario "facil" (termo bate literalmente com o
texto oficial) ou um gap conhecido (sinonimo oficial vs coloquial, termo
generico demais, ambiguidade de palavra) -- isso NAO e so uma lista de
sucessos, e um retrato honesto de onde a busca lexical (sem embeddings)
tem limite real.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ncm.lookup import search_by_description

CASOS = [
    ("vela de ignição", ["8511.10.00"], "facil"),
    ("amortecedor", ["8708.80.00"], "facil"),
    ("retrovisor", ["7009.10.00"], "facil"),
    ("radiador para automóvel", ["8708.91.00"], "facil"),
    ("para-choque", ["8708.10.00"], "facil"),
    ("PARACHOQUE", ["8708.10.00"], "grudado sem hifen (achado real do usuario)"),
    ("farol", ["8512.20.11"], "plural irregular -al/-ol"),
    ("embreagem", ["8708.93.00"], "plural irregular -agem/-agens"),
    ("pneu novo para carro de passeio", ["4011.10.00"], "sinonimo parcial (carro/passeio)"),
    ("correia dentada", ["4010.35.00", "4010.36.00"], "precisa achar a subcategoria certa"),
    ("pastilha de freio", ["8708.30.19", "8708.30.11", "8708.30.90"], "GAP: 'pastilha' colide com ceramica"),
    ("disco de freio", ["8708.30.19", "8708.30.11", "8708.30.90"], "GAP: termo generico 'freio' dilui ranking"),
    ("óleo lubrificante para motor", ["2710.19.31", "2710.19.32"], "GAP: termo generico dilui ranking"),
    ("bateria de chumbo para automóvel", ["8507.10.10", "8507.10.90"], "GAP: sinonimo oficial e 'acumulador', nao 'bateria'"),
    ("AZULEIJO DE BANHEIRO AZUL", ["6907.23.00", "6907.21.00", "6907.22.00"], "sinonimo puro (azulejo/ladrilho) + erro de digitacao real do usuario"),
]


def main():
    limit = 25
    acertos, total = 0, len(CASOS)
    print(f"Avaliando {total} casos, limit={limit} (mesmo valor usado pela ferramenta em producao)\n")

    for descricao, esperados, nota in CASOS:
        resultados = search_by_description(descricao, limit=limit)
        codigos = [r.get("codigo", "") for r in resultados]
        posicao = None
        codigo_achado = None
        for esperado in esperados:
            if esperado in codigos:
                posicao = codigos.index(esperado) + 1
                codigo_achado = esperado
                break

        status = f"OK  (pos {posicao})" if posicao else "FALHOU"
        if posicao:
            acertos += 1
        print(f"[{status:>12}] {descricao!r}")
        print(f"             esperado: {esperados}  |  nota: {nota}")
        if not posicao:
            print(f"             top3 retornado: {codigos[:3]}")
        print()

    print(f"Taxa de deteccao: {acertos}/{total} = {100*acertos/total:.1f}%")


def main_llm(nome_modelo: str | None = None):
    """Taxa de acerto de ponta a ponta: busca + escolha do LLM (o que o
    operador realmente ve no Streamlit). Mais lento -- duas chamadas ao
    Ollama por caso. Uso: --llm [--modelo qwen2.5:7b]"""
    import time

    from src.agent.ncm_suggester import build_ncm_agent, sugerir_ncm

    modelo = build_ncm_agent(nome_modelo)
    top1, top3, erros_infra, total = 0, 0, 0, len(CASOS)
    print(f"Avaliando {total} casos com o LLM ({modelo.model})\n")

    for descricao, esperados, nota in CASOS:
        inicio = time.time()
        try:
            sugestao = sugerir_ncm(modelo, descricao)
        except Exception as e:
            erros_infra += 1
            print(f"[ ERRO INFRA ] {descricao!r}: {type(e).__name__}: {str(e)[:120]}\n")
            continue
        segundos = time.time() - inicio
        codigos = [o.codigo for o in sugestao.opcoes]
        posicao = next((codigos.index(e) + 1 for e in esperados if e in codigos), None)
        top1 += posicao == 1
        top3 += posicao is not None
        status = f"OK {posicao}o" if posicao else "ERROU"
        print(f"[{status:>12}] {descricao!r} ({segundos:.0f}s)")
        print(f"             opcoes: {codigos}  |  esperado: {esperados}")
        print()

    avaliados = total - erros_infra
    print(f"Acerto em 1o lugar: {top1}/{avaliados} = {100*top1/max(avaliados, 1):.1f}%")
    print(f"Acerto entre as 3 opcoes: {top3}/{avaliados} = {100*top3/max(avaliados, 1):.1f}%"
          f"  (falhas de infraestrutura do Ollama, fora da conta: {erros_infra})")


if __name__ == "__main__":
    if "--llm" in sys.argv:
        nome = sys.argv[sys.argv.index("--modelo") + 1] if "--modelo" in sys.argv else None
        main_llm(nome)
    else:
        main()
