"""Consulta pontual a tabela NCM (data/ncm.db), gerada por
scripts/extract_ncm.py + scripts/repair_ncm.py a partir do PDF oficial.

Isso implementa a parte de RAG do agente (secao 2.6/2.7 do TCC): o LLM nunca
recebe a tabela inteira no prompt, apenas o resultado pontual da consulta
pelo codigo ou palavra-chave que precisa checar.
"""
import functools
import re
import sqlite3

from src.config import NCM_DB_PATH
from src.ncm.synonyms import obter_sinonimos

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Palavras que aparecem em milhares de itens e nao dizem O QUE o produto e.
# Numa busca com OR, elas trazem centenas de candidatos irrelevantes e
# empurram o certo pra fora da lista (visto com descricoes como 'tinta ...
# em embalagem de 18 litros'). 'para' fica de fora de proposito: faz parte
# de nomes compostos (para-choque, para-brisa, para-lama).
_PALAVRAS_GENERICAS = {
    "com", "sem", "dos", "das", "uma", "tipo", "uso", "usado", "usada",
    "utilizado", "utilizada", "destinado", "destinada", "embalagem",
    "embalado", "embalada", "volume", "litro", "litros", "unidade",
    "unidades", "peso", "gramas", "quilogramas", "capacidade", "nominal",
    "produto", "produtos", "item", "marca", "cor",
}


def _tokens_busca(termo: str) -> list[str]:
    tokens = [t.lower() for t in _TOKEN_RE.findall(termo) if len(t) >= 3]
    return [t for t in tokens if t not in _PALAVRAS_GENERICAS]

# Plurais irregulares em portugues (-al/-el/-ol/-ul -> -ais/-eis/-ois/-uis,
# ja sem diacritico pois o indice usa remove_diacritics) que a busca por
# prefixo (FTS5 '*') nao cobre sozinha -- ex.: 'farol' nao e prefixo de
# 'farois'. Gera o termo plural extra pra entrar no OR da busca.
_SUFIXOS_PLURAL_IRREGULAR = {
    "al": "ais",
    "el": "eis",
    "ol": "ois",
    "ul": "uis",
    "agem": "agens",
    "igem": "igens",
    "ugem": "ugens",
}


def _expandir_plural_irregular(token: str) -> str | None:
    for sufixo, plural in _SUFIXOS_PLURAL_IRREGULAR.items():
        if token.endswith(sufixo) and len(token) > len(sufixo):
            return token[: -len(sufixo)] + plural
    return None


def _connect():
    return sqlite3.connect(NCM_DB_PATH)


def lookup_by_code(codigo: str) -> dict | None:
    """Retorna a descricao oficial para um codigo NCM exato."""
    with _connect() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT codigo, descricao, data_inicio FROM ncm WHERE codigo = ?",
            (codigo.strip(),),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"codigo": row[0], "descricao": row[1], "data_inicio": row[2]}


def search_by_keyword(termo: str, limit: int = 10) -> list[dict]:
    """Busca codigos NCM cuja descricao contem o termo informado. Usado pelo
    agente para sugerir o NCM correto a partir da descricao do produto."""
    with _connect() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT codigo, descricao, data_inicio FROM ncm "
            "WHERE descricao LIKE ? LIMIT ?",
            (f"%{termo}%", limit),
        )
        rows = cur.fetchall()
    return [{"codigo": r[0], "descricao": r[1], "data_inicio": r[2]} for r in rows]


def _montar_query_fts(termo: str) -> str | None:
    """Converte texto livre (descricao de produto) numa query segura pro
    MATCH do FTS5. NAO e opcional passar o texto cru: caracteres como '-'
    sao sintaxe do MATCH (ex.: 'para-choques' cru lanca OperationalError).
    """
    tokens = _tokens_busca(termo)
    if not tokens:
        return None

    termos_query = []
    vistos = set()

    def adicionar(t: str):
        if t not in vistos:
            vistos.add(t)
            termos_query.append(f'"{t}"*')

    for token in tokens:
        adicionar(token)
        plural = _expandir_plural_irregular(token)
        if plural:
            adicionar(plural)

    return " OR ".join(termos_query)


def _montar_query_sinonimos(termo: str) -> str | None:
    """Query FTS separada, so com os SINONIMOS das palavras da busca (nao as
    palavras originais). Motivo de ser uma query a parte, e nao tudo junto
    na mesma busca: palavras comuns (ex.: 'automovel') tem sinonimos no
    WordNet que incluem sentidos bem distantes (ex.: 'trem', 'vagao',
    'comboio', do sentido 'carro de trem'). Se misturado na mesma busca, um
    termo especifico e util como 'acumuladores' (sinonimo de 'bateria') fica
    afogado por centenas de documentos que so batem com esse ruido -- testado
    e confirmado: o codigo certo caiu pra posicao 190 de 200 quando tudo foi
    misturado numa query so. Isolar os sinonimos numa busca propria evita
    que o ruido de uma palavra comum atrapalhe o sinal de uma palavra rara."""
    tokens = _tokens_busca(termo)
    termos_query = []
    vistos = set()

    def adicionar(t: str):
        if t not in vistos:
            vistos.add(t)
            termos_query.append(f'"{t}"*')

    for token in tokens:
        # so busca sinonimo se a palavra em si nao acha NADA sozinha -- se
        # ja acha (ex.: 'automovel', 'carro'), a palavra ja e util, e
        # expandir ela so adicionaria ruido de sentidos distantes (ver
        # docstring). Isso evita que 'automovel' (comum, ja funciona)
        # contamine a busca de sinonimo de 'bateria' (rara, precisa de ajuda).
        if _tem_hit_direto(token):
            continue
        for sinonimo in obter_sinonimos(token):
            for palavra_sinonimo in _TOKEN_RE.findall(sinonimo):
                if len(palavra_sinonimo) >= 3:
                    adicionar(palavra_sinonimo.lower())

    if not termos_query:
        return None
    return " OR ".join(termos_query)


def _tem_hit_direto(token: str) -> bool:
    """Verifica rapido se uma palavra sozinha (ou seu plural irregular, ex.
    'automovel' -> 'automoveis') ja acha algo na tabela -- usado pra decidir
    se vale a pena buscar sinonimo dela ou nao."""
    variantes = [token]
    plural = _expandir_plural_irregular(token)
    if plural:
        variantes.append(plural)
    query = " OR ".join(f'"{v}"*' for v in variantes)

    with _connect() as con:
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT 1 FROM ncm_fts WHERE ncm_fts MATCH ? LIMIT 1",
                (query,),
            )
            return cur.fetchone() is not None
        except sqlite3.OperationalError:
            return False


def _executar_query_fts(
    query: str, termo_original: str, limit: int, pesos: str = "0.0, 5.0, 1.0, 0.5"
) -> list[dict]:
    with _connect() as con:
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT codigo, texto_proprio, texto_ancestrais, "
                f"bm25(ncm_fts, {pesos}) AS score "
                "FROM ncm_fts WHERE ncm_fts MATCH ? ORDER BY score LIMIT ?",
                (query, limit),
            )
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            return [{"aviso": f"Nenhum NCM encontrado para '{termo_original}'."}]

    if not rows:
        return [{"aviso": f"Nenhum NCM encontrado para '{termo_original}'."}]

    codigos = [r[0] for r in rows]
    with _connect() as con:
        cur = con.cursor()
        placeholders = ",".join("?" * len(codigos))
        cur.execute(
            f"SELECT codigo, data_inicio FROM ncm WHERE codigo IN ({placeholders})",
            codigos,
        )
        datas = dict(cur.fetchall())

    resultados = []
    for codigo, texto_proprio, texto_ancestrais, _score in rows:
        caminho = f"{texto_ancestrais} > {texto_proprio}" if texto_ancestrais else texto_proprio
        resultados.append(
            {
                "codigo": codigo,
                "descricao": texto_proprio,
                "caminho_completo": caminho,
                "data_inicio": datas.get(codigo),
            }
        )
    return resultados


def _search_lexical(termo: str, limit: int = 15) -> list[dict]:
    """Busca por palavra/prefixo (FTS5) no caminho hierarquico completo de
    cada item, usando as palavras originais da busca. Rapida e precisa
    quando a descricao do produto compartilha alguma palavra com o texto
    oficial, mas nao acha nada quando o termo usado e um sinonimo puro
    (ex.: 'bateria' vs 'acumulador') -- para isso, ver _search_sinonimos."""
    query = _montar_query_fts(termo)
    if query is None:
        return [{"aviso": f"Nenhum termo de busca valido extraido de '{termo}'."}]
    return _executar_query_fts(query, termo, limit)


def _search_sinonimos(termo: str, limit: int = 15) -> list[dict]:
    """Busca so pelos SINONIMOS (WordNet + lista manual) das palavras da
    busca -- numa query separada da lexical principal, de proposito (ver
    _montar_query_sinonimos para o motivo).

    Usa peso MAIOR pro texto ancestral que pro texto proprio (invertido em
    relacao a busca lexical normal). Motivo: um sinonimo (ex.: 'azulejo' ->
    'ladrilho') quase sempre so aponta pra CATEGORIA certa (o cabecalho do
    capitulo/posicao), nao pro item especifico -- o item-folha raramente
    repete a palavra da categoria no proprio texto (ex.: '6907.23.00' so diz
    'com coeficiente de absorcao de agua... superior a 10%', nao 'ladrilho').
    Com o peso normal (texto proprio > ancestral), itens de OUTROS
    materiais que por acaso repetem 'ladrilho' no proprio texto venciam o
    item ceramico certo -- testado e confirmado."""
    query = _montar_query_sinonimos(termo)
    if query is None:
        return []
    return _executar_query_fts(query, termo, limit, pesos="0.0, 1.0, 5.0, 0.5")


def search_by_description(termo: str, limit: int = 25) -> list[dict]:
    """Busca o NCM a partir da descricao livre de um produto (pode ser a
    frase inteira, nao precisa ser uma unica palavra-chave). Combina duas
    buscas complementares sobre o caminho hierarquico completo de cada
    item (Capitulo/Posicao/Subposicao + descricao propria):

    1. Lexical (FTS5): rapida e precisa quando a descricao compartilha
       palavra/prefixo com o texto oficial (ex.: 'pneu' encontra
       '4011.10.00' mesmo esse item sozinho nao citando 'pneu' -- so o
       cabecalho pai cita).
    2. Sinonimos (WordNet + lista manual, busca SEPARADA da lexical): cobre
       sinonimos puros que a lexical nunca acharia (ex.: 'azulejo' ->
       'ladrilho'). E uma query a parte porque misturar os sinonimos de
       palavras comuns na mesma busca gera ruido demais (ver
       _montar_query_sinonimos).

    Busca semantica por embeddings (src.ncm.embeddings) foi testada e NAO
    entra aqui: os dois modelos avaliados (nomic-embed-text e
    paraphrase-multilingual-mpnet-base-v2) nao conectaram o vocabulario
    tecnico em portugues, e usar o modelo de embedding junto com o llama3.1
    obrigava o Ollama a trocar de modelo a cada sugestao -- o que travava
    a instalacao desta maquina.

    Resultados lexicais vem primeiro (mais confiaveis quando existem),
    depois sinonimos. O codigo correto nao e sempre o primeiro da lista."""
    lexicais = _search_lexical(termo, limit=limit)
    if lexicais and "aviso" in lexicais[0]:
        lexicais = []

    sinonimos = _search_sinonimos(termo, limit=limit)
    if sinonimos and "aviso" in sinonimos[0]:
        sinonimos = []

    # Prioridade: lexical primeiro (mais confiavel), com uma reserva PEQUENA
    # so pra sinonimo (so dispara quando uma palavra nao acha nada sozinha --
    # ver _montar_query_sinonimos, entao ja e um sinal relativamente
    # confiavel).
    reserva_sinonimo = 4 if sinonimos else 0
    primeiros_lexicais = lexicais[: limit - reserva_sinonimo]
    resto_lexicais = lexicais[len(primeiros_lexicais) :]

    combinados = list(primeiros_lexicais)
    vistos = {r["codigo"] for r in combinados}
    for r in sinonimos:
        if len(combinados) >= limit:
            break
        if r["codigo"] not in vistos:
            combinados.append(r)
            vistos.add(r["codigo"])
    for r in resto_lexicais:
        if len(combinados) >= limit:
            break
        if r["codigo"] not in vistos:
            combinados.append(r)
            vistos.add(r["codigo"])

    if not combinados:
        return [{"aviso": f"Nenhum NCM encontrado para '{termo}'."}]
    return combinados


def code_exists(codigo: str) -> bool:
    return lookup_by_code(codigo) is not None


@functools.lru_cache(maxsize=2048)
def titulo_posicao(posicao: str) -> str | None:
    """Titulo de uma posicao de 4 digitos ('87.11' ou '8711'). Posicoes sem
    subdivisao ficam gravadas como '8712.00', por isso busca pelo codigo
    mais curto que comeca com esses digitos."""
    digitos = posicao.replace(".", "")
    with _connect() as con:
        row = con.execute(
            "SELECT descricao FROM ncm WHERE replace(codigo, '.', '') LIKE ? "
            "ORDER BY length(codigo) LIMIT 1",
            (f"{digitos}%",),
        ).fetchone()
    return row[0] if row else None


def classificar_capitulo(codigo_ou_texto: str) -> dict | None:
    """Classificacao DETERMINISTICA (sem LLM): os 2 primeiros digitos de
    qualquer codigo NCM sempre indicam o Capitulo (categoria macro), ex.:
    87 = veiculos automoveis e suas partes. Isso serve tanto de roteamento
    normal (agrupar a busca por assunto) quanto de fallback quando o agente
    nao responde -- ver src.agent.core.diagnose().

    Aceita tanto um codigo NCM ('8708.10.00') quanto qualquer texto que
    contenha um (extrai os 2 primeiros digitos numericos encontrados).
    """
    import re

    match = re.search(r"\d{2}", codigo_ou_texto)
    if not match:
        return None
    capitulo = match.group()

    with _connect() as con:
        cur = con.cursor()
        cur.execute("SELECT capitulo, titulo FROM capitulos WHERE capitulo = ?", (capitulo,))
        row = cur.fetchone()
    if not row:
        return None
    return {"capitulo": row[0], "titulo": row[1]}


def normalizar_codigo_erp(bruto: str | None) -> str | None:
    """O ERP guarda o NCM sem pontuacao (ex.: '84849000'). Nossa tabela usa
    o formato oficial com pontos (ex.: '8484.90.00'). Converte um formato no
    outro; devolve None se nao tiver o formato esperado de 8 digitos."""
    if not bruto:
        return None
    digitos = bruto.strip()
    if len(digitos) != 8 or not digitos.isdigit():
        return None
    return f"{digitos[:4]}.{digitos[4:6]}.{digitos[6:8]}"


def ncm_valido(bruto: str | None) -> bool:
    """Verifica se o NCM cru do ERP (sem pontuacao) e um codigo valido e
    vigente, cruzando com a tabela oficial ja extraida. Nao usa IA -- e
    apenas uma consulta direta, por isso nunca falha nem alucina."""
    codigo = normalizar_codigo_erp(bruto)
    if codigo is None:
        return False
    return code_exists(codigo)


def listar_subcodigos(prefixo: str, limit: int = 30) -> list[dict]:
    """Lista os codigos NCM mais especificos dentro de um prefixo (ex.:
    prefixo '4011' devolve os 8-digitos filhos de 'Pneumaticos novos').
    Usado para descer na hierarquia Capitulo->Posicao->Subposicao->Item ate
    achar o codigo folha (8 digitos), que e o unico valido para cadastro."""
    prefixo_digitos = prefixo.strip().replace(".", "")
    with _connect() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT codigo, descricao FROM ncm "
            "WHERE replace(codigo, '.', '') LIKE ? "
            "AND replace(codigo, '.', '') != ? "
            "ORDER BY codigo LIMIT ?",
            (f"{prefixo_digitos}%", prefixo_digitos, limit),
        )
        rows = cur.fetchall()
    return [{"codigo": r[0], "descricao": r[1]} for r in rows]


def listar_capitulos() -> list[dict]:
    """Lista todos os 96 capitulos do NCM (categoria macro + titulo)."""
    with _connect() as con:
        cur = con.cursor()
        cur.execute("SELECT capitulo, titulo FROM capitulos ORDER BY capitulo")
        rows = cur.fetchall()
    return [{"capitulo": r[0], "titulo": r[1]} for r in rows]
