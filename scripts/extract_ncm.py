"""Extrai a Tabela NCM (PDF) para SQLite + CSV, para consulta programatica
(sem nunca carregar o arquivo inteiro no contexto de um LLM/chat)."""
import sqlite3
import csv
import sys
from pathlib import Path

import pdfplumber

BASE = Path(__file__).resolve().parent.parent
PDF_PATH = BASE / "docs" / "Tabela_NCM.pdf"
DB_PATH = BASE / "data" / "ncm.db"
CSV_PATH = BASE / "data" / "ncm.csv"

DB_PATH.parent.mkdir(exist_ok=True)


def clean(cell):
    return (cell or "").replace("\n", " ").strip()


def main():
    rows = []
    with pdfplumber.open(PDF_PATH) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            table = page.extract_table()
            if not table:
                continue
            for r in table:
                if len(r) < 3:
                    continue
                codigo, descricao, data_inicio = clean(r[0]), clean(r[1]), clean(r[2])
                if codigo.lower() == "código" or not codigo:
                    continue
                rows.append((codigo, descricao, data_inicio))
            if (i + 1) % 50 == 0 or (i + 1) == total:
                print(f"  processada pagina {i + 1}/{total} ({len(rows)} linhas ate agora)", file=sys.stderr)

    print(f"Total extraido: {len(rows)} linhas", file=sys.stderr)

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "descricao", "data_inicio"])
        w.writerows(rows)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS ncm")
    cur.execute(
        """CREATE TABLE ncm (
            codigo TEXT,
            descricao TEXT,
            data_inicio TEXT
        )"""
    )
    cur.executemany("INSERT INTO ncm VALUES (?, ?, ?)", rows)
    cur.execute("CREATE INDEX idx_ncm_codigo ON ncm(codigo)")
    con.commit()
    con.close()

    print(f"OK -> {DB_PATH} e {CSV_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
