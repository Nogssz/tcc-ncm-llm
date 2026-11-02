"""Tela de supervisao (Human-in-the-Loop) do NCM: produtos (mercadorias)
cadastrados no Lux Auto com NCM invalido/vazio sao detectados, a IA sugere
as 3 opcoes de NCM mais provaveis, e um humano escolhe e aprova antes de
qualquer UPDATE rodar. Uma segunda secao lista produtos com NCM valido, mas
possivelmente errado, apontados pelo worker (src.agent.ncm_verificador).

Se o worker estiver rodando (scripts/worker_sugestoes.py), a sugestao ja
aparece pronta; senao, o operador pede pelo botao.

Rodar com: streamlit run src/app/ncm_dashboard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.agent.ncm_suggester import NcmSuggestion, build_ncm_agent, sugerir_ncm
from src.agent.ncm_verificador import VerificacaoNcm, caminho_legivel
from src.db import cache_sugestoes
from src.db.firebird import execute_approved_update
from src.db.produtos import listar_produtos_ncm_invalido, listar_produtos_ncm_valido

st.set_page_config(page_title="NCM - Lux Auto", page_icon="🏷️")
st.title("Produtos com NCM invalido")
st.caption(
    "Deteccao automatica (sem IA) + sugestao de correcao por IA, com "
    "aprovacao humana obrigatoria antes de aplicar no banco."
)


@st.cache_resource
def get_agent():
    return build_ncm_agent()


def _descartar_sugestao(codigo: int) -> None:
    st.session_state.pop(f"sugestao_{codigo}", None)
    cache_sugestoes.remover(codigo)


def _mostrar_sugestao(codigo: int, sugestao: NcmSuggestion, gerada_em: str | None) -> None:
    if gerada_em:
        st.caption(f"⚡ Sugestao gerada automaticamente em {gerada_em}.")
    if sugestao.interpretacao:
        texto = f"A IA entendeu o produto como: *{sugestao.interpretacao}*"
        if sugestao.caracteristicas:
            texto += f"  \nCaracteristicas consideradas: {sugestao.caracteristicas}"
        st.caption(texto)
    if sugestao.parecidos:
        st.caption(
            "Produtos parecidos ja cadastrados: "
            + "; ".join(f"{p['descricao']} → {p['ncm']}" for p in sugestao.parecidos)
        )
    if sugestao.pergunta:
        st.warning(f"A IA precisa saber: **{sugestao.pergunta}** Confira antes de escolher.")

    st.write("Opcoes sugeridas (da mais para a menos provavel) -- escolha uma:")
    rotulos = {f"{i}. {o.codigo} — {o.descricao}": o for i, o in enumerate(sugestao.opcoes, start=1)}
    escolha = st.radio("Opcao", list(rotulos), key=f"escolha_{codigo}", label_visibility="collapsed")
    st.caption(f"Justificativa: {rotulos[escolha].justificativa}")

    col1, col2 = st.columns(2)
    if col1.button("✅ Aplicar opcao escolhida", key=f"aprova_{codigo}", type="primary"):
        novo_ncm_erp = rotulos[escolha].codigo.replace(".", "")
        try:
            execute_approved_update("UPDATE PRODUTO SET NCM = ? WHERE CODIGO = ?", (novo_ncm_erp, codigo))
            st.toast(f"NCM do produto #{codigo} atualizado para {novo_ncm_erp}.")
            _descartar_sugestao(codigo)
            st.session_state["produtos"] = listar_produtos_ncm_invalido()
            st.rerun()
        except ValueError as e:
            st.error(f"Bloqueado pelo guardrail: {e}")
    if col2.button("🔁 Nenhuma serve -- sugerir de novo", key=f"rejeita_{codigo}"):
        _descartar_sugestao(codigo)
        st.rerun()


if st.button("🔄 Atualizar lista"):
    st.session_state.pop("produtos", None)
    st.session_state.pop("validos", None)

if "produtos" not in st.session_state:
    with st.spinner("Consultando o ERP..."):
        st.session_state["produtos"] = listar_produtos_ncm_invalido()

produtos = st.session_state["produtos"]

if not produtos:
    st.success("Nenhum produto com NCM invalido encontrado no momento.")
else:
    st.warning(f"{len(produtos)} produto(s) com NCM invalido ou vazio.")

    for p in produtos:
        codigo, descricao, ncm_atual = p["CODIGO"], (p["DESCRICAO"] or "").strip(), p["NCM"]
        chave = f"sugestao_{codigo}"

        with st.container(border=True):
            st.write(f"**#{codigo} — {descricao}**")
            st.caption(f"NCM atual no ERP: `{ncm_atual or '(vazio)'}`")

            gerada_em = None
            if chave not in st.session_state:
                em_cache = cache_sugestoes.buscar(codigo, descricao)
                if em_cache:
                    st.session_state[chave] = NcmSuggestion.model_validate(em_cache[0])
                    gerada_em = em_cache[1]

            if chave not in st.session_state:
                if st.button("🤖 Pedir sugestao da IA", key=f"btn_{codigo}"):
                    with st.spinner("IA analisando o produto e buscando o NCM..."):
                        try:
                            sugestao = sugerir_ncm(get_agent(), descricao, codigo_produto=codigo)
                            st.session_state[chave] = sugestao
                            cache_sugestoes.salvar(codigo, descricao, sugestao.model_dump())
                        except Exception as e:
                            st.session_state[chave] = None
                            st.session_state[f"erro_{codigo}"] = str(e)
                    st.rerun()
                continue

            sugestao = st.session_state[chave]
            if sugestao is None:
                st.error(
                    "A IA local (Ollama) falhou ao responder -- isso e uma instabilidade de "
                    f"infraestrutura, nao do produto em si. Detalhe tecnico: "
                    f"{st.session_state.get(f'erro_{codigo}', 'erro desconhecido')}"
                )
                if st.button("Tentar de novo", key=f"retry_erro_{codigo}"):
                    _descartar_sugestao(codigo)
                    st.rerun()
            elif sugestao.opcoes:
                _mostrar_sugestao(codigo, sugestao, gerada_em)
            else:
                st.error(sugestao.observacao or "A IA nao encontrou uma sugestao.")
                if st.button("Tentar de novo", key=f"retry_{codigo}"):
                    _descartar_sugestao(codigo)
                    st.rerun()


# ---------------------------------------------------------------------------
# NCM válido, mas possivelmente errado (verificado pelo worker)
# ---------------------------------------------------------------------------
st.divider()
st.header("NCM possivelmente errado")
st.caption(
    "Produtos com um NCM que existe na tabela, mas que a IA acha que é de outro tipo de "
    "produto (ex.: cadastro feito copiando outro produto). Confira antes de alterar."
)

if "validos" not in st.session_state:
    st.session_state["validos"] = {p["CODIGO"]: p for p in listar_produtos_ncm_valido()}
validos = st.session_state["validos"]
# Só mostra se o produto ainda está do jeito que foi verificado no ERP.
suspeitos = [
    s for s in cache_sugestoes.listar_suspeitos()
    if s["codigo"] in validos
    and (validos[s["codigo"]]["DESCRICAO"] or "").strip() == s["descricao"]
    and (validos[s["codigo"]]["NCM"] or "").strip() == s["ncm"]
]

if not suspeitos:
    st.success("Nenhum NCM suspeito entre os produtos já verificados.")
for s in suspeitos:
    v = VerificacaoNcm.model_validate(s["verificacao"])
    codigo = s["codigo"]
    with st.container(border=True):
        st.write(f"**#{codigo} — {s['descricao']}**")
        st.write(f"NCM atual: `{v.ncm_cadastrado}` — {caminho_legivel(v.ncm_cadastrado, 120)}")
        st.warning(f"⚠️ {v.motivo}")
        sugestao = v.sugestao
        if not sugestao or not sugestao.opcoes:
            st.caption("A IA não conseguiu sugerir outra classificação.")
            continue
        if sugestao.interpretacao:
            st.caption(f"A IA entendeu o produto como: *{sugestao.interpretacao}*")
        rotulos = {f"{i}. {o.codigo} — {o.descricao}": o for i, o in enumerate(sugestao.opcoes, start=1)}
        escolha = st.radio("Opção", list(rotulos), key=f"susp_escolha_{codigo}", label_visibility="collapsed")
        st.caption(f"Justificativa: {rotulos[escolha].justificativa}")
        col1, col2 = st.columns(2)
        if col1.button("✅ Trocar pelo NCM escolhido", key=f"susp_aplica_{codigo}", type="primary"):
            novo = rotulos[escolha].codigo.replace(".", "")
            try:
                execute_approved_update("UPDATE PRODUTO SET NCM = ? WHERE CODIGO = ?", (novo, codigo))
                st.toast(f"NCM do produto #{codigo} alterado para {novo}.")
                st.session_state.pop("validos", None)
                st.rerun()
            except ValueError as e:
                st.error(f"Bloqueado pelo guardrail: {e}")
        if col2.button("👍 O NCM atual está certo", key=f"susp_ok_{codigo}"):
            cache_sugestoes.marcar_confirmado(codigo, s["descricao"], s["ncm"])
            st.rerun()
