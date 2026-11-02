"""Deteccao de produtos com NCM invalido no ERP Lux Auto.

So considera produtos onde SERVICO = 'N' (mercadoria). Quando SERVICO = 'S'
o campo NCM do ERP na verdade guarda um codigo NBS (Nomenclatura Brasileira
de Servicos), um sistema de classificacao diferente -- validar isso contra
a tabela de NCM daria falso positivo.
"""
from src.db.firebird import run_select
from src.ncm.lookup import ncm_valido


def listar_produtos_ncm_invalido() -> list[dict]:
    """Retorna produtos (mercadorias) cujo NCM esta vazio ou nao existe na
    tabela oficial vigente. Consulta pura, sem IA -- serve de gatilho para
    depois acionar o agente e sugerir o NCM correto pela descricao."""
    produtos = run_select(
        "SELECT CODIGO, DESCRICAO, NCM FROM PRODUTO WHERE SERVICO = 'N'"
    )
    return [p for p in produtos if not ncm_valido(p["NCM"])]


def listar_produtos_ncm_valido() -> list[dict]:
    """Mercadorias com NCM válido na tabela -- candidatas à verificação de NCM
    errado (src.agent.ncm_verificador). Os cadastrados mais recentemente vêm
    primeiro: numa base grande, o worker verifica primeiro o que acabou de
    ser cadastrado e vai cobrindo o restante aos poucos."""
    produtos = run_select(
        "SELECT CODIGO, DESCRICAO, NCM FROM PRODUTO WHERE SERVICO = 'N' "
        "ORDER BY DT_CADASTRO DESC NULLS LAST, CODIGO DESC"
    )
    return [p for p in produtos if ncm_valido(p["NCM"]) and (p["DESCRICAO"] or "").strip()]
