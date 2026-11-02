"""Cadastra no ERP (tabela PRODUTO do Firebird) produtos de teste de varios
setores, todos com NCM '00000000' -- simulando o operador que cadastrou sem
NCM. Serve pra testar o fluxo real: deteccao -> sugestao da IA -> aprovacao
no Streamlit.

Cada produto tem o NCM correto esperado (gabarito), conferido manualmente na
tabela oficial (data/ncm.db). Casos genuinamente ambiguos aceitam mais de um
codigo (ex.: notebook de 15" depende da area exata da tela).

Os produtos sao copiados do modelo de um produto ja criado pelo proprio ERP
(o mais recente de mercadoria), trocando so codigo, descricao, referencia,
NCM e data -- assim ficam iguais a um cadastro feito pela tela do sistema.
O codigo vem do mesmo gerador que o ERP usa (GEN_PRODUTO_CODIGO).

Uso:
  python scripts/seed_produtos_teste.py            # cadastra (pula os que ja existem)
  python scripts/seed_produtos_teste.py --avaliar  # roda a IA em cada um e compara com o gabarito
"""
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.firebird import get_connection  # noqa: E402

# (descricao como um operador digitaria, [NCMs aceitos], setor)
PRODUTOS = [
    ("ARROZ BRANCO TIPO 1 5KG", ["1006.30.21"], "alimentos"),
    ("CAFE TORRADO E MOIDO 500G", ["0901.21.00"], "alimentos"),
    ("REFRIGERANTE COLA 2L", ["2202.10.00"], "bebidas"),
    ("CERVEJA LATA 350ML", ["2203.00.00"], "bebidas"),
    ("LEITE UHT INTEGRAL 1L", ["0401.20.10"], "alimentos"),
    ("CHOCOLATE AO LEITE BARRA 90G", ["1806.32.10"], "alimentos"),
    ("DETERGENTE LIQUIDO LAVA LOUCAS 500ML", ["3402.50.00"], "limpeza"),
    ("SABONETE EM BARRA 90G", ["3401.11.90"], "higiene"),
    ("SHAMPOO ANTICASPA 350ML", ["3305.10.00"], "higiene"),
    ("CREME DENTAL 90G", ["3306.10.00"], "higiene"),
    ("PAPEL HIGIENICO FOLHA DUPLA 12 ROLOS", ["4818.10.00"], "higiene"),
    ("CAMISETA ALGODAO MASCULINA", ["6109.10.00"], "vestuario"),
    ("CALCA JEANS FEMININA", ["6204.62.00"], "vestuario"),
    ("TENIS ESPORTIVO", ["6404.11.00", "6402.19.00"], "calcados"),
    ("TOALHA DE BANHO ALGODAO", ["6302.60.00"], "cama mesa banho"),
    ("CELULAR SMARTPHONE 128GB", ["8517.13.00"], "eletronicos"),
    ("NOTEBOOK 15 POLEGADAS", ["8471.30.12", "8471.30.19"], "eletronicos"),
    ("GELADERA FROST FREE DUPLEX", ["8418.10.00"], "eletrodomesticos"),  # erro de digitacao proposital
    ("LAMPADA LED 9W", ["8539.52.00"], "eletricos"),
    ("PILHA ALCALINA AA", ["8506.10.19"], "eletricos"),
    ("MARTELO DE UNHA CABO MADEIRA", ["8205.20.00"], "ferramentas"),
    ("FURADERA ELETRICA 500W", ["8467.21.00"], "ferramentas"),  # erro de digitacao proposital
    ("CIMENTO PORTLAND 50KG", ["2523.29.10"], "construcao"),
    ("TINTA ACRILICA PAREDE 18L", ["3209.10.10"], "construcao"),
    ("PARAFUSO SEXTAVADO ACO M8", ["7318.15.00"], "ferragens"),
    ("CADERNO ESPIRAL 96 FOLHAS", ["4820.20.00"], "papelaria"),
    ("CANETA ESFEROGRAFICA AZUL", ["9608.10.00"], "papelaria"),
    ("CADEIRA DE ESCRITORIO GIRATORIA", ["9401.31.00", "9401.39.00"], "moveis"),
    ("BOLA DE FUTEBOL", ["9506.62.00"], "esporte"),
    ("FILTRO DE AR DO MOTOR", ["8421.31.00"], "automotivo"),
    ("OLEO MOTOR 5W30 1L", ["2710.19.32"], "automotivo"),
    ("LAMPADA FAROL H4 12V", ["8539.21.10"], "automotivo"),
    ("BATERIA 60AH 12V", ["8507.10.90"], "automotivo"),
]


def cadastrar():
    con = get_connection()
    cur = con.cursor()

    cur.execute("SELECT DESCRICAO FROM PRODUTO")
    existentes = {r[0].strip() for r in cur.fetchall() if r[0]}

    cur.execute(
        "SELECT FIRST 1 * FROM PRODUTO WHERE SERVICO = 'N' ORDER BY CODIGO DESC"
    )
    colunas = [d[0].strip() for d in cur.description]
    modelo = dict(zip(colunas, cur.fetchone()))
    modelo.pop("FOTO", None)

    criados = []
    for descricao, _, setor in PRODUTOS:
        if descricao in existentes:
            print(f"  ja existe, pulando: {descricao}")
            continue
        cur.execute("SELECT GEN_ID(GEN_PRODUTO_CODIGO, 1) FROM RDB$DATABASE")
        codigo = cur.fetchone()[0]
        linha = dict(modelo)
        linha.update(
            CODIGO=codigo,
            REFERENCIA=str(codigo),
            DESCRICAO=descricao,
            NCM="00000000",
            DT_CADASTRO=date.today(),
        )
        nomes = ", ".join(linha)
        marcadores = ", ".join("?" * len(linha))
        cur.execute(f"INSERT INTO PRODUTO ({nomes}) VALUES ({marcadores})", tuple(linha.values()))
        criados.append((codigo, descricao, setor))

    con.commit()
    con.close()

    for codigo, descricao, setor in criados:
        print(f"  #{codigo:<4} {descricao}  [{setor}]")
    print(f"\n{len(criados)} produto(s) cadastrado(s).")


def avaliar():
    """Roda o fluxo real: pega os produtos com NCM invalido direto do ERP e
    pede a sugestao da IA pra cada um -- o mesmo que clicar em 'Pedir
    sugestao' no Streamlit, mas em lote e comparando com o gabarito."""
    from src.agent.ncm_suggester import build_ncm_agent, sugerir_ncm
    from src.db.produtos import listar_produtos_ncm_invalido

    gabarito = {d: (esperados, setor) for d, esperados, setor in PRODUTOS}
    detectados = [p for p in listar_produtos_ncm_invalido() if p["DESCRICAO"].strip() in gabarito]
    print(f"Detectados com NCM invalido no ERP: {len(detectados)}/{len(PRODUTOS)} produtos de teste\n")

    modelo = build_ncm_agent()
    top1, top3, total = 0, 0, 0
    por_setor: dict[str, list[bool]] = {}
    for p in detectados:
        descricao = p["DESCRICAO"].strip()
        esperados, setor = gabarito[descricao]
        inicio = time.time()
        try:
            sugestao = sugerir_ncm(modelo, descricao, codigo_produto=p["CODIGO"], ignorar_identicos=True)
        except Exception as e:
            print(f"[ ERRO INFRA ] #{p['CODIGO']} {descricao}: {type(e).__name__}\n")
            continue
        codigos = [o.codigo for o in sugestao.opcoes]
        posicao = next((codigos.index(e) + 1 for e in esperados if e in codigos), None)
        total += 1
        top1 += posicao == 1
        top3 += posicao is not None
        por_setor.setdefault(setor, []).append(posicao is not None)
        status = f"OK {posicao}o" if posicao else "ERROU"
        print(f"[{status:>6}] #{p['CODIGO']} {descricao} ({time.time() - inicio:.0f}s)")
        print(f"         IA: {codigos}  |  gabarito: {esperados}")
        if not posicao:
            print(f"         {sugestao.observacao or sugestao.opcoes[0].justificativa}"[:190])

    print(f"\nAcerto em 1o lugar: {top1}/{total} = {100 * top1 / max(total, 1):.1f}%")
    print(f"Acerto entre as 3 opcoes: {top3}/{total} = {100 * top3 / max(total, 1):.1f}%")
    print("Top-3 por setor:", ", ".join(f"{s} {sum(v)}/{len(v)}" for s, v in sorted(por_setor.items())))


def avaliar_busca():
    """So a etapa de busca (sem a escolha final): o codigo certo esta entre
    os candidatos entregues ao LLM? Separa erro de busca de erro de escolha."""
    from src.agent.ncm_suggester import build_ncm_agent, buscar_candidatos

    modelo = build_ncm_agent()
    achou = 0
    for descricao, esperados, _ in PRODUTOS:
        candidatos, tecnica = buscar_candidatos(modelo, descricao)
        codigos = [c["codigo"] for c in candidatos]
        posicao = next((codigos.index(e) + 1 for e in esperados if e in codigos), None)
        achou += posicao is not None
        status = f"pos {posicao}" if posicao else "FORA"
        print(f"{status:>7}  {descricao}  ->  {tecnica}")
    print(f"\nBusca trouxe o codigo certo: {achou}/{len(PRODUTOS)}")


if __name__ == "__main__":
    if "--avaliar" in sys.argv:
        avaliar()
    elif "--busca" in sys.argv:
        avaliar_busca()
    else:
        cadastrar()
