"""Calcula o vetor de embedding (significado semantico) de cada
codigo-folha do NCM, a partir do mesmo 'caminho completo' ja usado no
indice FTS (scripts/build_ncm_fts.py). Salva em data/ncm.db, tabela
ncm_embeddings, pra busca por similaridade sem precisar recalcular nada em
tempo de consulta.

Depende de scripts/build_ncm_fts.py ja ter rodado (le texto_proprio /
texto_ancestrais da tabela ncm_fts).
"""
import sqlite3
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ollama

from src.config import NCM_DB_PATH, ollama_config

LOTE = 300


def main():
    con = sqlite3.connect(NCM_DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT codigo, texto_proprio, texto_ancestrais FROM ncm_fts ORDER BY rowid")
    linhas = cur.fetchall()

    cur.execute(
        "CREATE TABLE IF NOT EXISTS ncm_embeddings "
        "(codigo TEXT PRIMARY KEY, vetor BLOB, dimensoes INTEGER)"
    )
    cur.execute("SELECT codigo FROM ncm_embeddings")
    ja_feitos = {r[0] for r in cur.fetchall()}
    if ja_feitos:
        print(f"Retomando: {len(ja_feitos)} ja calculados, pulando esses.", file=sys.stderr)

    linhas = [linha for linha in linhas if linha[0] not in ja_feitos]
    textos = [
        f"{ancestrais} > {proprio}" if ancestrais else proprio
        for _, proprio, ancestrais in linhas
    ]
    codigos = [codigo for codigo, _, _ in linhas]

    total = len(textos)
    if total == 0:
        print("Nada a fazer, todos os embeddings ja existem.")
        con.close()
        return
    inicio = time.time()
    for i in range(0, total, LOTE):
        lote_textos = textos[i : i + LOTE]
        lote_codigos = codigos[i : i + LOTE]
        resposta = ollama.embed(model=ollama_config.embed_model, input=lote_textos)
        linhas_inserir = []
        for codigo, vetor in zip(lote_codigos, resposta["embeddings"]):
            blob = struct.pack(f"{len(vetor)}f", *vetor)
            linhas_inserir.append((codigo, blob, len(vetor)))
        cur.executemany(
            "INSERT INTO ncm_embeddings (codigo, vetor, dimensoes) VALUES (?, ?, ?)",
            linhas_inserir,
        )
        con.commit()
        print(f"  {min(i + LOTE, total)}/{total} ({time.time() - inicio:.0f}s)", file=sys.stderr)

    con.close()
    print(f"Concluido: {total} embeddings em {time.time() - inicio:.0f}s")


if __name__ == "__main__":
    main()
