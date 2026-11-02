"""Construcao do agente autonomo (Figura 3 do TCC): recebe o DDL do banco,
usa as ferramentas de consulta (somente leitura) para diagnosticar a
inconsistencia fiscal e propoe uma correcao estruturada. O agente nunca
executa a correcao -- isso so acontece apos aprovacao humana na interface
Streamlit, chamando src.db.firebird.execute_approved_update().
"""
import re

from langchain.agents import create_agent
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from src.agent.tools import DIAGNOSTIC_TOOLS
from src.config import ollama_config
from src.db.firebird import fetch_schema_ddl
from src.ncm.lookup import classificar_capitulo

_NCM_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}|\d{4}\.\d{1,2}|\d{2}\.\d{2}")

SYSTEM_PROMPT = """Voce e um agente de auditoria fiscal para um ERP do setor \
automotivo (Lux Auto). Sua tarefa e diagnosticar inconsistencias em \
cadastros de clientes/produtos que causam rejeicao de NF-e pela SEFAZ: \
divergencia entre Inscricao Estadual e Indicador de Contribuinte, \
classificacao incorreta de NCM, aplicacao equivocada de CST e \
preenchimento incorreto de CFOP.

Regras obrigatorias:
1. Use as ferramentas para investigar antes de concluir qualquer coisa. \
Nunca invente um NCM ou valor -- sempre confirme com \
consultar_ncm_por_codigo ou buscar_ncm_por_descricao.
2. Voce so tem acesso a ferramentas de LEITURA. Jamais responda como se \
tivesse executado uma alteracao no banco.
3. Formule o alerta final em linguagem simples e direta, sem jargao \
tecnico, como neste exemplo: "Identificamos que o NCM do produto X esta \
desatualizado. Sugerimos atualiza-lo para 1234.56.78, de acordo com a \
tabela da Receita Federal. Caso discorde, nao confirme a alteracao."
4. O comando SQL proposto deve ser um UPDATE unico, especifico (com \
WHERE pelo identificador do registro), pronto para revisao humana antes \
da execucao. Se nao houver correcao segura a propor, deixe sql_update \
como null.

Esquema do banco de dados disponivel:
{schema}
"""


class CorrectionProposal(BaseModel):
    alerta: str = Field(description="Mensagem em linguagem simples para o operador humano")
    sql_update: str | None = Field(
        default=None,
        description="Comando UPDATE unico proposto para correcao, ou null se nao houver",
    )
    confianca: str = Field(description="Confianca do diagnostico: alta, media ou baixa")


def build_agent(schema_ddl: str | None = None):
    schema_ddl = schema_ddl or fetch_schema_ddl()
    # num_ctx limitado por hardware -- ver nota em src/agent/ncm_suggester.py
    model = ChatOllama(
        base_url=ollama_config.base_url,
        model=ollama_config.model,
        temperature=0,
        num_ctx=4096,
    )
    return create_agent(
        model=model,
        tools=DIAGNOSTIC_TOOLS,
        system_prompt=SYSTEM_PROMPT.format(schema=schema_ddl),
        response_format=CorrectionProposal,
    )


def diagnose(agent, instrucao: str) -> CorrectionProposal:
    """Roda o agente sobre uma instrucao (ex.: 'verifique o cliente 4521') e
    devolve a proposta estruturada para a interface exibir ao operador.

    Modelos locais pequenos nem sempre respeitam o response_format nativo
    (as vezes "descrevem" uma chamada de ferramenta como texto em vez de
    executa-la de verdade). Por isso nunca confiamos cegamente no LLM: se a
    extracao estruturada falhar, caimos para um fallback textual em vez de
    quebrar a interface -- o operador humano sempre revisa antes de agir.
    """
    result = agent.invoke({"messages": [{"role": "user", "content": instrucao}]})
    structured = result.get("structured_response")
    if structured is not None:
        return structured

    return _fallback_proposal(result["messages"])


def _fallback_proposal(messages) -> CorrectionProposal:
    """Quando o LLM nao formula a resposta estruturada, ainda assim damos
    ao operador um roteamento util: procuramos um codigo NCM mencionado na
    conversa (instrucao do usuario, raciocinio do modelo ou resultado de
    ferramenta) e classificamos o Capitulo de forma DETERMINISTICA (sem
    depender do LLM de novo). Essa e a mesma logica que classificaria o caso
    mesmo que o agente tivesse falhado completamente -- o roteamento por
    Capitulo nao depende da IA responder."""
    last_text = ""
    capitulo_info = None
    for msg in reversed(messages):
        content = getattr(msg, "content", "") or ""
        if not last_text and content:
            last_text = content
        if capitulo_info is None:
            match = _NCM_RE.search(content)
            if match:
                capitulo_info = classificar_capitulo(match.group())
        if last_text and capitulo_info:
            break

    alerta = (
        "O agente nao conseguiu formular uma proposta estruturada de "
        "correcao. Resposta bruta do modelo, revise manualmente: "
        f"{last_text or '(sem conteudo)'}"
    )
    if capitulo_info:
        alerta += (
            f"\n\nRoteamento automatico (sem IA): Capitulo {capitulo_info['capitulo']} "
            f"- {capitulo_info['titulo']}"
        )

    return CorrectionProposal(alerta=alerta, sql_update=None, confianca="baixa")
