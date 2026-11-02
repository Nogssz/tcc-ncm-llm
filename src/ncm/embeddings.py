"""Busca semantica (por significado) sobre os codigos-folha do NCM, pra
cobrir os casos onde a descricao do produto nao compartilha NENHUMA palavra
literal com o texto oficial -- ex.: 'azulejo' (o termo oficial e
'ladrilho'), 'bateria' (o termo oficial e 'acumulador'). A busca lexical
(src.ncm.lookup.search_by_description, via FTS5) nao consegue resolver
isso por definicao: ela so acha o que compartilha palavra/prefixo.

Cada codigo-folha (8 digitos) tem um vetor pre-calculado (uma vez, no
build) a partir do seu 'caminho completo' (Capitulo + Posicao + Subposicao
+ descricao propria -- o mesmo texto usado no indice FTS). Na hora da
busca, calculamos o vetor da descricao do produto e comparamos por
similaridade de cosseno com todos os ~10.500 vetores guardados (busca por
forca bruta com numpy -- nessa escala e instantaneo, nao precisa de banco
de vetores dedicado).
"""
import sqlite3
import struct

import numpy as np
import ollama

from src.config import NCM_DB_PATH, ollama_config

_cache: dict = {}


def embed_text(texto: str) -> np.ndarray:
    resposta = ollama.embed(model=ollama_config.embed_model, input=texto)
    return np.array(resposta["embeddings"][0], dtype=np.float32)


def _carregar_vetores() -> tuple[list[str], np.ndarray]:
    """Carrega todos os vetores salvos em memoria (uma vez por processo).
    ~10.500 vetores de 768 dimensoes = ~32MB, trivial de manter em RAM."""
    if "codigos" in _cache:
        return _cache["codigos"], _cache["matriz"]

    con = sqlite3.connect(NCM_DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT codigo, vetor, dimensoes FROM ncm_embeddings ORDER BY rowid")
    codigos, vetores = [], []
    for codigo, blob, dimensoes in cur.fetchall():
        codigos.append(codigo)
        vetores.append(struct.unpack(f"{dimensoes}f", blob))
    con.close()

    matriz = np.array(vetores, dtype=np.float32)
    # normaliza uma vez, pra cada busca ser so um produto escalar (cosseno)
    matriz = matriz / np.linalg.norm(matriz, axis=1, keepdims=True)

    _cache["codigos"] = codigos
    _cache["matriz"] = matriz
    return codigos, matriz


def search_by_embedding(descricao: str, top_k: int = 10) -> list[dict]:
    """Busca os codigos NCM mais proximos, por significado, da descricao
    informada. Complementa (nao substitui) a busca lexical -- pega
    sinonimos que a busca por palavra nunca acharia."""
    codigos, matriz = _carregar_vetores()

    vetor_consulta = embed_text(descricao)
    vetor_consulta = vetor_consulta / np.linalg.norm(vetor_consulta)

    similaridades = matriz @ vetor_consulta
    melhores_indices = np.argsort(-similaridades)[:top_k]

    con = sqlite3.connect(NCM_DB_PATH)
    cur = con.cursor()
    resultados = []
    for i in melhores_indices:
        codigo = codigos[i]
        cur.execute(
            "SELECT texto_proprio, texto_ancestrais FROM ncm_fts WHERE codigo = ?",
            (codigo,),
        )
        row = cur.fetchone()
        if not row:
            continue
        texto_proprio, texto_ancestrais = row
        caminho = f"{texto_ancestrais} > {texto_proprio}" if texto_ancestrais else texto_proprio
        resultados.append(
            {
                "codigo": codigo,
                "descricao": texto_proprio,
                "caminho_completo": caminho,
                "similaridade": round(float(similaridades[i]), 3),
            }
        )
    con.close()
    return resultados
