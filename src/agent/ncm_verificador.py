"""Detecção de NCM errado: o código existe na tabela, mas não corresponde ao
produto (ex.: um filtro de ar cadastrado com o NCM de um pneu, porque o
operador copiou outro produto para criar o novo).

Diferente do NCM vazio ou inexistente, isso não se resolve com uma consulta
à tabela: é preciso comparar o que o produto é com o que o código descreve.
O verificador combina dois tipos de evidência:

1. A sugestão independente (src.agent.ncm_suggester.sugerir_ncm): se o
   código cadastrado está entre as 3 opções, ou na mesma posição/capítulo.
2. Duas perguntas curtas ao modelo, com resposta restrita por esquema:
   - absoluta: "este código corresponde a este produto?";
   - comparativa: entre o código cadastrado e as opções sugeridas (em ordem
     embaralhada, para o modelo não favorecer uma posição), qual descreve
     melhor o produto.

A regra que junta esses sinais (decidir) foi escolhida no conjunto de
desenvolvimento DEV2 e medida uma única vez no TESTE2.
"""
import hashlib
import random

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from src.agent.ncm_suggester import (
    NcmSuggestion,
    _curto,
    _latino,
    _perguntar,
    _traduzir_referencias,
    sugerir_ncm,
)
from src.ncm import hierarquia
from src.ncm.lookup import ncm_valido, normalizar_codigo_erp

PROMPT_VERIFICACAO = """Voce e um especialista em classificacao fiscal de \
mercadorias na NCM (Nomenclatura Comum do Mercosul). Voce revisa cadastros \
de produtos de um ERP de oficina mecanica para encontrar NCM errado.

A descricao do produto vem como foi digitada no cadastro: pode estar \
abreviada ou com erro de digitacao. Julgue pelo que o produto E (material, \
funcao, aplicacao), nao por palavras soltas.

Responda SEMPRE em portugues do Brasil, nunca em outro idioma.
"""


class VerificacaoNcm(BaseModel):
    status: str = Field(description="ok | suspeito | invalido")
    motivo: str = ""
    ncm_cadastrado: str | None = None
    sugestao: NcmSuggestion | None = None
    # sinais, guardados para avaliação e para explicar a decisão na tela
    em_top3: bool = False
    mesma_posicao: bool = False
    mesmo_capitulo: bool = False
    veredito_absoluto: str | None = None
    preferido_comparacao: str | None = None
    # base de conhecimento: NCM mais votado pelos parecidos de outras lojas,
    # o peso desse voto e o peso que o NCM cadastrado recebeu
    conhecimento_top: str | None = None
    conhecimento_peso_top: float = 0.0
    conhecimento_peso_cadastrado: float = 0.0


def caminho_legivel(codigo: str, maximo_por_nivel: int = 160) -> str:
    item = next((c for c in hierarquia.itens_da_posicao(codigo.replace(".", "")[:4]) if c["codigo"] == codigo), None)
    if item is None:
        return codigo
    partes = []
    for p in item["caminho_completo"].split(" > "):
        curto = _traduzir_referencias(_curto(p, maximo_por_nivel))
        if not partes or partes[-1] != curto:
            partes.append(curto)
    return " > ".join(partes)


def _cabecalho_produto(descricao: str, sugestao: NcmSuggestion | None) -> str:
    texto = f'Produto cadastrado no ERP: "{descricao}"'
    if sugestao and sugestao.interpretacao:
        texto += f"\nInterpretacao tecnica: {sugestao.interpretacao}"
    if sugestao and sugestao.caracteristicas:
        texto += f"\nCaracteristicas: {sugestao.caracteristicas}"
    if sugestao and sugestao.conhecimento:
        exemplos = "; ".join(f"'{v['descricao'][:50]}' -> {v['ncm']}" for v in sugestao.conhecimento[:5])
        texto += f"\nProdutos parecidos ja classificados por outras lojas: {exemplos}"
    return texto


def veredito_absoluto(modelo: ChatOllama, descricao: str, ncm: str, sugestao: NcmSuggestion | None) -> str | None:
    esquema = {
        "type": "object",
        "properties": {
            "analise": {"type": "string"},
            "veredito": {"type": "string", "enum": ["compativel", "incompativel", "duvida"]},
        },
        "required": ["analise", "veredito"],
    }
    pergunta = (
        f"{_cabecalho_produto(descricao, sugestao)}\n\n"
        f"NCM cadastrado: {ncm}\nTexto oficial: {caminho_legivel(ncm)}\n\n"
        "Esse NCM corresponde a esse produto? Responda 'compativel' se o texto "
        "oficial descreve este tipo de produto; 'incompativel' se descreve outro "
        "tipo de produto (outro material, outra funcao ou outra aplicacao); "
        "'duvida' se depender de uma informacao que a descricao nao tem."
    )
    resposta = _perguntar(modelo, esquema, pergunta, PROMPT_VERIFICACAO) or _perguntar(
        modelo, esquema, pergunta, PROMPT_VERIFICACAO
    )
    return (resposta or {}).get("veredito")


def preferido_comparacao(modelo: ChatOllama, descricao: str, ncm: str, sugestao: NcmSuggestion) -> str | None:
    """Devolve o código que o modelo considera o melhor entre o cadastrado e
    as opções sugeridas, ou 'empate'."""
    codigos = [ncm] + [o.codigo for o in sugestao.opcoes if o.codigo != ncm]
    # Ordem embaralhada, mas reprodutível para o mesmo produto/código.
    rng = random.Random(int(hashlib.md5(f"{descricao}|{ncm}".encode()).hexdigest(), 16))
    rng.shuffle(codigos)
    letras = "ABCD"[: len(codigos)]
    por_letra = dict(zip(letras, codigos))
    esquema = {
        "type": "object",
        "properties": {
            "analise": {"type": "string"},
            "melhor": {"type": "string", "enum": list(letras) + ["empate"]},
        },
        "required": ["analise", "melhor"],
    }
    opcoes = "\n".join(f"{letra}) {cod}: {caminho_legivel(cod)}" for letra, cod in por_letra.items())
    pergunta = (
        f"{_cabecalho_produto(descricao, sugestao)}\n\nCodigos NCM possiveis:\n{opcoes}\n\n"
        "Qual codigo descreve melhor esse produto? Responda a letra. Use 'empate' "
        "somente se dois ou mais forem igualmente corretos para essa descricao."
    )
    resposta = _perguntar(modelo, esquema, pergunta, PROMPT_VERIFICACAO) or _perguntar(
        modelo, esquema, pergunta, PROMPT_VERIFICACAO
    )
    melhor = (resposta or {}).get("melhor")
    if melhor == "empate":
        return "empate"
    return por_letra.get(melhor)


def decidir(v: VerificacaoNcm) -> tuple[bool, str]:
    """Regra final (suspeito?, motivo). Escolhida no DEV2 -- ver docs/diario_noturno.md."""
    if v.em_top3:
        return False, "O NCM cadastrado está entre as opções que a IA sugere para este produto."
    if v.veredito_absoluto == "incompativel":
        return True, "A IA considera que o texto oficial deste NCM descreve outro tipo de produto."
    # A antiga 3ª condição (outro capítulo + comparação contra) foi retirada em
    # 01/11: no DEV2 só acrescentava alarmes falsos (85,6% -> 86,6% sem ela).
    return False, "Não há indício forte de erro."


def verificar_ncm(
    modelo: ChatOllama,
    descricao: str,
    ncm_bruto: str | None,
    sugestao: NcmSuggestion | None = None,
    codigo_produto: int | None = None,
    ignorar_identicos: bool = False,
    comparar: bool = True,
    sempre_perguntar: bool = False,
) -> VerificacaoNcm:
    """sempre_perguntar: faz as perguntas de verificação mesmo quando o NCM
    cadastrado está entre as sugestões (só para avaliação das regras)."""
    if not ncm_valido(ncm_bruto):
        return VerificacaoNcm(status="invalido", motivo="NCM vazio, malformado ou inexistente na tabela vigente.")
    ncm = normalizar_codigo_erp(ncm_bruto)
    if sugestao is None:
        sugestao = sugerir_ncm(modelo, descricao, codigo_produto=codigo_produto, ignorar_identicos=ignorar_identicos)
    sugeridos = [o.codigo for o in sugestao.opcoes]
    v = VerificacaoNcm(
        status="ok",
        ncm_cadastrado=ncm,
        sugestao=sugestao,
        em_top3=ncm in sugeridos,
        mesma_posicao=ncm[:4] in {c[:4] for c in sugeridos},
        mesmo_capitulo=bool(sugestao.capitulos) and ncm[:2] == sugestao.capitulos[0],
    )
    if sugestao.votos_conhecimento:
        votos = dict(sugestao.votos_conhecimento)
        v.conhecimento_top, v.conhecimento_peso_top = sugestao.votos_conhecimento[0]
        v.conhecimento_peso_cadastrado = votos.get(ncm, 0.0)
    if sempre_perguntar or not v.em_top3:
        v.veredito_absoluto = veredito_absoluto(modelo, descricao, ncm, sugestao)
        if comparar and sugestao.opcoes:
            v.preferido_comparacao = preferido_comparacao(modelo, descricao, ncm, sugestao)
    suspeito, motivo = decidir(v)
    v.status = "suspeito" if suspeito else "ok"
    v.motivo = _latino(motivo) or motivo
    return v
