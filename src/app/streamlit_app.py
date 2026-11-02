"""Interface de supervisao Human-in-the-Loop (Figura 3 do TCC).
Roda como app independente, conectada ao mesmo banco do ERP, sem alterar o
codigo-fonte do Lux Auto. Execute com: streamlit run src/app/streamlit_app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.agent.core import build_agent, diagnose
from src.db.firebird import execute_approved_update

st.set_page_config(page_title="Auditoria Fiscal - Lux Auto", page_icon="🔎")
st.title("Agente de Auditoria Fiscal")
st.caption("Identificacao e correcao supervisionada de inconsistencias fiscais (NCM, CST, CFOP)")


@st.cache_resource
def get_agent():
    return build_agent()


instrucao = st.text_area(
    "O que verificar?",
    placeholder="Ex.: verifique o cadastro do cliente 4521 que teve a NF-e rejeitada",
)

if st.button("Analisar", type="primary", disabled=not instrucao.strip()):
    with st.spinner("Agente investigando o cadastro..."):
        agent = get_agent()
        proposta = diagnose(agent, instrucao)
        st.session_state["proposta"] = proposta

proposta = st.session_state.get("proposta")
if proposta:
    st.divider()
    st.subheader("Diagnostico")
    st.info(proposta.alerta)
    st.caption(f"Confianca do agente: {proposta.confianca}")

    if proposta.sql_update:
        with st.expander("Detalhes tecnicos da correcao proposta"):
            st.code(proposta.sql_update, language="sql")

        col1, col2 = st.columns(2)
        if col1.button("Aprovar e aplicar correcao", type="primary"):
            try:
                afetadas = execute_approved_update(proposta.sql_update)
                st.success(f"Correcao aplicada. {afetadas} registro(s) atualizado(s).")
                del st.session_state["proposta"]
            except ValueError as e:
                st.error(f"Correcao bloqueada pelo guardrail: {e}")
        if col2.button("Rejeitar"):
            st.warning("Correcao rejeitada. Nenhuma alteracao foi feita.")
            del st.session_state["proposta"]
    else:
        st.warning("O agente nao encontrou uma correcao segura para propor.")
