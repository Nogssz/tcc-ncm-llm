"""Constrói o índice de radicais (stemming) da tabela NCM: tabela FTS5
ncm_fts_stem em data/ncm.db, com o mesmo conteúdo de ncm_fts, mas com cada
palavra reduzida ao radical pelo stemmer Snowball para português (NLTK).

Motivo: a busca por prefixo não liga palavras da mesma família quando o
radical é mais curto que a palavra buscada ("sinalizador" x "sinalização",
"desinfecção" x "desinfetantes"). Com os radicais, as duas viram
"sinaliz". Rodar depois de build_ncm_fts.py.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import NCM_DB_PATH  # noqa: E402
from src.ncm.radicais import radicais_texto  # noqa: E402


def main():
    con = sqlite3.connect(NCM_DB_PATH)
    linhas = con.execute("SELECT codigo, texto_proprio, texto_ancestrais FROM ncm_fts").fetchall()
    con.execute("DROP TABLE IF EXISTS ncm_fts_stem")
    con.execute(
        "CREATE VIRTUAL TABLE ncm_fts_stem USING fts5("
        " codigo UNINDEXED, proprio_stem, ancestrais_stem, tokenize = 'unicode61 remove_diacritics 2')"
    )
    con.executemany(
        "INSERT INTO ncm_fts_stem (codigo, proprio_stem, ancestrais_stem) VALUES (?, ?, ?)",
        [(c, radicais_texto(p), radicais_texto(a or "")) for c, p, a in linhas],
    )
    con.commit()
    print(f"ncm_fts_stem: {con.execute('SELECT COUNT(*) FROM ncm_fts_stem').fetchone()[0]} itens")
    exemplo = con.execute("SELECT codigo, proprio_stem FROM ncm_fts_stem WHERE codigo = '8512.30.00'").fetchone()
    print("exemplo:", exemplo)
    con.close()


if __name__ == "__main__":
    main()
