"""Avaliação da detecção de NCM INVÁLIDO (consulta à tabela, sem IA).

Atende à crítica de que os 33 casos antigos usavam todos o "00000000".
Duas partes:

1. Casos rotulados por categoria, no formato em que o ERP guarda o NCM
   (só dígitos): vazio, zeros, malformado, bem formado mas inexistente,
   extinto e válido. Os válidos (os NCMs esperados dos conjuntos de
   avaliação) medem os falsos positivos.
   Os extintos vêm da NT 2016.003 v3.20 do Portal da NF-e (atualização
   de 01/09/2022): 3923.30.00 -> 3923.90.10/90 e 9403.20.00 -> 9403.20.10/90.

2. Todos os produtos (mercadorias) das duas bases reais de clientes, só
   leitura: quantos têm cada tipo de problema e quantos válidos seriam
   marcados por engano.

Uso: python scripts/avaliar_ncm_invalido.py [--bases loja_a=ARQ.FDB,loja_b=ARQ.FDB]
"""
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ncm.lookup import ncm_valido  # noqa: E402

BASE = Path(__file__).resolve().parent.parent

CASOS_FIXOS = {
    "vazio": [None, "", "   "],
    "zeros": ["00000000", "0", "0000", "000000"],
    "malformado": ["8708100", "870810000", "8708100A", "87O81000", "8708 100", "8708-100", "115024000", "1200131"],
    "inexistente": ["99999999", "87081099", "87089900", "01010101", "40119999", "73181699", "12345678", "85999999"],
    "extinto": ["39233000", "94032000"],
}


def validos_dos_conjuntos() -> list[str]:
    from scripts.avaliar import DEV
    from scripts.conjuntos_v2 import DEV2, TESTE2

    codigos = {e for _, esperados, _ in DEV + DEV2 + TESTE2 for e in esperados}
    brutos = sorted(c.replace(".", "") for c in codigos)
    # o mesmo código com espaços em volta, como às vezes vem do banco
    return brutos + [f" {b} " for b in brutos[:10]]


def parte_rotulada() -> dict:
    casos = [(cat, b) for cat, lista in CASOS_FIXOS.items() for b in lista]
    casos += [("valido", b) for b in validos_dos_conjuntos()]
    por_cat: dict[str, Counter] = {}
    erros = []
    for cat, bruto in casos:
        marcado = not ncm_valido(bruto)
        certo = marcado == (cat != "valido")
        por_cat.setdefault(cat, Counter())["certo" if certo else "errado"] += 1
        if not certo:
            erros.append((cat, bruto))
    return {"por_categoria": {k: dict(v) for k, v in por_cat.items()}, "erros": erros}


def categoria_real(bruto: str | None) -> str:
    b = bruto or ""
    digitos = re.sub(r"\D", "", b)
    if not b.strip():
        return "vazio"
    if set(digitos) == {"0"}:
        return "zeros"
    if len(b.strip()) != 8 or not b.strip().isdigit():
        return "malformado"
    return "valido" if ncm_valido(b) else "inexistente"


def parte_bases(bases: dict[str, Path]) -> dict:
    import firebird.driver as fb

    import src.db.firebird  # noqa: F401  (fbclient 64 bits)
    from src.config import firebird_config

    fb.driver_config.db_defaults.utf8filename.value = True
    saida = {}
    for nome, arquivo in bases.items():
        con = fb.connect(f"{firebird_config.host}/{firebird_config.port}:{arquivo.resolve()}",
                         user=firebird_config.user, password=firebird_config.password)
        cur = con.cursor()
        cur.execute("SELECT NCM FROM PRODUTO WHERE SERVICO = 'N'")
        contagem = Counter()
        for (bruto,) in cur.fetchall():
            cat = categoria_real(bruto)
            marcado = not ncm_valido(bruto)
            contagem[cat] += 1
            if marcado == (cat == "valido"):
                contagem["discordancias"] += 1
        con.close()
        saida[nome] = dict(contagem)
    return saida


def main():
    resultado = {"rotulados": parte_rotulada()}
    print("Casos rotulados (acertos/total por categoria):")
    for cat, c in resultado["rotulados"]["por_categoria"].items():
        total = c.get("certo", 0) + c.get("errado", 0)
        print(f"  {cat:12} {c.get('certo', 0)}/{total}")
    print("  erros:", resultado["rotulados"]["erros"] or "nenhum")
    if "--bases" in sys.argv:
        pares = sys.argv[sys.argv.index("--bases") + 1].split(",")
        resultado["bases_reais"] = parte_bases({n: Path(a) for n, a in (p.split("=", 1) for p in pares)})
        print("Bases reais (mercadorias por categoria):")
        for nome, c in resultado["bases_reais"].items():
            print(f"  {nome:12} {c}")
    saida = BASE / "data" / "avaliacoes" / f"ncm_invalido_{time.strftime('%Y%m%d_%H%M%S')}.json"
    saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Salvo em {saida}")


if __name__ == "__main__":
    main()
