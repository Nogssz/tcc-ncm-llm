"""Avaliacao da sugestao de NCM por etapa, em tres conjuntos separados:

  dev15  -- os 15 casos iniciais (scripts/eval_ncm_suggestions.py). Foram
            usados para ajustar o sistema: numero otimista.
  dev    -- conjunto de desenvolvimento novo (abaixo). E ele que deve guiar
            as melhorias a partir da Fase 1.
  teste  -- os 33 produtos cadastrados no ERP (scripts/seed_produtos_teste.py).
            NAO ajustar nada olhando para ele; rodar so para medir no fim.

Mede, por produto: o capitulo e a posicao corretos estavam entre os
escolhidos pela IA? O codigo certo ficou em 1o lugar? Entre as 3 opcoes?
Cada rodada e salva em data/avaliacoes/ (registro para os resultados do TCC).

Uso: python scripts/avaliar.py --conjunto dev [--modelo qwen2.5:7b]
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# (descricao como um operador digitaria, [NCMs aceitos], setor). Nenhum
# produto aqui aparece nos outros conjuntos nem nos exemplos dos prompts.
DEV = [
    ("BOMBA D AGUA MOTOR", ["8413.30.90"], "automotivo"),
    ("ALTERNADOR 12V", ["8511.50.10"], "automotivo"),
    ("MOTOR DE ARRANQUE", ["8511.40.00"], "automotivo"),
    ("PARABRISA DIANTEIRO", ["7007.21.00", "8708.22.00"], "automotivo"),
    ("JUNTA DO CABECOTE", ["8484.10.00"], "automotivo"),
    ("FILTRO DE OLEO", ["8421.23.00"], "automotivo"),
    ("CABO DE VELA", ["8544.30.00"], "automotivo"),
    ("EXTINTOR DE INCENDIO PO QUIMICO", ["8424.10.00"], "automotivo"),
    ("BUZINA 12V", ["8512.30.00"], "automotivo"),
    ("PNEU ARO 17 MOTO", ["4011.40.00"], "automotivo"),
    ("CAMARA DE AR BICICLETA", ["4013.20.00"], "automotivo"),
    ("FLUIDO DE FREIO DOT 4", ["3819.00.00"], "automotivo"),
    ("ADITIVO PARA RADIADOR", ["3820.00.00"], "automotivo"),
    ("ACUCAR REFINADO 1KG", ["1701.99.00"], "alimentos"),
    ("OLEO DE SOJA 900ML", ["1507.90.11"], "alimentos"),
    ("MACARRAO ESPAGUETE 500G", ["1902.19.00", "1902.11.00"], "alimentos"),
    ("BISCOITO RECHEADO CHOCOLATE", ["1905.31.00"], "alimentos"),
    ("SUCO DE UVA INTEGRAL 1L", ["2009.61.00", "2009.69.00"], "bebidas"),
    ("AGUA MINERAL SEM GAS 500ML", ["2201.10.00"], "bebidas"),
    ("VINHO TINTO SECO 750ML", ["2204.21.00"], "bebidas"),
    ("PERFUME 100ML", ["3303.00.10"], "higiene"),
    ("PAPEL TOALHA 2 ROLOS", ["4818.20.00"], "higiene"),
    ("ESCOVA DE DENTES", ["9603.21.00"], "higiene"),
    ("FRALDA DESCARTAVEL INFANTIL", ["9619.00.00"], "higiene"),
    ("MEIA DE ALGODAO", ["6115.95.00"], "vestuario"),
    ("CUECA BOXER ALGODAO", ["6107.11.00"], "vestuario"),
    ("CHINELO DE BORRACHA", ["6402.20.00"], "calcados"),
    ("FONE DE OUVIDO BLUETOOTH", ["8518.30.00"], "eletronicos"),
    ("MICROONDAS 30L", ["8516.50.00"], "eletrodomesticos"),
    ("LIQUIDIFICADOR 600W", ["8509.40.10"], "eletrodomesticos"),
    ("VENTILADOR DE MESA", ["8414.51.10"], "eletrodomesticos"),
    ("CHAVE DE FENDA", ["8205.40.00"], "ferramentas"),
    ("ALICATE UNIVERSAL", ["8203.20.10"], "ferramentas"),
    ("TRENA 5M", ["9017.80.10"], "ferramentas"),
    ("TIJOLO CERAMICO 8 FUROS", ["6904.10.00"], "construcao"),
    ("CANO PVC 100MM", ["3917.23.00"], "construcao"),
    ("FIO ELETRICO 2,5MM", ["8544.49.00"], "construcao"),
    ("LAPIS PRETO", ["9609.10.00"], "papelaria"),
    ("SOFA 3 LUGARES", ["9401.61.00", "9401.71.00"], "moveis"),
    ("BICICLETA ARO 29", ["8712.00.10"], "esporte"),
    ("RACAO PARA CAES 15KG", ["2309.10.00"], "pet"),
]


def _conjunto(nome: str) -> list[tuple[str, list[str], str]]:
    if nome == "dev":
        return DEV
    if nome == "dev15":
        from scripts.eval_ncm_suggestions import CASOS

        return CASOS
    if nome == "teste":
        from scripts.seed_produtos_teste import PRODUTOS

        return PRODUTOS
    if nome in ("dev2", "teste2", "devtudo"):
        from scripts.conjuntos_v2 import DEV2, TESTE2

        if nome == "teste2" and "--final" not in sys.argv:
            raise SystemExit("teste2 e o conjunto congelado: so rode com --final, uma vez, no fim.")
        return {"dev2": DEV2, "teste2": TESTE2, "devtudo": DEV + DEV2}[nome]
    raise SystemExit(f"Conjunto desconhecido: {nome} (use dev, dev2, devtudo, dev15, teste ou teste2)")


def aplicar_config(argv) -> dict:
    """--config chave=valor,chave=valor altera src.agent.ncm_suggester.CONFIG."""
    from src.agent import ncm_suggester

    if "--config" in argv:
        for par in argv[argv.index("--config") + 1].split(","):
            chave, valor = par.split("=")
            atual = ncm_suggester.CONFIG[chave]
            ncm_suggester.CONFIG[chave] = (valor in ("1", "true")) if isinstance(atual, bool) else type(atual)(valor)
    return dict(ncm_suggester.CONFIG)


def main():
    from src.agent.ncm_suggester import build_ncm_agent, sugerir_ncm

    config = aplicar_config(sys.argv)

    nome = sys.argv[sys.argv.index("--conjunto") + 1] if "--conjunto" in sys.argv else "dev"
    nome_modelo = sys.argv[sys.argv.index("--modelo") + 1] if "--modelo" in sys.argv else None
    casos = _conjunto(nome)
    if "--limite" in sys.argv:
        casos = casos[: int(sys.argv[sys.argv.index("--limite") + 1])]
    rotulo = sys.argv[sys.argv.index("--rotulo") + 1] if "--rotulo" in sys.argv else ""
    so_resumo = nome == "teste2"  # conjunto congelado: nao mostrar caso a caso
    modelo = build_ncm_agent(nome_modelo)
    print(f"Conjunto '{nome}': {len(casos)} produtos, modelo {modelo.model}, config {config}\n", flush=True)

    registros = []
    for descricao, esperados, grupo in casos:
        inicio = time.time()
        try:
            sugestao = sugerir_ncm(modelo, descricao, ignorar_identicos=True)
            erro = None
        except Exception as e:
            sugestao, erro = None, f"{type(e).__name__}: {str(e)[:120]}"
        segundos = round(time.time() - inicio, 1)

        if sugestao is None:
            print(f"[ ERRO INFRA ] {'(oculto)' if so_resumo else descricao}: {erro}")
            registros.append({"descricao": descricao, "esperados": esperados, "erro": erro})
            continue

        codigos = [o.codigo for o in sugestao.opcoes]
        posicao = next((codigos.index(e) + 1 for e in esperados if e in codigos), None)
        caps_certos = {e[:2] for e in esperados}
        pos_certas = {e.replace(".", "")[:4] for e in esperados}
        cap_ok = bool(caps_certos & set(sugestao.capitulos)) if sugestao.capitulos else None
        pos_ok = bool(pos_certas & set(sugestao.posicoes)) if sugestao.posicoes else None

        registros.append(
            {
                "descricao": descricao,
                "grupo": grupo,
                "esperados": esperados,
                "opcoes": codigos,
                "posicao_certo": posicao,
                "capitulo_ok": cap_ok,
                "posicao_ncm_ok": pos_ok,
                "capitulos": sugestao.capitulos,
                "posicoes": sugestao.posicoes,
                "interpretacao": sugestao.interpretacao,
                "pergunta": sugestao.pergunta,
                "busca_tem_certo": any(e in sugestao.candidatos for e in esperados),
                "segundos": segundos,
            }
        )
        marca = f"OK {posicao}o" if posicao else "ERROU"
        if so_resumo:
            print(".", end="", flush=True)
            continue
        print(f"[{marca:>6}] {descricao} ({segundos:.0f}s)  cap={'ok' if cap_ok else 'X' if cap_ok is False else '-'}"
              f" pos={'ok' if pos_ok else 'X' if pos_ok is False else '-'}"
              f" busca={'ok' if registros[-1]['busca_tem_certo'] else 'X'}", flush=True)
        if not posicao:
            print(f"         opcoes {codigos} | esperado {esperados} | caps {sugestao.capitulos} | {sugestao.interpretacao}",
                  flush=True)

    avaliados = [r for r in registros if "erro" not in r]
    n = max(len(avaliados), 1)

    def taxa(chave, cond):
        valores = [r for r in avaliados if r.get(chave) is not None]
        acertos = sum(1 for r in valores if cond(r[chave]))
        return f"{acertos}/{len(valores)} = {100 * acertos / max(len(valores), 1):.1f}%" if valores else "-"

    top1 = sum(1 for r in avaliados if r["posicao_certo"] == 1)
    top3 = sum(1 for r in avaliados if r["posicao_certo"])
    resumo = {
        "capitulo_certo_entre_escolhidos": taxa("capitulo_ok", bool),
        "posicao_certa_entre_escolhidas": taxa("posicao_ncm_ok", bool),
        "acerto_1o_lugar": f"{top1}/{len(avaliados)} = {100 * top1 / n:.1f}%",
        "acerto_top3": f"{top3}/{len(avaliados)} = {100 * top3 / n:.1f}%",
        "tempo_medio_s": round(sum(r["segundos"] for r in avaliados) / n, 1),
        "falhas_infra": len(registros) - len(avaliados),
        "busca_tem_certo": taxa("busca_tem_certo", bool),
    }
    print()
    for chave, valor in resumo.items():
        print(f"{chave}: {valor}")

    saida = BASE / "data" / "avaliacoes"
    saida.mkdir(parents=True, exist_ok=True)
    arquivo = saida / f"{nome}_{rotulo + '_' if rotulo else ''}{datetime.now():%Y%m%d_%H%M%S}.json"
    arquivo.write_text(
        json.dumps({"conjunto": nome, "modelo": modelo.model, "rotulo": rotulo, "config": config, "resumo": resumo, "casos": registros},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSalvo em {arquivo.relative_to(BASE)}")


if __name__ == "__main__":
    main()
