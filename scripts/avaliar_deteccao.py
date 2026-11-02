"""Avaliação da detecção de NCM errado (código válido, mas de outro produto).

Para cada produto do conjunto, gera um caso com o NCM certo e um com NCM
errado (ver scripts/conjuntos_v2.casos_deteccao). A sugestão é calculada uma
vez por produto e reaproveitada nos dois casos. Todas as perguntas de
verificação são feitas sempre (sempre_perguntar=True), para que várias
regras de decisão possam ser comparadas sem rodar o modelo de novo.

Métrica principal: acurácia = casos classificados corretamente / total
(metade dos casos é correta, metade errada). Também: taxa de alarme falso
(NCM certo apontado como suspeito) e taxa de detecção por tipo de erro.

Uso: python scripts/avaliar_deteccao.py --conjunto dev2 [--limite N] [--rotulo x]
     python scripts/avaliar_deteccao.py --conjunto teste2 --final   (uma vez, no fim)
"""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def regras():
    """Regras candidatas: recebem o registro de sinais e devolvem True = suspeito."""
    def comp_contra(r):
        return r["preferido_comparacao"] not in (r["ncm_cadastrado"], "empate", None)

    return {
        "fora_top3": lambda r: not r["em_top3"],
        "fora_posicao": lambda r: not r["mesma_posicao"],
        "fora_capitulo": lambda r: not r["mesmo_capitulo"],
        "abs_incompativel": lambda r: r["veredito_absoluto"] == "incompativel",
        "abs_nao_compativel": lambda r: r["veredito_absoluto"] in ("incompativel", "duvida"),
        "comparacao_contra": comp_contra,
        "fora_top3_e_comp": lambda r: not r["em_top3"] and comp_contra(r),
        "fora_top3_e_abs": lambda r: not r["em_top3"] and r["veredito_absoluto"] == "incompativel",
        "fora_top3_e_(abs_ou_comp)": lambda r: not r["em_top3"] and (r["veredito_absoluto"] == "incompativel" or comp_contra(r)),
        "fora_posicao_ou_(fora_top3_e_abs)": lambda r: (not r["mesma_posicao"]) or (not r["em_top3"] and r["veredito_absoluto"] == "incompativel"),
        # --- com a base de conhecimento (votos dos parecidos de outras lojas)
        "conhec_contra": lambda r: r["conhecimento_peso_top"] >= 2.0 and r["conhecimento_peso_cadastrado"] == 0,
        "fora_top3_e_conhec_contra": lambda r: not r["em_top3"] and r["conhecimento_peso_cadastrado"] == 0
        and r["conhecimento_peso_top"] >= 1.0,
        "fora_top3_e_(abs_ou_conhec)": lambda r: not r["em_top3"] and (
            r["veredito_absoluto"] == "incompativel"
            or (r["conhecimento_peso_top"] >= 2.0 and r["conhecimento_peso_cadastrado"] == 0)),
        "fora_top3_e_(abs_ou_comp_ou_conhec)": lambda r: not r["em_top3"] and (
            r["veredito_absoluto"] == "incompativel" or comp_contra(r)
            or (r["conhecimento_peso_top"] >= 2.0 and r["conhecimento_peso_cadastrado"] == 0)),
        "decidir_atual": None,  # preenchido abaixo, usa a regra do módulo
    }


def medir(registros, regra):
    acertos, falsos, det = 0, 0, defaultdict(lambda: [0, 0])
    for r in registros:
        suspeito = regra(r)
        acertos += suspeito == r["ncm_errado"]
        if not r["ncm_errado"]:
            falsos += suspeito
        det[r["tipo"]][0] += suspeito
        det[r["tipo"]][1] += 1
    n = len(registros)
    corretos = sum(1 for r in registros if not r["ncm_errado"])
    return {
        "acuracia": round(100 * acertos / n, 1),
        "alarme_falso": round(100 * falsos / max(corretos, 1), 1),
        **{f"det_{t}": f"{v[0]}/{v[1]}" for t, v in sorted(det.items()) if t != "correto"},
    }


def casos_loja_b(arquivo: Path, n_cada: int = 40) -> list[dict]:
    """Erros REAIS: produtos da Loja B com 8708.10.00 (para-choques) que
    não são para-choques, contra produtos comuns da mesma loja (presumidos
    corretos). Lê a base do cliente só para leitura."""
    import random

    import firebird.driver as fb

    import src.db.firebird  # noqa: F401  (fbclient 64 bits)
    from src.config import firebird_config
    from src.ncm import conhecimento
    from src.ncm.lookup import ncm_valido, normalizar_codigo_erp

    fb.driver_config.db_defaults.utf8filename.value = True
    con = fb.connect(f"{firebird_config.host}/{firebird_config.port}:{arquivo.resolve()}",
                     user=firebird_config.user, password=firebird_config.password)
    cur = con.cursor()
    cur.execute("SELECT DESCRICAO, NCM FROM PRODUTO WHERE SERVICO = 'N'")
    linhas = [((d or "").strip(), normalizar_codigo_erp((n or "").strip())) for d, n in cur.fetchall()
              if d and ncm_valido((n or "").strip())]
    con.close()
    rng = random.Random(2026)
    errados = [x for x in linhas if not conhecimento.confiavel(*x)]
    certos = [x for x in linhas if x[1] != "8708.10.00"]
    rng.shuffle(errados)
    rng.shuffle(certos)
    casos = [{"descricao": d, "ncm_cadastrado": n, "ncm_errado": True, "tipo": "coringa", "aceitos": [], "setor": "real"}
             for d, n in errados[:n_cada]]
    casos += [{"descricao": d, "ncm_cadastrado": n, "ncm_errado": False, "tipo": "correto", "aceitos": [n], "setor": "real"}
              for d, n in certos[:n_cada]]
    return casos


def main():
    from scripts.conjuntos_v2 import DEV2, TESTE2, casos_deteccao
    from src.agent.ncm_suggester import build_ncm_agent, sugerir_ncm
    from src.agent.ncm_verificador import VerificacaoNcm, decidir, verificar_ncm

    from scripts.avaliar import aplicar_config

    config = aplicar_config(sys.argv)
    nome = sys.argv[sys.argv.index("--conjunto") + 1]
    if nome == "teste2" and "--final" not in sys.argv:
        raise SystemExit("teste2 e congelado: rode com --final, uma vez, no fim.")
    if nome == "loja_b":  # --conjunto loja_b --arquivo basesProduto/<base da loja>.fdb
        casos = casos_loja_b(Path(sys.argv[sys.argv.index("--arquivo") + 1]))
    else:
        conjunto = {"dev2": DEV2, "teste2": TESTE2}[nome]
        if "--limite" in sys.argv:
            conjunto = conjunto[: int(sys.argv[sys.argv.index("--limite") + 1])]
        casos = casos_deteccao(conjunto)
    rotulo = sys.argv[sys.argv.index("--rotulo") + 1] if "--rotulo" in sys.argv else ""
    so_resumo = nome == "teste2"
    modelo = build_ncm_agent(sys.argv[sys.argv.index("--modelo") + 1] if "--modelo" in sys.argv else None)

    sugestoes = {}
    registros = []
    for caso in casos:
        inicio = time.time()
        descricao = caso["descricao"]
        try:
            if descricao not in sugestoes:
                sugestoes[descricao] = sugerir_ncm(modelo, descricao, ignorar_identicos=True)
            v = verificar_ncm(modelo, descricao, caso["ncm_cadastrado"].replace(".", ""),
                              sugestao=sugestoes[descricao], sempre_perguntar=True)
        except Exception as e:
            print(f"[ERRO INFRA] {type(e).__name__}: {str(e)[:100]}")
            continue
        r = {**caso, "em_top3": v.em_top3, "mesma_posicao": v.mesma_posicao, "mesmo_capitulo": v.mesmo_capitulo,
             "veredito_absoluto": v.veredito_absoluto, "preferido_comparacao": v.preferido_comparacao,
             "opcoes": [o.codigo for o in v.sugestao.opcoes], "segundos": round(time.time() - inicio, 1),
             "conhecimento_top": v.conhecimento_top, "conhecimento_peso_top": v.conhecimento_peso_top,
             "conhecimento_peso_cadastrado": v.conhecimento_peso_cadastrado}
        r["decidir_atual"] = decidir(VerificacaoNcm(status="", ncm_cadastrado=v.ncm_cadastrado, em_top3=v.em_top3,
                                                    mesma_posicao=v.mesma_posicao, mesmo_capitulo=v.mesmo_capitulo,
                                                    veredito_absoluto=v.veredito_absoluto,
                                                    preferido_comparacao=v.preferido_comparacao))[0]
        registros.append(r)
        if so_resumo:
            print(".", end="", flush=True)
        else:
            print(f"[{'ERRADO' if r['ncm_errado'] else 'certo '} {r['tipo']:>8}] {descricao[:38]:38} {r['ncm_cadastrado']} "
                  f"top3={int(r['em_top3'])} pos={int(r['mesma_posicao'])} cap={int(r['mesmo_capitulo'])} "
                  f"abs={r['veredito_absoluto']} comp={'cad' if r['preferido_comparacao'] == r['ncm_cadastrado'] else r['preferido_comparacao']} "
                  f"conhec={r['conhecimento_top']}({r['conhecimento_peso_top']:.1f}) cad={r['conhecimento_peso_cadastrado']:.1f}",
                  flush=True)

    print()
    tabela = {}
    for nome_regra, regra in regras().items():
        if regra is None:
            regra = lambda r: r["decidir_atual"]  # noqa: E731
        tabela[nome_regra] = medir(registros, regra)
        print(f"{nome_regra:36} {tabela[nome_regra]}")
    print(f"tempo medio por caso: {sum(r['segundos'] for r in registros) / max(len(registros), 1):.1f}s")

    saida = BASE / "data" / "avaliacoes"
    saida.mkdir(parents=True, exist_ok=True)
    arquivo = saida / f"deteccao_{nome}_{rotulo + '_' if rotulo else ''}{datetime.now():%Y%m%d_%H%M%S}.json"
    arquivo.write_text(json.dumps({"conjunto": nome, "modelo": modelo.model, "rotulo": rotulo, "config": config, "regras": tabela,
                                   "casos": registros}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Salvo em {arquivo.relative_to(BASE)}")


if __name__ == "__main__":
    main()
