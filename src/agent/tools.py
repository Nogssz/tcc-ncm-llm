"""Ferramentas que o agente LangChain pode chamar. Cada uma devolve apenas o
resultado pontual da consulta -- nunca uma tabela inteira -- para manter o
prompt pequeno (essa foi a causa dos erros de "prompt muito grande" ao
tentar colar a tabela NCM inteira em uma conversa)."""
from langchain_core.tools import tool

from src.db.firebird import run_select
from src.ncm.lookup import (
    classificar_capitulo,
    listar_subcodigos,
    lookup_by_code,
    search_by_description,
)


@tool
def consultar_cadastro(sql_select: str) -> list[dict]:
    """Executa uma consulta SELECT no banco do ERP (Firebird) para
    investigar um cadastro de cliente/produto. Use para checar os campos
    fiscais atuais (NCM, CST, CFOP, Indicador de Contribuinte, Inscricao
    Estadual) antes de propor uma correcao. Somente leitura."""
    return run_select(sql_select)


@tool
def consultar_ncm_por_codigo(codigo: str) -> dict | str:
    """Consulta a descricao oficial de um codigo NCM especifico na tabela
    vigente da Receita Federal. Use para validar se o NCM cadastrado no
    produto esta correto e atualizado."""
    resultado = lookup_by_code(codigo)
    if resultado is None:
        return f"Codigo NCM '{codigo}' nao encontrado na tabela vigente."
    return resultado


@tool
def buscar_ncm_por_descricao(descricao_produto: str) -> list[dict]:
    """Busca o codigo NCM a partir da descricao do produto. Passe a
    descricao completa e rica em detalhes (tipo de peca, aplicacao, veiculo
    -- ex.: 'pneu novo para automovel de passageiro'), nao so uma
    palavra-chave isolada -- a busca ja considera o contexto hierarquico
    completo (capitulo/posicao/subposicao) de cada item, entao uma frase
    inteira tende a achar o codigo final de 8 digitos direto, sem precisar
    de buscas adicionais. Pode retornar mais de um candidato plausivel: o
    primeiro nem sempre e o correto (ex.: a busca nao distingue sozinha
    'pneu novo' de 'pneu recauchutado' se a palavra distintiva nao estiver
    na descricao) -- compare o 'caminho_completo' de cada opcao com o
    produto antes de decidir."""
    resultados = search_by_description(descricao_produto)
    if not resultados:
        return [{"aviso": f"Nenhum NCM encontrado para '{descricao_produto}'."}]
    return resultados


@tool
def listar_subcodigos_ncm(prefixo: str) -> list[dict]:
    """Lista os codigos mais especificos dentro de um codigo NCM parcial
    (ex.: '4011' ou '40.11'). Use quando buscar_ncm_por_descricao devolver
    um codigo de posicao/subposicao (menos de 8 digitos) -- o cadastro do
    produto exige sempre o codigo final de 8 digitos (item), nunca um
    codigo de categoria. Va descendo ate achar o item que melhor descreve
    o produto."""
    resultados = listar_subcodigos(prefixo)
    if not resultados:
        return [{"aviso": f"Nenhum subcodigo encontrado para '{prefixo}'."}]
    return resultados


@tool
def classificar_capitulo_ncm(codigo: str) -> dict | str:
    """Identifica o Capitulo (categoria macro) de um codigo NCM a partir dos
    2 primeiros digitos -- ex.: 87 = veiculos automoveis e suas partes. Use
    para confirmar rapidamente se um NCM cadastrado condiz com o tipo de
    produto (ex.: uma peca automotiva deve cair no capitulo 87 ou 40 pneus)."""
    resultado = classificar_capitulo(codigo)
    if resultado is None:
        return f"Nao foi possivel identificar o capitulo NCM a partir de '{codigo}'."
    return resultado


DIAGNOSTIC_TOOLS = [
    consultar_cadastro,
    consultar_ncm_por_codigo,
    buscar_ncm_por_descricao,
    listar_subcodigos_ncm,
    classificar_capitulo_ncm,
]
