"""Memoria de classificacoes: produtos do proprio ERP que ja tem NCM valido.

Numa oficina, um produto novo quase sempre se parece com algum ja
cadastrado ('PASTILHA FREIO DIANT GOL' vs 'PASTILHA FREIO TRAS PALIO'). O
NCM que o operador ja usou (ou aprovou no Streamlit -- a aprovacao grava o
NCM no ERP) e a melhor pista possivel, porque reflete como AQUELA empresa
classifica. Nao precisa de tabela nova: o proprio cadastro de produtos e a
memoria, e ela cresce sozinha com o uso.

Similaridade simples por palavras em comum (sem acento, sem palavras
genericas), suficiente para descricoes curtas de cadastro.
"""
import unicodedata

from src.db.firebird import run_select
from src.ncm.lookup import _tokens_busca, normalizar_codigo_erp, ncm_valido


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def _palavras(texto: str) -> set[str]:
    return set(_tokens_busca(_sem_acento(texto)))


def produtos_parecidos(
    descricao: str,
    excluir_codigo: int | None = None,
    ignorar_identicos: bool = False,
    limite: int = 3,
    similaridade_minima: float = 0.4,
) -> list[dict]:
    """Produtos ja classificados (mercadorias com NCM valido) mais parecidos
    com a descricao. ignorar_identicos existe para avaliacao: sem ele, um
    produto de teste que ja foi aprovado antes 'cola' a propria resposta."""
    alvo = _palavras(descricao)
    if not alvo:
        return []

    produtos = run_select(
        "SELECT CODIGO, DESCRICAO, NCM FROM PRODUTO WHERE SERVICO = 'N' AND NCM IS NOT NULL"
    )
    parecidos = []
    for p in produtos:
        if excluir_codigo is not None and p["CODIGO"] == excluir_codigo:
            continue
        texto = (p["DESCRICAO"] or "").strip()
        if ignorar_identicos and _sem_acento(texto).upper() == _sem_acento(descricao).strip().upper():
            continue
        if not ncm_valido(p["NCM"]):
            continue
        palavras = _palavras(texto)
        if not palavras:
            continue
        comuns = len(alvo & palavras)
        # Media de Jaccard (penaliza palavras sobrando) com sobreposicao
        # (uma descricao contida na outra: 'PARACHOQUE' em 'PARACHOQUE
        # DIANTEIRO GOL'). So Jaccard perdia esses casos, que sao os mais
        # comuns num cadastro (mesmo produto, com modelo/lado/medida).
        similaridade = 0.5 * comuns / len(alvo | palavras) + 0.5 * comuns / min(len(alvo), len(palavras))
        if similaridade >= similaridade_minima:
            parecidos.append(
                {
                    "codigo_produto": p["CODIGO"],
                    "descricao": texto,
                    "ncm": normalizar_codigo_erp(p["NCM"]),
                    "similaridade": round(similaridade, 2),
                }
            )
    parecidos.sort(key=lambda p: p["similaridade"], reverse=True)
    return parecidos[:limite]
