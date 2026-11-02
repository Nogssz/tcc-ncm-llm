"""Base de conhecimento de produtos já classificados por empresas reais
(data/conhecimento.db, SQLite, fora do git).

É a "memória" do sistema em escala: em vez de só os produtos da própria
empresa (src.db.memoria), consulta milhares de produtos que outras lojas
de autopeças já classificaram. Para um produto novo, os mais parecidos e
seus NCMs servem de evidência e de candidatos para o modelo de linguagem.

Não é treinamento de pesos do modelo: é recuperação (kNN) sobre exemplos
rotulados, o que funciona com qualquer modelo e é atualizado só inserindo
linhas.
"""
import re
import sqlite3
from collections import Counter

from src.config import BASE_DIR
from src.ncm.abreviacoes import expandir
from src.ncm.radicais import radical

CAMINHO = BASE_DIR / "data" / "conhecimento.db"

# "VIEMAR 680077 - ARTICULADOR AXIAL DIRECAO" -> "ARTICULADOR AXIAL DIRECAO":
# o prefixo "MARCA CODIGO -" identifica o fabricante, não o tipo de produto.
_PREFIXO_MARCA = re.compile(r"^[^-]{0,40}?\d[^-]{0,25}\s-\s+")
_PALAVRA = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_IRRELEVANTES = {"de", "da", "do", "das", "dos", "para", "com", "sem", "em", "e", "a", "o", "p", "c", "kit", "jogo"}


_PARACHOQUE = re.compile(r"P[AÁ]RA.?CHOQ|PCHOQ|P/CHOQ", re.IGNORECASE)


def confiavel(descricao: str, ncm: str) -> bool:
    """Filtra NCMs usados como "coringa". Na base da Loja B, 8708.10.00
    (para-choques) aparece em 3.407 produtos -- molas, freios, cabos,
    rolamentos --, e só 104 são para-choques: usar esses pares ensinaria o
    erro da loja. Fica de fora quem tem 8708.10.00 sem citar para-choque."""
    return ncm != "8708.10.00" or bool(_PARACHOQUE.search(descricao))


def limpar_descricao(descricao: str) -> str:
    return _PREFIXO_MARCA.sub("", descricao.strip()).strip()


def termos(descricao: str) -> list[str]:
    """Radicais das palavras relevantes, depois de expandir abreviações."""
    texto = expandir(limpar_descricao(descricao)).lower()
    return [radical(p) for p in _PALAVRA.findall(texto) if p not in _IRRELEVANTES]


def _conectar() -> sqlite3.Connection:
    CAMINHO.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CAMINHO)
    con.execute(
        "CREATE TABLE IF NOT EXISTS produtos (base TEXT, codigo INTEGER, descricao TEXT, ncm TEXT,"
        " PRIMARY KEY (base, codigo))"
    )
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS produtos_fts USING fts5("
        " base UNINDEXED, codigo UNINDEXED, termos, tokenize = 'unicode61 remove_diacritics 2')"
    )
    return con


def salvar_base(nome: str, pares: list[tuple[int, str, str]]) -> None:
    """Substitui todos os produtos da base `nome` pelos pares (codigo, descricao, ncm)."""
    with _conectar() as con:
        con.execute("DELETE FROM produtos WHERE base = ?", (nome,))
        con.execute("DELETE FROM produtos_fts WHERE base = ?", (nome,))
        con.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?)", [(nome, c, d, n) for c, d, n in pares])
        con.executemany(
            "INSERT INTO produtos_fts (base, codigo, termos) VALUES (?, ?, ?)",
            [(nome, c, " ".join(termos(d))) for c, d, _ in pares],
        )


def parecidos(descricao: str, limite: int = 10, excluir: set[tuple[str, int]] | None = None,
              bases: list[str] | None = None) -> list[dict]:
    """Produtos já classificados mais parecidos com a descrição (BM25 sobre
    os radicais), cada um com base, código, descrição, NCM e pontuação."""
    t = list(dict.fromkeys(termos(descricao)))
    if not t:
        return []
    query = " OR ".join(f'"{x}"' for x in t)
    filtro = ""
    params: list = [query]
    if bases:
        filtro = f" AND f.base IN ({','.join('?' * len(bases))})"
        params += bases
    params.append(limite + len(excluir or ()))
    with _conectar() as con:
        rows = con.execute(
            "SELECT f.base, f.codigo, p.descricao, p.ncm, bm25(produtos_fts) AS s "
            "FROM produtos_fts f JOIN produtos p ON p.base = f.base AND p.codigo = f.codigo "
            f"WHERE produtos_fts MATCH ?{filtro} ORDER BY s LIMIT ?",
            params,
        ).fetchall()
    saida = [{"base": b, "codigo": c, "descricao": d, "ncm": n, "pontuacao": round(-s, 2)}
             for b, c, d, n, s in rows if not excluir or (b, c) not in excluir]
    return saida[:limite]


def votar(vizinhos: list[dict], k: int = 10) -> list[tuple[str, float]]:
    """NCMs dos vizinhos, ponderados pela posição (1/(1+i)), do mais votado
    para o menos votado."""
    pontos: Counter = Counter()
    for i, v in enumerate(vizinhos[:k]):
        pontos[v["ncm"]] += 1 / (1 + i)
    return pontos.most_common()
