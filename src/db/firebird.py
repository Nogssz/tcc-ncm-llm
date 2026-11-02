"""Conexao com o Firebird do ERP e guardrails de execucao SQL.

Fase de diagnostico do agente: apenas SELECT. Um UPDATE so roda depois de
aprovacao humana na interface (Streamlit), via execute_approved_update().
"""
import re
from pathlib import Path

import firebird.driver as fb

from src.config import BASE_DIR, firebird_config

_DESTRUCTIVE = re.compile(
    r"\b(DROP|DELETE|TRUNCATE|ALTER|GRANT|REVOKE|EXECUTE\s+BLOCK)\b", re.IGNORECASE
)
_UPDATE_STMT = re.compile(r"^\s*UPDATE\b", re.IGNORECASE)
_SELECT_STMT = re.compile(r"^\s*SELECT\b", re.IGNORECASE)

_client_lib = Path(firebird_config.client_library)
if not _client_lib.is_absolute():
    _client_lib = BASE_DIR / _client_lib
if _client_lib.exists():
    fb.driver_config.fb_client_library.value = str(_client_lib)


def get_connection():
    return fb.connect(
        database=f"{firebird_config.host}/{firebird_config.port}:{firebird_config.database}",
        user=firebird_config.user,
        password=firebird_config.password,
    )


def fetch_schema_ddl() -> str:
    """Le a estrutura (tabelas e colunas) do banco para dar contexto ao LLM,
    sem nunca expor os dados em si."""
    query = """
        SELECT TRIM(r.RDB$RELATION_NAME) AS tabela,
               TRIM(f.RDB$FIELD_NAME) AS coluna,
               TRIM(t.RDB$TYPE_NAME) AS tipo
        FROM RDB$RELATION_FIELDS r
        JOIN RDB$FIELDS fld ON fld.RDB$FIELD_NAME = r.RDB$FIELD_SOURCE
        JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = r.RDB$FIELD_SOURCE
        JOIN RDB$TYPES t ON t.RDB$TYPE = fld.RDB$FIELD_TYPE
                          AND t.RDB$FIELD_NAME = 'RDB$FIELD_TYPE'
        WHERE r.RDB$SYSTEM_FLAG = 0
        ORDER BY r.RDB$RELATION_NAME, r.RDB$FIELD_POSITION
    """
    with get_connection() as con:
        cur = con.cursor()
        cur.execute(query)
        rows = cur.fetchall()

    ddl_lines, current_table = [], None
    for tabela, coluna, tipo in rows:
        if tabela != current_table:
            ddl_lines.append(f"\nTABELA {tabela}:")
            current_table = tabela
        ddl_lines.append(f"  - {coluna} ({tipo})")
    return "\n".join(ddl_lines)


def run_select(sql: str) -> list[dict]:
    """Executa apenas consultas de leitura. Usado pelo agente na fase de
    diagnostico (identificar inconsistencias)."""
    if not _SELECT_STMT.match(sql) or _DESTRUCTIVE.search(sql):
        raise ValueError("Apenas SELECT e permitido nesta fase. Consulta rejeitada.")

    with get_connection() as con:
        cur = con.cursor()
        cur.execute(sql)
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def execute_approved_update(sql: str, params: tuple = ()) -> int:
    """So deve ser chamada apos aprovacao explicita do operador humano na UI.
    Continua bloqueando qualquer comando destrutivo (DROP/DELETE/etc).
    Use `params` (placeholders `?`) em vez de concatenar valores na string."""
    if not _UPDATE_STMT.match(sql) or _DESTRUCTIVE.search(sql):
        raise ValueError("Apenas UPDATE e permitido na execucao aprovada.")

    with get_connection() as con:
        cur = con.cursor()
        cur.execute(sql, params)
        affected = cur.rowcount
        con.commit()
        return affected
