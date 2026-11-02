"""Sugestao de NCM para um produto com NCM invalido/vazio -- o gatilho
descrito no TCC: quando um produto e cadastrado sem NCM valido, a IA entra
em acao e propoe o codigo, que so e aplicado depois de aprovacao humana.

Desenho "recupera e escolhe" (retrieve-then-choose), em vez de um agente
que decide sozinho quando chamar ferramentas:

1. A busca roda direto em Python (src.ncm.lookup.search_by_description),
   sem depender do modelo "lembrar" de chamar uma ferramenta. Na versao
   anterior (agente com tool calling), o llama3.1 8B chamava a busca certo,
   recebia o codigo correto na lista... e respondia algo inventado ("tubo
   de escape" para um azulejo). Antes da busca, o LLM so reescreve a
   descricao do dia a dia na linguagem da tabela ('sabonete' -> 'sabao de
   toucador'), e a busca roda com as duas versoes.
2. O modelo responde duas perguntas curtas em vez de uma dificil:
   primeiro "em qual Capitulo esse produto se encaixa?" (azulejo e peixe ou
   ceramica?), depois "quais os 3 itens mais provaveis, dentro desse
   capitulo?" -- vendo o texto quase completo so dos itens daquele capitulo.
3. A resposta e travada por JSON Schema (saida estruturada do Ollama): o
   campo do codigo so aceita um dos codigos candidatos. O modelo nao tem
   como inventar um codigo -- no maximo ordenar mal os candidatos.
4. O operador ve as 3 opcoes e escolhe uma (Human-in-the-Loop). Nos testes,
   quando o modelo errava a 1a opcao, a certa quase sempre estava logo
   abaixo, no mesmo capitulo (leite integral vs desnatado, pilha AA vs C).
5. Memoria: produtos parecidos ja classificados no proprio ERP (ver
   src.db.memoria) entram como candidato e como pista para o modelo.

Experimento descartado: navegacao de cima para baixo (capitulo -> posicao
-> item, vendo a lista completa de cada nivel). Acertava o capitulo em 90%
e a posicao em ~84% dos casos do conjunto dev, mas no fim empatou no dev
(top-3 63% vs 61%) e perdeu no teste (55% vs 64%), levando quase o dobro do
tempo -- com um modelo de 7B, o gargalo e escolher o item, nao achar o ramo.
"""
import json
import re

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from src.config import ollama_config
from src.db.memoria import produtos_parecidos
from src.ncm import hierarquia
from src.ncm import conhecimento
from src.ncm.abreviacoes import expandir as expandir_abreviacoes
from src.ncm.lookup import search_by_description, titulo_posicao

NENHUM = "NENHUM"

SYSTEM_PROMPT = """Voce e um especialista em classificacao fiscal de \
mercadorias na NCM (Nomenclatura Comum do Mercosul) da Receita Federal.

A descricao do produto vem do jeito que foi digitada no cadastro de um ERP: \
pode estar em maiusculas, sem hifen, abreviada ou com erro de digitacao \
(ex.: PARACHOQUE = para-choque de carro; AZULEIJO = azulejo). Os \
candidatos vem de uma busca automatica e CONTEM RUIDO: alguns nao tem nada \
a ver com o produto.

Regras:
1. Pense no que o produto E de fato (material, funcao) antes de escolher. \
Uma cor ou palavra solta no nome nao muda o que o produto e (um azulejo \
azul continua sendo ceramica, nunca peixe).
2. Se um candidato nomeia diretamente o produto (ex.: 'Para-choques e suas \
partes' para um parachoque), escolha ele.
3. Nao escolha um item 'Outros'/'Outras' so porque ficou em duvida: todo \
'Outros' pertence a uma posicao especifica (ex.: 'Outros' de tijolos \
refratarios). Escolha primeiro a posicao que descreve o produto e so \
depois o item dentro dela.
4. Responda SOMENTE com codigos/capitulos da lista. Na escolha do \
capitulo, use NENHUM apenas se nenhum candidato for sequer do mesmo tipo \
de produto.
5. Contexto do negocio: o ERP e de uma oficina mecanica de automoveis. \
Quando a descricao nao diz o tipo de veiculo e o mesmo produto existir para \
automovel e para moto/bicicleta/trator/trem, prefira o de automovel. Isso \
vale so para desempatar -- um produto que claramente nao e peca de carro \
(ex.: azulejo) continua sendo classificado pelo que ele e.
6. Cada justificativa deve ser curta e em linguagem simples. Se a escolha \
exata depender de uma informacao que a descricao nao tem (ex.: tipo de \
ceramica, absorcao de agua), diga qual informacao falta -- e justamente \
por isso as outras opcoes existem.
"""


class OpcaoNcm(BaseModel):
    codigo: str = Field(description="Codigo NCM (formato 0000.00.00)")
    descricao: str = Field(description="Caminho oficial legivel: posicao > subposicao > item")
    justificativa: str = Field(description="Por que o modelo considera essa opcao")


class NcmSuggestion(BaseModel):
    """Ate 3 opcoes, da mais para a menos provavel. Lista vazia = sem
    sugestao (motivo em observacao). Sem campo de 'confianca': nos testes, o
    modelo declarava confianca 'alta' justamente nos erros."""

    opcoes: list[OpcaoNcm] = Field(default_factory=list)
    interpretacao: str | None = Field(default=None, description="Descricao tecnica usada na busca")
    caracteristicas: str | None = Field(default=None, description="O que decide a classificacao, segundo o modelo")
    observacao: str = Field(default="", description="Motivo quando nao ha sugestao")
    pergunta: str | None = Field(default=None, description="Informacao que falta para decidir, a perguntar ao operador")
    parecidos: list[dict] = Field(default_factory=list, description="Produtos parecidos ja classificados no ERP")
    # Rastro das etapas, para medir onde a classificacao erra (scripts/avaliar.py)
    capitulos: list[str] = Field(default_factory=list)
    posicoes: list[str] = Field(default_factory=list)
    candidatos: list[str] = Field(default_factory=list, description="Codigos que a busca entregou ao modelo")
    # Base de conhecimento: produtos parecidos de outras lojas e o voto deles
    conhecimento: list[dict] = Field(default_factory=list)
    votos_conhecimento: list[tuple[str, float]] = Field(default_factory=list)

    @property
    def ncm_sugerido(self) -> str | None:
        return self.opcoes[0].codigo if self.opcoes else None


def build_ncm_agent(modelo: str | None = None) -> ChatOllama:
    # Contexto limitado de proposito: grande demais forca o Ollama a tirar
    # parte do modelo da VRAM (8GB na placa) e rodar na CPU, o que ja causou
    # travamento por falta de RAM nesta maquina (com llama3.1 e 16k). O
    # qwen2.5 usa atencao com poucas cabecas de KV, entao 8k cabe na GPU.
    nome = modelo or ollama_config.model
    return ChatOllama(
        base_url=ollama_config.base_url,
        model=nome,
        temperature=0,
        num_ctx=8192,
        # Qwen3 "pensa" antes de responder por padrao, o que multiplica o
        # tempo; as respostas aqui sao curtas e travadas por esquema.
        reasoning=False if nome.startswith("qwen3") else None,
    )


_FAIXA_POSICOES_RE = re.compile(r"posi[çc][õo]es\s+(\d{2})\.(\d{2})\s+a\s+(\d{2})\.(\d{2})")


def _curto(texto: str, maximo: int) -> str:
    texto = texto.strip(" -").strip()
    return texto if len(texto) <= maximo else texto[: maximo - 3].rstrip() + "..."


def _nome_curto_posicao(titulo: str) -> str:
    return _curto(re.split(r"[(,;.]", titulo, maxsplit=1)[0], 35)


def _traduzir_referencias(texto: str) -> str:
    """O texto oficial referencia outras posicoes so pelo numero ('partes
    dos veiculos das posicoes 87.11 a 87.13'), e o modelo nao tem como saber
    que isso significa motos/bicicletas/cadeiras de rodas. Sem isso, o
    modelo classificava pastilha de freio de carro como peca de bicicleta.
    Acrescenta o nome curto de cada posicao da faixa."""

    def substituir(m: re.Match) -> str:
        capitulo, inicio, capitulo_fim, fim = m.groups()
        if capitulo != capitulo_fim or int(fim) - int(inicio) > 10:
            return m.group(0)
        nomes = [
            _nome_curto_posicao(t)
            for n in range(int(inicio), int(fim) + 1)
            if (t := titulo_posicao(f"{capitulo}{n:02d}"))
        ]
        return f"{m.group(0)} (= {'; '.join(nomes)})" if nomes else m.group(0)

    return _FAIXA_POSICOES_RE.sub(substituir, texto)


def _descrever_item(candidato: dict, maximo_por_nivel: int) -> str:
    """Caminho do item sem o titulo do capitulo: posicao > subposicao(oes) >
    descricao propria. O texto proprio sozinho costuma ser inutil ('Outros',
    'Com um coeficiente de absorcao...') sem os niveis de cima."""
    partes = candidato["caminho_completo"].split(" > ")[1:]
    segmentos: list[str] = []
    for p in partes:
        curto = _traduzir_referencias(_curto(p, maximo_por_nivel))
        if not segmentos or segmentos[-1] != curto:
            segmentos.append(curto)
    return " > ".join(segmentos) or candidato["descricao"]


def _agrupar_por_capitulo(candidatos: list[dict]) -> dict[str, list[dict]]:
    grupos: dict[str, list[dict]] = {}
    for c in candidatos:
        grupos.setdefault(c["codigo"][:2], []).append(c)
    return grupos


def _titulo_capitulo(candidato: dict) -> str:
    return candidato["caminho_completo"].split(" > ")[0]


def _listar_capitulos(grupos: dict[str, list[dict]]) -> str:
    """Etapa 1: cada capitulo com seu titulo e os itens bem resumidos, so
    pra dar uma ideia do que tem ali dentro."""
    linhas = []
    for numero, itens in grupos.items():
        linhas.append(f"[Capitulo {numero} - {_curto(_titulo_capitulo(itens[0]), 90)}]")
        for c in itens[:6]:
            linhas.append(f"  - {_curto(_descrever_item(c, 45), 110)}")
        if len(itens) > 6:
            linhas.append(f"  - (+{len(itens) - 6} itens)")
    return "\n".join(linhas)


def _listar_itens(itens: list[dict]) -> str:
    """Etapa 2: so os itens do capitulo escolhido, com texto quase completo
    -- cortar demais apaga justamente a palavra que diferencia um item do
    outro (ex.: 'refratarios' em 69.02 vs 'de ceramica' em 69.07)."""
    return "\n".join(f"  {c['codigo']}: {_descrever_item(c, 180)}" for c in itens)


# Nota 2 da Secao XVII do Sistema Harmonizado: as "partes e acessorios" de
# veiculos (87.08, 87.14...) nao incluem pecas de uso geral, que tem posicao
# propria em outros capitulos mesmo quando sao claramente de carro.
REGRA_SECAO17 = """
7. Pecas de uso geral NAO sao classificadas como "partes e acessorios" de \
veiculos (87.08), mesmo quando sao de carro (Nota 2 da Secao XVII). Elas \
tem posicao propria: rolamentos (84.82); parafusos, porcas e arruelas \
(73.18); molas (73.20); juntas, retentores e outros artigos de borracha \
(40.16); mangueiras de borracha (40.09); correias (40.10); pneus (40.11); \
filtros (84.21); bombas (84.13); pecas de motor (84.09); lampadas (85.39); \
reles, fusiveis e interruptores (85.36); velas, bobinas, alternadores e \
motores de arranque (85.11); farois, buzinas e limpadores de para-brisa, \
com suas partes (85.12); vidros (70.07); espelhos (70.09); fios e cabos \
eletricos (85.44); ferramentas (Cap. 82). Use a 87.08 so para partes \
proprias de veiculo que nao tenham posicao especifica (para-choques, \
freios, suspensao, radiadores, silenciosos, direcao, rodas).
"""


def _prompt_sistema() -> str:
    return SYSTEM_PROMPT + (REGRA_SECAO17 if CONFIG["regra_secao17"] else "")


def _perguntar(
    modelo: ChatOllama, schema: dict, pergunta: str, prompt_sistema: str | None = None
) -> dict | None:
    """Uma chamada ao LLM com a resposta travada pelo JSON Schema."""
    if prompt_sistema is None:
        prompt_sistema = _prompt_sistema()
    travado = ChatOllama(
        base_url=modelo.base_url,
        model=modelo.model,
        temperature=modelo.temperature,
        num_ctx=modelo.num_ctx,
        format=schema,
        reasoning=modelo.reasoning,
    )
    resposta = travado.invoke(
        [{"role": "system", "content": prompt_sistema}, {"role": "user", "content": pergunta}]
    )
    try:
        return json.loads(resposta.content)
    except (json.JSONDecodeError, TypeError):
        return None


# Os exemplos sao de produtos que NAO estao em nenhum conjunto de avaliacao
# (scripts/avaliar.py) -- usar um produto do gabarito como exemplo inflaria
# a taxa de acerto medida.
PROMPT_ANALISE = """Voce conhece a Nomenclatura Comum do Mercosul (NCM). \
Para a descricao de produto recebida (pode ter erro de digitacao), responda:

- descricao_tecnica: o nome tecnico/formal que a NCM usa para esse tipo de \
mercadoria. No maximo 8 palavras. Sem embalagem, volume, peso, medidas, \
potencia, cor ou marca.
- caracteristicas: ate 15 palavras com o que decide a classificacao: \
material, funcao, aplicacao (ex.: para automovel), estado (novo, \
refinado, cru...), se e produto completo ou peca. Se algo importante nao \
da para saber pela descricao, diga "nao informado: ...".

Responda SEMPRE em portugues do Brasil, nunca em outro idioma.

Exemplos:
'TV LED 50 POLEGADAS' -> descricao_tecnica 'aparelho receptor de televisao'; \
caracteristicas 'aparelho eletronico completo, tela de LED, uso domestico'
'GUARDA ROUPA MDF' -> descricao_tecnica 'movel de madeira para quarto de \
dormir'; caracteristicas 'movel completo, madeira aglomerada (MDF), uso domestico'
'SUCO DE LARANJA 1L' -> descricao_tecnica 'suco de laranja nao fermentado'; \
caracteristicas 'bebida nao alcoolica, fruta, pronto para beber; nao \
informado: valor Brix'
"""

# Chaves de experimento (scripts/avaliar.py --config chave=valor). Os valores
# padrao sao os da versao adotada.
# Padrao = melhor configuracao no DEV+DEV2 (diario, secoes 8 e 9), medida uma vez no TESTE2.
CONFIG = {
    "abreviacoes": True,  # expande abreviacoes do cadastro (src.ncm.abreviacoes)
    "regra_secao17": True,  # pecas de uso geral nao vao na 87.08 (Nota 2 da Secao XVII)
    "contexto_negocio": False,  # a analise sabe que o ERP e de oficina/autopecas
    "hipoteses": False,  # a analise da ate 2 outras interpretacoes, buscadas tambem
    "dicas_posicao": False,  # a analise tambem chuta posicoes de 4 digitos
    "irmaos": 0,  # na etapa 2, mostra todos os itens das N posicoes mais provaveis
    "max_itens_etapa2": 30,
    # Base de conhecimento (src.ncm.conhecimento): nomes das bases de clientes
    # a consultar, separados por "+" (ex.: "loja_a+loja_b"); vazio desliga.
    "conhecimento": "loja_a",
    # Depois da escolha do LLM, poe o NCM mais votado pela base em 1o lugar
    # quando a base esta confiante (voto >= 2 e vizinho bem parecido).
    "conhecimento_primeiro": True,
}

PROMPT_POSICOES = """
- posicoes_provaveis: ate 3 posicoes do Sistema Harmonizado (4 digitos, ex.: "8708") onde esse produto provavelmente se classifica, da mais para a menos provavel. Pense no capitulo certo primeiro (ex.: pecas de carro 87, maquinas 84, aparelhos eletricos 85, plasticos 39, borracha 40, ferramentas 82).

Exemplos de posicoes: 'TV LED 50 POLEGADAS' -> ["8528"]; 'GUARDA ROUPA MDF' -> ["9403"]; 'SUCO DE LARANJA 1L' -> ["2009"].
"""

PROMPT_CONTEXTO = """
Contexto: o ERP e usado principalmente por oficinas mecanicas e lojas de \
autopecas, entao muitos produtos sao pecas, fluidos e ferramentas para \
veiculos; mas a loja tambem vende itens de outros setores (alimentos, \
limpeza, construcao, eletronicos). Interprete cada termo no sentido mais \
comum nesse comercio (ex.: em autopecas, 'anel' costuma ser anel de pistao).
"""

PROMPT_HIPOTESES = """
- outras_interpretacoes: ate 2 outros nomes tecnicos possiveis, se a \
descricao for ambigua ou se voce nao tiver certeza do que e o produto (ex.: \
outro significado da palavra, ou o nome do material/substancia). Lista \
vazia se nao houver duvida.
"""

_NAO_LATINO_RE = re.compile(r"[^\x00-ɏ]+")


def _latino(texto: str | None) -> str | None:
    # O qwen2.5 as vezes mistura chines no meio da resposta mesmo instruido a
    # responder em portugues ('bateria蓄能器'). So mantem alfabeto latino.
    if not texto:
        return None
    return _NAO_LATINO_RE.sub(" ", texto).strip() or None


def _analisar_produto(
    modelo: ChatOllama, descricao_produto: str
) -> tuple[str | None, str | None, list[str], list[str]]:
    """Traduz a descricao do dia a dia pra linguagem da tabela NCM (ex.:
    'sabonete' -> 'sabao de toucador', 'cadeira' -> 'assento') e lista as
    caracteristicas que decidem a classificacao. A tabela oficial quase
    nunca usa o nome popular do produto, e um dicionario de sinonimos manual
    nao escala pra centenas de pares como esses.
    Devolve (descricao_tecnica, caracteristicas, posicoes_provaveis,
    outras_interpretacoes); as duas ultimas so vem preenchidas com
    CONFIG["dicas_posicao"] e CONFIG["hipoteses"]."""
    propriedades = {
        "descricao_tecnica": {"type": "string"},
        "caracteristicas": {"type": "string"},
    }
    prompt = PROMPT_ANALISE
    if CONFIG["contexto_negocio"]:
        prompt += PROMPT_CONTEXTO
    if CONFIG["hipoteses"]:
        propriedades["outras_interpretacoes"] = {"type": "array", "maxItems": 2, "items": {"type": "string"}}
        prompt += PROMPT_HIPOTESES
    if CONFIG["dicas_posicao"]:
        propriedades["posicoes_provaveis"] = {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "pattern": "^[0-9]{4}$"},
        }
        prompt += PROMPT_POSICOES
    resposta = _perguntar(
        modelo,
        {"type": "object", "properties": propriedades, "required": list(propriedades)},
        f"Produto: {descricao_produto}",
        prompt_sistema=prompt,
    )
    resposta = resposta or {}
    posicoes = []
    for pos in resposta.get("posicoes_provaveis") or []:
        pos = re.sub(r"\D", "", str(pos))[:4]
        if len(pos) == 4 and hierarquia.itens_da_posicao(pos) and pos not in posicoes:
            posicoes.append(pos)
    hipoteses = [h for h in (_latino(x) for x in resposta.get("outras_interpretacoes") or []) if h]
    return (
        _latino(resposta.get("descricao_tecnica")),
        _latino(resposta.get("caracteristicas")),
        posicoes,
        hipoteses[:2],
    )


def _fundir_rankings(listas: list[list[dict]], limite: int, k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion (Cormack et al., 2009): junta rankings somando
    1/(k + posicao) de cada lista. Um codigo bem colocado nas duas buscas
    sobe; um que so aparece numa delas ainda entra, intercalado."""
    pontos: dict[str, float] = {}
    por_codigo: dict[str, dict] = {}
    for lista in listas:
        for posicao, c in enumerate(lista):
            pontos[c["codigo"]] = pontos.get(c["codigo"], 0.0) + 1 / (k + posicao + 1)
            por_codigo.setdefault(c["codigo"], c)
    ordem = sorted(pontos, key=pontos.get, reverse=True)[:limite]
    return [por_codigo[c] for c in ordem]


def _itens_das_posicoes(posicoes: list[str], prioridade: list[dict], por_posicao: int = 12) -> list[dict]:
    """Itens das posicoes indicadas pelo modelo, como uma terceira lista para
    a fusao: em cada posicao, primeiro os que a busca por palavras tambem
    achou (na ordem dela), depois os demais na ordem da tabela."""
    ordem = {c["codigo"]: i for i, c in enumerate(prioridade)}
    lista = []
    for pos in posicoes:
        itens = sorted(hierarquia.itens_da_posicao(pos), key=lambda c: ordem.get(c["codigo"], len(ordem)))
        lista += itens[:por_posicao]
    return lista


def buscar_candidatos(
    modelo: ChatOllama,
    descricao_produto: str,
    limite: int = 40,
    descricao_tecnica: str | None = None,
    posicoes: list[str] | None = None,
    hipoteses: list[str] | None = None,
) -> tuple[list[dict], str | None]:
    """Busca pela descricao original E pela descricao tecnica, fundindo as
    listas (e, com dicas de posicao, os itens das posicoes indicadas).
    Devolve (candidatos, descricao_tecnica). Se a descricao tecnica nao vier
    pronta, pede ao modelo."""
    if descricao_tecnica is None:
        descricao_tecnica, _, posicoes, hipoteses = _analisar_produto(modelo, descricao_produto)
    listas = [[c for c in search_by_description(descricao_produto, limit=limite) if "codigo" in c]]
    if descricao_tecnica:
        listas.append([c for c in search_by_description(descricao_tecnica, limit=limite) if "codigo" in c])
    for hipotese in hipoteses or []:
        listas.append([c for c in search_by_description(hipotese, limit=limite) if "codigo" in c])
    if posicoes:
        listas.append(_itens_das_posicoes(posicoes, [c for lista in listas for c in lista]))
    return _fundir_rankings(listas, limite), descricao_tecnica


MAX_OPCOES = 3


def _buscar_parecidos(descricao_produto: str, codigo_produto: int | None, ignorar_identicos: bool) -> list[dict]:
    try:
        return produtos_parecidos(
            descricao_produto, excluir_codigo=codigo_produto, ignorar_identicos=ignorar_identicos
        )
    except Exception:
        return []  # sem acesso ao ERP a sugestao continua funcionando, so sem memoria


def _candidato_do_ncm(ncm: str) -> dict | None:
    """O item da tabela NCM no mesmo formato que a busca devolve."""
    return next((c for c in hierarquia.itens_da_posicao(ncm.replace(".", "")[:4]) if c["codigo"] == ncm), None)


def sugerir_ncm(
    modelo: ChatOllama,
    descricao_produto: str,
    codigo_produto: int | None = None,
    usar_memoria: bool = True,
    ignorar_identicos: bool = False,
) -> NcmSuggestion:
    """Busca candidatos e pede ao LLM, em duas perguntas curtas, que escolha
    primeiro o capitulo e depois os 3 itens mais provaveis dentro dele.
    Sempre devolve um NcmSuggestion -- lista de opcoes vazia quando a busca
    nao acha nada ou o modelo descarta todos os capitulos.

    usar_memoria: consulta produtos parecidos ja classificados no ERP (ver
    src.db.memoria). ignorar_identicos: para avaliacao, nao deixa um produto
    'colar' a resposta de um cadastro identico ja aprovado."""
    parecidos = _buscar_parecidos(descricao_produto, codigo_produto, ignorar_identicos) if usar_memoria else []
    por_extenso = descricao_produto
    if CONFIG["abreviacoes"] and expandir_abreviacoes(descricao_produto) != descricao_produto.upper().strip():
        por_extenso = expandir_abreviacoes(descricao_produto)
    descricao_tecnica, caracteristicas, posicoes_dica, hipoteses = _analisar_produto(modelo, por_extenso)
    candidatos, _ = buscar_candidatos(
        modelo, por_extenso, descricao_tecnica=descricao_tecnica or "", posicoes=posicoes_dica, hipoteses=hipoteses
    )

    # O NCM do produto mais parecido entra como 1o candidato: a busca por
    # palavras pode nao acha-lo (ex.: descricao com nome popular), e um
    # cadastro ja aprovado pelo operador e a pista mais forte que existe.
    # Base de conhecimento: o que outras lojas ja classificaram de parecido.
    vizinhos, votos = [], []
    if CONFIG["conhecimento"]:
        vizinhos = conhecimento.parecidos(descricao_produto, 10, bases=CONFIG["conhecimento"].split("+"))
        votos = conhecimento.votar(vizinhos)
        frente = [item for ncm, _ in reversed(votos[:3]) if (item := _candidato_do_ncm(ncm))]
        for item in frente:
            candidatos = [item] + [c for c in candidatos if c["codigo"] != item["codigo"]]

    if parecidos and (item := _candidato_do_ncm(parecidos[0]["ncm"])):
        candidatos = [item] + [c for c in candidatos if c["codigo"] != item["codigo"]]

    def _sem_sugestao(motivo: str) -> NcmSuggestion:
        return NcmSuggestion(
            interpretacao=descricao_tecnica, caracteristicas=caracteristicas, parecidos=parecidos, observacao=motivo
        )

    if not candidatos:
        return _sem_sugestao(f"A busca nao encontrou nenhum NCM candidato para '{descricao_produto}'.")

    grupos = _agrupar_por_capitulo(candidatos)
    produto = f'Produto cadastrado no ERP: "{descricao_produto}"'
    if por_extenso != descricao_produto:
        produto += f'\nPor extenso: "{por_extenso}"'
    if descricao_tecnica:
        produto += f"\nInterpretacao tecnica: {descricao_tecnica}"
    if hipoteses:
        produto += f"\nOutras interpretacoes possiveis: {'; '.join(hipoteses)}"
    if caracteristicas:
        produto += f"\nCaracteristicas: {caracteristicas}"
    if vizinhos:
        exemplos = "; ".join(f"'{conhecimento.limpar_descricao(v['descricao'])[:60]}' -> {v['ncm']}" for v in vizinhos[:6])
        resumo = ", ".join(f"{n} ({p:.1f})" for n, p in votos[:3])
        produto += (
            f"\nProdutos parecidos ja classificados por outras lojas de autopecas: {exemplos}. "
            f"NCMs mais frequentes entre eles (peso): {resumo}. Use como forte indicio quando "
            "forem do mesmo tipo de produto; ignore se forem de outro tipo."
        )
    if parecidos:
        exemplos = "; ".join(f"'{p['descricao']}' -> {p['ncm']}" for p in parecidos)
        produto += (
            f"\nProdutos parecidos ja cadastrados nesta empresa, com NCM aprovado: {exemplos}"
            " (forte indicio, mas confira se e mesmo o mesmo tipo de produto)"
        )

    # Etapa 1: que tipo de coisa e esse produto? (pulada se so ha um capitulo)
    if len(grupos) == 1:
        capitulo = next(iter(grupos))
        o_que_e = ""
    else:
        esquema1 = {
            "type": "object",
            "properties": {
                "o_que_e_o_produto": {"type": "string"},
                "capitulo": {"type": "string", "enum": list(grupos) + [NENHUM]},
            },
            "required": ["o_que_e_o_produto", "capitulo"],
        }
        pergunta1 = (
            f"{produto}\n\nEm qual destes capitulos esse produto se encaixa? "
            "Os capitulos (e os itens dentro de cada um) estao em ordem de "
            "relevancia segundo a busca: o primeiro costuma ser o certo, mas "
            "descarte-o se claramente nao for o tipo de produto.\n"
            f"{_listar_capitulos(grupos)}"
        )
        # O modelo local as vezes devolve JSON quebrado: uma segunda tentativa resolve.
        etapa1 = _perguntar(modelo, esquema1, pergunta1) or _perguntar(modelo, esquema1, pergunta1)
        if etapa1 is None:
            return _sem_sugestao("O modelo nao respondeu no formato esperado ao escolher o capitulo.")
        capitulo = etapa1.get("capitulo")
        o_que_e = etapa1.get("o_que_e_o_produto", "")
        if capitulo not in grupos:
            return _sem_sugestao(f"Nenhum capitulo dos candidatos corresponde ao produto, segundo o modelo: {o_que_e}")

    # Etapa 2: quais os itens mais provaveis dentro do capitulo escolhido?
    itens = grupos[capitulo]
    if CONFIG["irmaos"]:
        # Mostra a posicao inteira das N mais provaveis: o item certo costuma
        # ser um "irmao" que a busca nao trouxe (refinado x cristal, com x sem
        # aditivos), e sem ele na lista o modelo nao tem como escolhe-lo.
        top_posicoes = list(dict.fromkeys(c["codigo"].replace(".", "")[:4] for c in itens))[: CONFIG["irmaos"]]
        expandidos = [i for pos in top_posicoes for i in hierarquia.itens_da_posicao(pos)]
        vistos = {i["codigo"] for i in expandidos}
        itens = (expandidos + [c for c in itens if c["codigo"] not in vistos])[: CONFIG["max_itens_etapa2"]]
    por_codigo = {c["codigo"]: c for c in itens}
    quantas = min(MAX_OPCOES, len(itens))
    esquema2 = {
        "type": "object",
        "properties": {
            "opcoes": {
                "type": "array",
                "minItems": 1,
                "maxItems": quantas,
                "items": {
                    "type": "object",
                    "properties": {
                        "justificativa": {"type": "string"},
                        "codigo": {"type": "string", "enum": list(por_codigo)},
                    },
                    "required": ["justificativa", "codigo"],
                },
            },
            # Depois das opcoes, para nao influenciar a escolha.
            "informacao_que_falta": {"type": "string"},
        },
        "required": ["opcoes", "informacao_que_falta"],
    }
    pergunta2 = (
        f"{produto}\n"
        + (f"O que e: {o_que_e}\n" if o_que_e else "")
        + f"\nItens do Capitulo {capitulo} - {_titulo_capitulo(itens[0])}:\n"
        f"{_listar_itens(itens)}\n\n"
        f"Liste os {quantas} itens mais provaveis para esse produto, do mais "
        "provavel para o menos provavel, sem repetir codigo. Em "
        "informacao_que_falta, escreva a pergunta que voce faria ao operador se "
        "a escolha depender de algo que a descricao nao diz (ex.: 'A cadeira e "
        "de madeira ou de metal?'), ou deixe vazio se nao faltar nada."
    )
    etapa2 = _perguntar(modelo, esquema2, pergunta2) or _perguntar(modelo, esquema2, pergunta2)
    if etapa2 is None:
        return _sem_sugestao("O modelo nao respondeu no formato esperado ao escolher os itens.")

    escolhidos: list[tuple[str, str]] = []
    for opcao in etapa2.get("opcoes", []):
        codigo = opcao.get("codigo")
        if codigo in por_codigo and codigo not in {c for c, _ in escolhidos}:
            escolhidos.append((codigo, _latino(opcao.get("justificativa")) or "(sem justificativa)"))
    # Se o modelo repetiu codigos ou devolveu menos opcoes, completa com os
    # proximos itens do capitulo na ordem da busca -- pro operador sempre
    # ter alternativas pra comparar.
    for c in itens:
        if len(escolhidos) >= quantas:
            break
        if c["codigo"] not in {cod for cod, _ in escolhidos}:
            escolhidos.append((c["codigo"], "(alternativa sugerida pela busca, sem analise do modelo)"))

    resultado = NcmSuggestion(
        opcoes=[
            OpcaoNcm(codigo=cod, descricao=_descricao_para_tela(por_codigo[cod]), justificativa=just)
            for cod, just in escolhidos[:quantas]
        ],
        interpretacao=descricao_tecnica,
        caracteristicas=caracteristicas,
        pergunta=_latino(etapa2.get("informacao_que_falta")),
        parecidos=parecidos,
        capitulos=[capitulo],
        posicoes=[c.replace(".", "")[:4] for c, _ in escolhidos[:1]],
        candidatos=[c["codigo"] for c in candidatos],
        conhecimento=[{"descricao": v["descricao"], "ncm": v["ncm"], "pontuacao": v["pontuacao"]} for v in vizinhos[:5]],
        votos_conhecimento=[(n, round(p, 2)) for n, p in votos[:5]],
    )
    if CONFIG["conhecimento_primeiro"]:
        resultado = _priorizar_conhecimento(resultado, vizinhos, votos)
    return resultado


def _priorizar_conhecimento(sugestao: NcmSuggestion, vizinhos: list[dict], votos: list) -> NcmSuggestion:
    """Se a base de conhecimento esta confiante (NCM com voto >= 2 e vizinho
    bem parecido), esse NCM vai para o 1o lugar e as opcoes do LLM seguem."""
    if not votos or votos[0][1] < 2.0 or vizinhos[0]["pontuacao"] < 8.0:
        return sugestao
    ncm = votos[0][0]
    item = _candidato_do_ncm(ncm)
    if item is None:
        return sugestao
    resto = [o for o in sugestao.opcoes if o.codigo != ncm]
    primeira = OpcaoNcm(
        codigo=ncm,
        descricao=_descricao_para_tela(item),
        justificativa=f"Outras lojas classificam produtos parecidos assim (ex.: "
        f"'{conhecimento.limpar_descricao(vizinhos[0]['descricao'])[:60]}').",
    )
    sugestao.opcoes = [primeira] + resto[: MAX_OPCOES - 1]
    return sugestao


def _descricao_para_tela(candidato: dict) -> str:
    """Os dois ultimos niveis do caminho: e a parte que diferencia uma opcao
    da outra (o cabecalho da posicao costuma ser igual nas 3 opcoes)."""
    partes = [_curto(p, 100) for p in candidato["caminho_completo"].split(" > ")[1:]]
    return " > ".join(partes[-2:]) or candidato["descricao"]
