"""Conjuntos da segunda rodada de avaliação (out. 2026).

POOL tem 99 produtos novos (nenhum aparece em dev15, dev ou teste), com
cerca de um terço de peças e itens automotivos, porque o ERP atende
oficinas. Algumas descrições foram escritas abreviadas, como o operador
digita ("CIL MESTRE FREIO", "PIVO SUSP INF").

A divisão em DEV2 e TESTE2 é feita por sorteio com semente fixa,
estratificado (automotivo / demais), para que nenhum caso seja escolhido a
dedo para o teste. TESTE2 é congelado (ver congelar_teste2) e só deve ser
medido no fim; DEV2 orienta as melhorias.

Gabaritos conferidos na tabela NCM vigente (data/ncm.db). Quando a
descrição admite mais de um código, todos os plausíveis são aceitos.
"""
import hashlib
import json
import random

# (descricao, [NCMs aceitos], setor)
POOL = [
    # --- automotivo ---
    ("PASTILHA DE FREIO DIANTEIRA CERAMICA", ["8708.30.19"], "automotivo"),
    ("CIL MESTRE FREIO", ["8708.30.90"], "automotivo"),
    ("TERMINAL DE DIRECAO LD", ["8708.94.90", "8708.80.00"], "automotivo"),
    ("BIELETA BARRA ESTABILIZADORA", ["8708.80.00"], "automotivo"),
    ("PIVO SUSP INF", ["8708.80.00"], "automotivo"),
    ("ROLAM RODA DIANT", ["8482.10.10", "8482.10.90"], "automotivo"),
    ("BOMBA COMBUSTIVEL ELETRICA FLEX", ["8413.30.10"], "automotivo"),
    ("SONDA LAMBDA", ["9027.10.00"], "automotivo"),
    ("BOBINA DE IGNICAO", ["8511.30.20"], "automotivo"),
    ("RELE AUXILIAR 12V 4 TERMINAIS", ["8536.41.00"], "automotivo"),
    ("FUSIVEL LAMINA 10A", ["8536.10.00"], "automotivo"),
    ("PALHETA LIMPADOR PARABRISA 20 POL", ["8512.90.00"], "automotivo"),
    ("MANG SUP RADIADOR", ["4009.31.00", "4009.32.10", "4009.32.90", "8708.91.00"], "automotivo"),
    ("FILTRO DE COMBUSTIVEL", ["8421.23.00"], "automotivo"),
    ("FILTRO AR COND CABINE", ["8421.39.90"], "automotivo"),
    ("CALOTA ARO 14", ["8708.70.90"], "automotivo"),
    ("MACACO HIDRAULICO GARRAFA 2T", ["8425.42.00"], "automotivo"),
    ("CHAVE DE RODA CRUZ", ["8204.11.00"], "automotivo"),
    ("TAPETE AUTOMOTIVO BORRACHA JOGO", ["4016.91.00"], "automotivo"),
    ("RETENTOR VIRABREQUIM", ["4016.93.00"], "automotivo"),
    ("ARRUELA LISA ACO 10MM", ["7318.22.00"], "automotivo"),
    ("JOGO DE ANEIS DE SEGMENTO", ["8409.91.16"], "automotivo"),
    ("PISTAO MOTOR STD", ["8409.91.20"], "automotivo"),
    ("BRONZINA DE BIELA", ["8483.30.90", "8409.91.90"], "automotivo"),
    ("CORREIA DO ALTERNADOR", ["4010.31.00", "4010.32.00", "4010.33.00", "4010.34.00"], "automotivo"),
    ("LAMPADA PINGO 12V 5W", ["8539.29.10"], "automotivo"),
    ("SILENCIOSO TRASEIRO ESCAPAMENTO", ["8708.92.00"], "automotivo"),
    ("TAMPA DO RADIADOR", ["8708.91.00"], "automotivo"),
    ("CERA AUTOMOTIVA PASTA", ["3405.30.00"], "automotivo"),
    ("PNEU 175/70 R14", ["4011.10.00"], "automotivo"),
    ("PARAFUSO DE RODA", ["7318.15.00"], "automotivo"),
    ("PORCA SEXTAVADA M10", ["7318.16.00"], "automotivo"),
    ("CHAVE COMBINADA 13MM", ["8204.11.00"], "automotivo"),
    ("SOQUETE ENCAIXE 1/2 10MM", ["8204.20.00"], "automotivo"),
    ("ALICATE DE PRESSAO", ["8203.20.90"], "automotivo"),
    ("MULTIMETRO DIGITAL", ["9030.31.00"], "automotivo"),
    # --- alimentos e bebidas ---
    ("FEIJAO CARIOCA 1KG", ["0713.33.99"], "alimentos"),
    ("SAL REFINADO 1KG", ["2501.00.20"], "alimentos"),
    ("FARINHA DE TRIGO 1KG", ["1101.00.10"], "alimentos"),
    ("MANTEIGA COM SAL 200G", ["0405.10.00"], "alimentos"),
    ("IOGURTE NATURAL 170G", ["0403.20.00"], "alimentos"),
    ("QUEIJO MUSSARELA FATIADO", ["0406.10.10"], "alimentos"),
    ("OVOS BRANCOS DUZIA", ["0407.21.00"], "alimentos"),
    ("BANANA PRATA KG", ["0803.90.00"], "alimentos"),
    ("PATINHO BOVINO KG", ["0201.30.00", "0202.30.00"], "alimentos"),
    ("FRANGO INTEIRO CONGELADO", ["0207.12.10", "0207.12.20"], "alimentos"),
    ("SARDINHA EM LATA 125G", ["1604.13.10"], "alimentos"),
    ("ACHOCOLATADO EM PO 400G", ["1806.10.00", "1806.90.00"], "alimentos"),
    ("KETCHUP 400G", ["2103.20.10"], "alimentos"),
    ("MAIONESE 500G", ["2103.90.11"], "alimentos"),
    ("CAFE SOLUVEL 100G", ["2101.11.10"], "alimentos"),
    ("VODKA 1L", ["2208.60.00"], "bebidas"),
    ("ENERGETICO LATA 250ML", ["2202.10.00", "2202.99.00"], "bebidas"),
    # --- limpeza e higiene ---
    ("AGUA SANITARIA 1L", ["2828.90.11"], "limpeza"),
    ("DESINFETANTE 2L", ["3808.94.19"], "limpeza"),
    ("AMACIANTE ROUPA 2L", ["3809.91.90"], "limpeza"),
    ("SABAO EM PO 1KG", ["3402.50.00"], "limpeza"),
    ("DESODORANTE AEROSOL MASC 150ML", ["3307.20.10", "3307.20.90"], "higiene"),
    ("PROTETOR SOLAR FPS 50", ["3304.99.90"], "higiene"),
    ("ESMALTE DE UNHA", ["3304.30.00"], "higiene"),
    ("ABSORVENTE HIGIENICO", ["9619.00.00"], "higiene"),
    ("APARELHO DE BARBEAR DESCARTAVEL", ["8212.10.20"], "higiene"),
    # --- vestuário, calçados, cama ---
    ("JAQUETA DE COURO", ["4203.10.00"], "vestuario"),
    ("VESTIDO MALHA ALGODAO", ["6104.42.00"], "vestuario"),
    ("BOTA DE SEGURANCA BICO DE ACO", ["6403.40.00"], "calcados"),
    ("LENCOL CASAL ALGODAO", ["6302.21.00", "6302.31.00"], "cama mesa banho"),
    ("TRAVESSEIRO", ["9404.90.00"], "cama mesa banho"),
    ("COLCHAO DE ESPUMA SOLTEIRO", ["9404.21.00"], "moveis"),
    # --- móveis, eletrônicos, eletrodomésticos ---
    ("MESA DE JANTAR MADEIRA", ["9403.60.00"], "moveis"),
    ("ARMARIO DE ACO 2 PORTAS", ["9403.20.90", "9403.10.00"], "moveis"),
    ("MOUSE SEM FIO", ["8471.60.53"], "eletronicos"),
    ("TECLADO USB", ["8471.60.52"], "eletronicos"),
    ("IMPRESSORA MULTIFUNCIONAL JATO DE TINTA", ["8443.31.11", "8443.31.19"], "eletronicos"),
    ("PENDRIVE 32GB", ["8523.51.10", "8523.51.90"], "eletronicos"),
    ("CARREGADOR DE CELULAR USB", ["8504.40.10", "8504.40.90"], "eletronicos"),
    ("CAIXA DE SOM BLUETOOTH", ["8518.22.00", "8518.21.00"], "eletronicos"),
    ("AR CONDICIONADO SPLIT 12000 BTUS", ["8415.10.11"], "eletrodomesticos"),
    ("FERRO DE PASSAR", ["8516.40.00"], "eletrodomesticos"),
    ("BATEDEIRA", ["8509.40.20"], "eletrodomesticos"),
    ("FOGAO 4 BOCAS", ["7321.11.00"], "eletrodomesticos"),
    ("CHUVEIRO ELETRICO", ["8516.10.00"], "eletrodomesticos"),
    ("ASPIRADOR DE PO", ["8508.11.00"], "eletrodomesticos"),
    ("MAQUINA DE LAVAR ROUPAS", ["8450.11.00"], "eletrodomesticos"),
    # --- ferramentas e construção ---
    ("SERRA CIRCULAR", ["8467.22.00"], "ferramentas"),
    ("CHAVE INGLESA", ["8204.12.00"], "ferramentas"),
    ("SERROTE", ["8202.10.00"], "ferramentas"),
    ("TORNEIRA DE PIA", ["8481.80.19"], "construcao"),
    ("ARGAMASSA 20KG", ["3824.50.00"], "construcao"),
    ("TELHA FIBROCIMENTO", ["6811.82.00"], "construcao"),
    ("PREGO 17X27 1KG", ["7317.00.90"], "construcao"),
    ("LIXA DAGUA 220", ["6805.20.00"], "construcao"),
    ("FITA ISOLANTE", ["3919.10.20"], "construcao"),
    ("DISJUNTOR 20A", ["8536.20.00"], "construcao"),
    ("TOMADA 2P+T", ["8536.69.90"], "construcao"),
    # --- papelaria, esporte, brinquedos ---
    ("BORRACHA ESCOLAR", ["4016.92.00"], "papelaria"),
    ("MOCHILA ESCOLAR", ["4202.92.00"], "papelaria"),
    ("BOLA DE BASQUETE", ["9506.62.00"], "esporte"),
    ("VARA DE PESCA", ["9507.10.00"], "esporte"),
    ("BONECA DE PLASTICO", ["9503.00.22"], "brinquedos"),
]

SEMENTE = 2026


def _dividir():
    rng = random.Random(SEMENTE)
    auto = [p for p in POOL if p[2] == "automotivo"]
    outros = [p for p in POOL if p[2] != "automotivo"]
    dev, teste = [], []
    for grupo in (auto, outros):
        grupo = list(grupo)
        rng.shuffle(grupo)
        meio = len(grupo) // 2
        dev += grupo[:meio]
        teste += grupo[meio:]
    return dev, teste


DEV2, TESTE2 = _dividir()


def hash_teste2() -> str:
    return hashlib.sha256(json.dumps(TESTE2, ensure_ascii=False).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Detecção de NCM errado (código válido, porém de outro produto).
# Para cada produto, gera um caso com o NCM certo e um com NCM errado, de um
# destes tipos (proporção 40/30/30):
#   troca    -- NCM de outro produto do mesmo conjunto, de outro capítulo
#               (erro típico de cadastrar copiando um produto existente);
#   capitulo -- item de outra posição do mesmo capítulo;
#   vizinho  -- outro item da mesma posição (erro fino, o mais difícil).
# ---------------------------------------------------------------------------
TIPOS_ERRO = ["troca", "troca", "capitulo", "capitulo", "vizinho", "vizinho", "troca", "capitulo", "vizinho", "troca"]


def casos_deteccao(conjunto, semente: int = SEMENTE):
    """Lista de dicts {descricao, ncm_cadastrado, ncm_errado: bool, tipo, aceitos}."""
    from src.ncm import hierarquia

    rng = random.Random(semente)
    todos_itens = {}
    for pos_lista in hierarquia._arvore()[2].values():
        for item in pos_lista:
            todos_itens[item["codigo"]] = item
    casos = []
    for i, (descricao, aceitos, setor) in enumerate(conjunto):
        casos.append({"descricao": descricao, "ncm_cadastrado": aceitos[0], "ncm_errado": False,
                      "tipo": "correto", "aceitos": aceitos, "setor": setor})
        tipo = TIPOS_ERRO[i % len(TIPOS_ERRO)]
        certo = aceitos[0].replace(".", "")
        errado = None
        if tipo == "vizinho":
            irmaos = [c["codigo"] for c in hierarquia.itens_da_posicao(certo[:4]) if c["codigo"] not in aceitos]
            if irmaos:
                errado = rng.choice(irmaos)
            else:
                tipo = "capitulo"
        if tipo == "capitulo":
            outras = [p for p in hierarquia.posicoes_do_capitulo(certo[:2]) if p != certo[:4]]
            if outras:
                errado = rng.choice(hierarquia.itens_da_posicao(rng.choice(outras)))["codigo"]
            else:
                tipo = "troca"
        if tipo == "troca":
            outros = [p for p in conjunto if p[1][0][:2] != aceitos[0][:2]]
            errado = rng.choice(outros)[1][0]
        casos.append({"descricao": descricao, "ncm_cadastrado": errado, "ncm_errado": True,
                      "tipo": tipo, "aceitos": aceitos, "setor": setor})
    return casos
