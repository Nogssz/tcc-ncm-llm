"""Organiza a tabela NCM pela hierarquia oficial (Capitulo -> Posicao ->
Subposicao -> Item). Os 2 primeiros digitos do codigo NCM sempre indicam o
Capitulo (ex.: 87 = veiculos automoveis e suas partes) -- isso permite um
roteamento DETERMINISTICO (sem depender do LLM) do assunto de um codigo,
usado tanto pela ferramenta do agente quanto como fallback caso o agente
nao responda (ver src/agent/core.py:diagnose).

Gera:
  - tabela `capitulos` dentro de data/ncm.db (capitulo, titulo)
  - coluna `capitulo` na tabela `ncm` (indexada)
  - data/ncm/capitulos.csv (indice: capitulo, titulo, qtd_codigos)
  - data/ncm/por_capitulo/<NN>.csv (um arquivo por capitulo, so os itens
    daquele capitulo -- util para navegar manualmente sem abrir a tabela
    inteira)
"""
import csv
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "data" / "ncm.db"
OUT_DIR = BASE / "data" / "ncm"
POR_CAPITULO_DIR = OUT_DIR / "por_capitulo"
POR_CAPITULO_DIR.mkdir(parents=True, exist_ok=True)


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(ncm)")
    cols = [c[1] for c in cur.fetchall()]
    if "capitulo" not in cols:
        cur.execute("ALTER TABLE ncm ADD COLUMN capitulo TEXT")

    cur.execute("SELECT rowid, codigo FROM ncm")
    rows = cur.fetchall()
    updates = []
    for rowid, codigo in rows:
        digits = codigo.replace(".", "")
        capitulo = digits[:2].zfill(2) if digits[:2].isdigit() else digits[:1].zfill(2)
        updates.append((capitulo, rowid))
    cur.executemany("UPDATE ncm SET capitulo = ? WHERE rowid = ?", updates)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ncm_capitulo ON ncm(capitulo)")

    # tabela de referencia: titulo oficial de cada capitulo (as proprias
    # entradas de nivel 1-2 digitos que ja estavam na tabela extraida)
    cur.execute(
        "SELECT codigo, descricao FROM ncm WHERE codigo GLOB '[0-9]' OR codigo GLOB '[0-9][0-9]'"
    )
    capitulo_titulos = {codigo.zfill(2): descricao for codigo, descricao in cur.fetchall()}

    cur.execute("DROP TABLE IF EXISTS capitulos")
    cur.execute("CREATE TABLE capitulos (capitulo TEXT PRIMARY KEY, titulo TEXT)")
    cur.executemany(
        "INSERT INTO capitulos VALUES (?, ?)",
        sorted(capitulo_titulos.items()),
    )
    con.commit()

    # arquivos por capitulo + indice, para navegacao manual
    index_rows = []
    for capitulo, titulo in sorted(capitulo_titulos.items()):
        cur.execute(
            "SELECT codigo, descricao, data_inicio FROM ncm "
            "WHERE capitulo = ? AND codigo != ? ORDER BY codigo",
            (capitulo, capitulo.lstrip("0") or "0"),
        )
        itens = cur.fetchall()
        with open(POR_CAPITULO_DIR / f"{capitulo}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["codigo", "descricao", "data_inicio"])
            w.writerows(itens)
        index_rows.append((capitulo, titulo, len(itens)))

    with open(OUT_DIR / "capitulos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["capitulo", "titulo", "qtd_codigos"])
        w.writerows(index_rows)

    con.close()
    print(f"{len(index_rows)} capitulos processados.")
    print(f"Indice: {OUT_DIR / 'capitulos.csv'}")
    print(f"Arquivos por capitulo: {POR_CAPITULO_DIR}")


if __name__ == "__main__":
    main()
