"""A arvore do NCM para navegacao de cima para baixo: Capitulo (2 digitos)
-> Posicao (4 digitos) -> Item (8 digitos, o unico valido para cadastro).

E como um classificador fiscal humano trabalha (Regras Gerais de
Interpretacao do Sistema Harmonizado: a classificacao e determinada primeiro
pelos textos das posicoes). A IA escolhe o capitulo vendo a lista COMPLETA
dos 96, depois a posicao vendo todas as posicoes do capitulo, e so no fim o
item -- em vez de depender de a busca por palavras ter achado o item certo
(o que falha quando o nome popular nao aparece no texto oficial: 'cadeira'
vs 'assentos', 'notebook' vs 'maquinas automaticas para processamento de
dados').

Tudo e carregado uma vez em memoria a partir de data/ncm.db (tabelas
capitulos e ncm_fts: ~10.500 itens), nao ha consulta ao banco por navegacao.
"""
import functools
import sqlite3

from src.config import NCM_DB_PATH
from src.ncm.lookup import titulo_posicao


@functools.lru_cache(maxsize=1)
def _arvore() -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[dict]]]:
    con = sqlite3.connect(NCM_DB_PATH)
    capitulos = dict(con.execute("SELECT capitulo, titulo FROM capitulos ORDER BY capitulo"))

    posicoes_por_capitulo: dict[str, list[str]] = {}
    itens_por_posicao: dict[str, list[dict]] = {}
    for codigo, proprio, ancestrais in con.execute(
        "SELECT codigo, texto_proprio, texto_ancestrais FROM ncm_fts ORDER BY codigo"
    ):
        digitos = codigo.replace(".", "")
        posicao = digitos[:4]
        if posicao not in itens_por_posicao:
            posicoes_por_capitulo.setdefault(digitos[:2], []).append(posicao)
            itens_por_posicao[posicao] = []
        itens_por_posicao[posicao].append(
            {
                "codigo": codigo,
                "descricao": proprio,
                "caminho_completo": f"{ancestrais} > {proprio}" if ancestrais else proprio,
            }
        )
    con.close()
    return capitulos, posicoes_por_capitulo, itens_por_posicao


def capitulos() -> dict[str, str]:
    """{'01': 'Animais vivos.', ...} -- os 96 capitulos."""
    return _arvore()[0]


def posicoes_do_capitulo(capitulo: str) -> list[str]:
    """Posicoes (4 digitos, sem ponto) do capitulo, em ordem numerica."""
    return _arvore()[1].get(capitulo, [])


def itens_da_posicao(posicao: str) -> list[dict]:
    """Itens de 8 digitos da posicao, com o caminho oficial completo."""
    return _arvore()[2].get(posicao.replace(".", ""), [])


def titulo_da_posicao(posicao: str) -> str:
    return titulo_posicao(posicao.replace(".", "")) or ""


def formatar_posicao(posicao: str) -> str:
    """'8708' -> '87.08'"""
    return f"{posicao[:2]}.{posicao[2:4]}"
