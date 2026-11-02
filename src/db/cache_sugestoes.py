"""Cache local das sugestoes de NCM (data/sugestoes.db, SQLite -- nunca no
banco do ERP). O worker (scripts/worker_sugestoes.py) grava aqui assim que
um produto com NCM invalido aparece; a tela do Streamlit le daqui, entao o
operador ja encontra a sugestao pronta em vez de esperar ~30s por produto.

A chave e (codigo do produto, descricao): se o operador corrigir a
descricao no ERP, a sugestao antiga deixa de valer e e recalculada.
"""
import json
import sqlite3
from datetime import datetime

from src.config import BASE_DIR

CAMINHO = BASE_DIR / "data" / "sugestoes.db"


def _conectar() -> sqlite3.Connection:
    CAMINHO.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CAMINHO)
    con.execute(
        "CREATE TABLE IF NOT EXISTS sugestoes ("
        " codigo_produto INTEGER, descricao TEXT, sugestao_json TEXT, criado_em TEXT,"
        " PRIMARY KEY (codigo_produto, descricao))"
    )
    return con


def buscar(codigo_produto: int, descricao: str) -> tuple[dict, str] | None:
    """(sugestao como dict, criado_em) ou None se ainda nao foi calculada."""
    with _conectar() as con:
        row = con.execute(
            "SELECT sugestao_json, criado_em FROM sugestoes WHERE codigo_produto = ? AND descricao = ?",
            (codigo_produto, descricao.strip()),
        ).fetchone()
    return (json.loads(row[0]), row[1]) if row else None


def salvar(codigo_produto: int, descricao: str, sugestao: dict) -> None:
    with _conectar() as con:
        con.execute(
            "INSERT OR REPLACE INTO sugestoes VALUES (?, ?, ?, ?)",
            (codigo_produto, descricao.strip(), json.dumps(sugestao, ensure_ascii=False),
             datetime.now().strftime("%d/%m %H:%M")),
        )


def remover(codigo_produto: int) -> None:
    """Chamado quando o operador aplica ou pede de novo: tira a sugestao velha."""
    with _conectar() as con:
        con.execute("DELETE FROM sugestoes WHERE codigo_produto = ?", (codigo_produto,))


# ---------------------------------------------------------------------------
# Verificações de NCM válido, mas possivelmente errado (src.agent.ncm_verificador).
# Chave (código, descrição, NCM): se o operador mudar qualquer um dos dois
# campos no ERP, o produto é verificado de novo.
# status: ok | suspeito | confirmado (operador disse que o NCM atual está certo)
# ---------------------------------------------------------------------------
def _conectar_verificacoes() -> sqlite3.Connection:
    con = _conectar()
    con.execute(
        "CREATE TABLE IF NOT EXISTS verificacoes ("
        " codigo_produto INTEGER, descricao TEXT, ncm TEXT, status TEXT, verificacao_json TEXT, criado_em TEXT,"
        " PRIMARY KEY (codigo_produto, descricao, ncm))"
    )
    return con


def buscar_verificacao(codigo_produto: int, descricao: str, ncm: str) -> tuple[str, dict, str] | None:
    """(status, verificação como dict, criado_em) ou None se ainda não foi verificado."""
    with _conectar_verificacoes() as con:
        row = con.execute(
            "SELECT status, verificacao_json, criado_em FROM verificacoes"
            " WHERE codigo_produto = ? AND descricao = ? AND ncm = ?",
            (codigo_produto, descricao.strip(), (ncm or "").strip()),
        ).fetchone()
    return (row[0], json.loads(row[1]), row[2]) if row else None


def salvar_verificacao(codigo_produto: int, descricao: str, ncm: str, status: str, verificacao: dict) -> None:
    with _conectar_verificacoes() as con:
        con.execute(
            "INSERT OR REPLACE INTO verificacoes VALUES (?, ?, ?, ?, ?, ?)",
            (codigo_produto, descricao.strip(), (ncm or "").strip(), status,
             json.dumps(verificacao, ensure_ascii=False), datetime.now().strftime("%d/%m %H:%M")),
        )


def marcar_confirmado(codigo_produto: int, descricao: str, ncm: str) -> None:
    """O operador conferiu e o NCM atual está certo: não apontar de novo."""
    with _conectar_verificacoes() as con:
        con.execute(
            "UPDATE verificacoes SET status = 'confirmado' WHERE codigo_produto = ? AND descricao = ? AND ncm = ?",
            (codigo_produto, descricao.strip(), (ncm or "").strip()),
        )


def listar_suspeitos() -> list[dict]:
    with _conectar_verificacoes() as con:
        rows = con.execute(
            "SELECT codigo_produto, descricao, ncm, verificacao_json, criado_em FROM verificacoes"
            " WHERE status = 'suspeito' ORDER BY codigo_produto"
        ).fetchall()
    return [{"codigo": r[0], "descricao": r[1], "ncm": r[2], "verificacao": json.loads(r[3]), "criado_em": r[4]}
            for r in rows]
