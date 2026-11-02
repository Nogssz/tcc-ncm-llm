"""Busca por radicais (stemming) na tabela NCM -- complementa a busca por
palavra/prefixo de src.ncm.lookup quando a descrição usa outra palavra da
mesma família do texto oficial ("sinalizador" x "sinalização"). O índice
é construído por scripts/build_ncm_stem.py.
"""
import functools
import re
import sqlite3
import unicodedata

from nltk.stem.snowball import SnowballStemmer

from src.config import NCM_DB_PATH

_STEMMER = SnowballStemmer("portuguese")
_PALAVRA_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


@functools.lru_cache(maxsize=50000)
def radical(palavra: str) -> str:
    return _sem_acento(_STEMMER.stem(palavra.lower()))


def radicais_texto(texto: str) -> str:
    return " ".join(radical(p) for p in _PALAVRA_RE.findall(texto))


def search_radicais(termo: str, limit: int = 25) -> list[dict]:
    """Mesmo formato de lookup.search_by_description; lista vazia se nada."""
    from src.ncm.lookup import _tokens_busca

    radicais = list(dict.fromkeys(radical(t) for t in _tokens_busca(termo)))
    radicais = [r for r in radicais if len(r) >= 3]
    if not radicais:
        return []
    query = " OR ".join(f'"{r}"*' for r in radicais)
    con = sqlite3.connect(NCM_DB_PATH)
    try:
        # Sem JOIN com ncm_fts: a coluna codigo de uma tabela FTS não é
        # indexada, e o JOIN varria a tabela inteira a cada linha.
        codigos = [r[0] for r in con.execute(
            "SELECT codigo FROM ncm_fts_stem WHERE ncm_fts_stem MATCH ? "
            "ORDER BY bm25(ncm_fts_stem, 0.0, 5.0, 1.0) LIMIT ?",
            (query, limit),
        )]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [item for c in codigos if (item := _item(c))]


def _item(codigo: str) -> dict | None:
    from src.ncm import hierarquia

    return next((c for c in hierarquia.itens_da_posicao(codigo.replace(".", "")[:4]) if c["codigo"] == codigo), None)
