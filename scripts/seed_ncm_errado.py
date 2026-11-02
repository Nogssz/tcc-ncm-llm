"""Cadastra no ERP de desenvolvimento produtos com NCM VÁLIDO, mas errado
(além de alguns com o NCM certo, para mostrar que o sistema não aponta
tudo). Serve para demonstrar a detecção de NCM errado de ponta a ponta:
worker -> verificação -> notificação -> seção "NCM possivelmente errado"
da tela.

Usa só produtos do DEV2 (scripts/conjuntos_v2.py), nunca do TESTE2, e os
NCMs errados são os mesmos gerados para a avaliação (casos_deteccao).

Uso: python scripts/seed_ncm_errado.py           (cadastra)
     python scripts/seed_ncm_errado.py --listar  (só mostra o que cadastraria)
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.conjuntos_v2 import DEV2, casos_deteccao  # noqa: E402
from src.db.firebird import get_connection  # noqa: E402

QTD_ERRADOS = 8
QTD_CERTOS = 4


def escolher():
    casos = casos_deteccao(DEV2)
    errados = [c for c in casos if c["ncm_errado"] and c["tipo"] in ("troca", "capitulo")][:QTD_ERRADOS]
    usados = {c["descricao"] for c in errados}
    certos = [c for c in casos if not c["ncm_errado"] and c["descricao"] not in usados][:QTD_CERTOS]
    return errados + certos


def cadastrar(casos):
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT DESCRICAO FROM PRODUTO")
    existentes = {r[0].strip() for r in cur.fetchall() if r[0]}
    cur.execute("SELECT FIRST 1 * FROM PRODUTO WHERE SERVICO = 'N' ORDER BY CODIGO DESC")
    colunas = [d[0].strip() for d in cur.description]
    modelo = dict(zip(colunas, cur.fetchone()))
    modelo.pop("FOTO", None)

    criados = []
    for c in casos:
        if c["descricao"] in existentes:
            print(f"  já existe, pulando: {c['descricao']}")
            continue
        cur.execute("SELECT GEN_ID(GEN_PRODUTO_CODIGO, 1) FROM RDB$DATABASE")
        codigo = cur.fetchone()[0]
        linha = dict(modelo)
        linha.update(CODIGO=codigo, REFERENCIA=str(codigo), DESCRICAO=c["descricao"],
                     NCM=c["ncm_cadastrado"].replace(".", ""), DT_CADASTRO=date.today())
        cur.execute(f"INSERT INTO PRODUTO ({', '.join(linha)}) VALUES ({', '.join('?' * len(linha))})",
                    tuple(linha.values()))
        criados.append((codigo, c))
    con.commit()
    con.close()
    for codigo, c in criados:
        print(f"  #{codigo:<4} {c['descricao']:<40} NCM {c['ncm_cadastrado']} "
              f"({'ERRADO, ' + c['tipo'] if c['ncm_errado'] else 'certo'})")
    print(f"\n{len(criados)} produto(s) cadastrado(s).")


if __name__ == "__main__":
    casos = escolher()
    if "--listar" in sys.argv:
        for c in casos:
            print(f"  {c['descricao']:<40} {c['ncm_cadastrado']} ({'ERRADO, ' + c['tipo'] if c['ncm_errado'] else 'certo'})")
    else:
        cadastrar(casos)
