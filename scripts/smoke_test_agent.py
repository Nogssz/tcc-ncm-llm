"""Teste rapido: o agente consegue usar a ferramenta de NCM e devolver a
resposta estruturada (CorrectionProposal) via Ollama local? Nao depende do
Firebird -- usa so as ferramentas de NCM."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain.agents import create_agent
from langchain_ollama import ChatOllama

from src.agent.core import CorrectionProposal
from src.agent.tools import buscar_ncm_por_descricao, consultar_ncm_por_codigo
from src.config import ollama_config

model = ChatOllama(base_url=ollama_config.base_url, model=ollama_config.model, temperature=0)

agent = create_agent(
    model=model,
    tools=[consultar_ncm_por_codigo, buscar_ncm_por_descricao],
    system_prompt=(
        "Voce audita cadastros fiscais. O produto 'Para-choques' foi "
        "cadastrado com o NCM 9999.99.99, que nao existe na tabela oficial. "
        "Use buscar_ncm_por_descricao com a palavra-chave 'para-choques' "
        "para achar o NCM correto e responda com o alerta e o sql_update "
        "sugerido (UPDATE produtos SET ncm = '<codigo correto>' WHERE id = 42)."
    ),
    response_format=CorrectionProposal,
)

result = agent.invoke({"messages": [{"role": "user", "content": "Analise o produto id 42."}]})
proposta = result["structured_response"]
if proposta is None:
    print("STRUCTURED_RESPONSE VEIO NONE. Ultima mensagem do modelo:")
    for msg in reversed(result["messages"]):
        content = getattr(msg, "content", "")
        if content:
            print(content)
            break
else:
    print("ALERTA:", proposta.alerta)
    print("SQL:", proposta.sql_update)
    print("CONFIANCA:", proposta.confianca)
