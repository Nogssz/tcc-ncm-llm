"""Repara linhas da tabela NCM cuja data_inicio ficou entrelacada com o
final da descricao (defeito do PDF de origem: uma camada de texto sobreposta
faz o pdfplumber intercalar caracteres). A ordem relativa dos caracteres de
cada string original se preserva no entrelacamento, entao basta separar
digitos/barras (formam a data) do restante (reconstroi a descricao)."""
import csv
import re
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "data" / "ncm.db"
CSV_PATH = BASE / "data" / "ncm.csv"

DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")


def repair(descricao, data_inicio):
    combined = descricao + data_inicio
    idx_map = [i for i, ch in enumerate(combined) if ch.isdigit() or ch == "/"]
    d = "".join(combined[i] for i in idx_map)
    match = None
    for m in DATE_RE.finditer(d):
        match = m
    if not match:
        return None
    remove = set(idx_map[match.start():match.end()])
    remainder = "".join(ch for i, ch in enumerate(combined) if i not in remove)
    return remainder.strip(), match.group()


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT rowid, codigo, descricao, data_inicio FROM ncm "
        "WHERE data_inicio NOT GLOB '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]'"
    )
    bad = cur.fetchall()

    repaired, unresolved = 0, []
    for rowid, codigo, desc, data in bad:
        r = repair(desc, data)
        if r:
            new_desc, new_date = r
            cur.execute(
                "UPDATE ncm SET descricao = ?, data_inicio = ? WHERE rowid = ?",
                (new_desc, new_date, rowid),
            )
            repaired += 1
        else:
            unresolved.append((rowid, codigo, desc, data))

    for rowid, codigo, desc, data in unresolved:
        cur.execute(
            "UPDATE ncm SET descricao = ?, data_inicio = ? WHERE rowid = ?",
            (desc.strip(), None, rowid),
        )

    con.commit()

    cur.execute("SELECT codigo, descricao, data_inicio FROM ncm ORDER BY rowid")
    rows = cur.fetchall()
    con.close()

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "descricao", "data_inicio"])
        w.writerows(rows)

    print(f"reparadas: {repaired}")
    print(f"nao resolvidas (data zerada, descricao mantida truncada): {len(unresolved)}")
    for u in unresolved[:15]:
        print(" ", u[1], repr(u[2][-50:]))


if __name__ == "__main__":
    main()
