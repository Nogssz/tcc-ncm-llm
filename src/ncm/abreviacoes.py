"""Expansão de abreviações comuns em cadastros de produtos de ERP,
principalmente de autopeças ("PIVO SUSP INF" -> "PIVO SUSPENSAO INFERIOR").

Sem isso, o modelo de linguagem interpreta errado (no conjunto DEV2,
"PIVO SUSP INF" virou "medicamento para infusão") e a busca não encontra
nada. A lista reúne abreviações usuais do ramo; não foi montada a partir
dos produtos de avaliação. Só palavras inteiras são trocadas, e uma
abreviação só é expandida se não for, ela mesma, uma palavra da tabela NCM
que faça sentido sozinha.
"""
import re

ABREVIACOES = {
    # posição / lado
    "DIANT": "DIANTEIRO", "DIANTEIR": "DIANTEIRO",
    "TRAS": "TRASEIRO", "TRAZ": "TRASEIRO", "TRAS.": "TRASEIRO",
    "SUP": "SUPERIOR", "INF": "INFERIOR", "ESQ": "ESQUERDO", "DIR": "DIREITO",
    "LD": "LADO DIREITO","INT": "INTERNO", "EXT": "EXTERNO",
    # peças e sistemas
    "SUSP": "SUSPENSAO", "AMORT": "AMORTECEDOR", "AMORTEC": "AMORTECEDOR",
    "ROLAM": "ROLAMENTO", "ROL": "ROLAMENTO", "CIL": "CILINDRO", "MANG": "MANGUEIRA",
    "EMBR": "EMBREAGEM", "EMBREAG": "EMBREAGEM", "ESCAP": "ESCAPAMENTO",
    "RADIAD": "RADIADOR", "RESERV": "RESERVATORIO", "REFRIG": "REFRIGERACAO",
    "COND": "CONDICIONADO", "AR COND": "AR CONDICIONADO", "COMB": "COMBUSTIVEL",
    "IGN": "IGNICAO", "ALTERN": "ALTERNADOR", "ARRANQ": "ARRANQUE", "PARTIDA": "PARTIDA",
    "DIRECAO": "DIRECAO", "DIR HIDR": "DIRECAO HIDRAULICA", "HIDR": "HIDRAULICO",
    "PAST": "PASTILHA", "PASTILH": "PASTILHA", "TAMB": "TAMBOR", "VIRAB": "VIRABREQUIM",
    "CABEC": "CABECOTE", "JTA": "JUNTA", "RET": "RETENTOR", "RETENT": "RETENTOR",
    "PARAF": "PARAFUSO", "ARRUEL": "ARRUELA", "ABRAC": "ABRACADEIRA",
    "CORR": "CORREIA", "TENS": "TENSOR", "BOMB": "BOMBA", "VALV": "VALVULA",
    "TERM": "TERMINAL", "ESTAB": "ESTABILIZADORA", "BARR": "BARRA",
    "LAMP": "LAMPADA", "FAR": "FAROL", "LANT": "LANTERNA", "RETROV": "RETROVISOR",
    "PARABR": "PARABRISA", "PCHOQUE": "PARACHOQUE", "P/CHOQUE": "PARACHOQUE",
    "P/BRISA": "PARABRISA", "P/LAMA": "PARALAMA",
    "ELETR": "ELETRICO", "ELET": "ELETRICO", "AUT": "AUTOMOTIVO", "AUTOM": "AUTOMOTIVO",
    "MOT": "MOTOR", "TRANSM": "TRANSMISSAO", "CX": "CAIXA", "CAMB": "CAMBIO",
    "PNEU": "PNEU", "JG": "JOGO", "KIT": "KIT", "PCS": "PECAS",
    "UN": "UNIDADE", "UNID": "UNIDADE", "CJ": "CONJUNTO", "CONJ": "CONJUNTO",
    # outros setores
    "DESOD": "DESODORANTE",
    "DET": "DETERGENTE", "AMAC": "AMACIANTE", "INFANT": "INFANTIL",
    "MASC": "MASCULINO", "FEM": "FEMININO", "ALG": "ALGODAO",
}

# Ordena da mais longa para a mais curta para "AR COND" vencer "COND".
_PADROES = [
    (re.compile(r"(?<![\w/])" + re.escape(abrev) + r"(?![\w/])"), completo)
    for abrev, completo in sorted(ABREVIACOES.items(), key=lambda kv: -len(kv[0]))
    if abrev != completo
]


def expandir(descricao: str) -> str:
    """Devolve a descrição com as abreviações expandidas (em maiúsculas)."""
    texto = descricao.upper()
    for padrao, completo in _PADROES:
        texto = padrao.sub(completo, texto)
    return re.sub(r"\s+", " ", texto).strip()
