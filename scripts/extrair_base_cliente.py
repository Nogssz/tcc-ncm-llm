"""Extrai de uma base de cliente (Firebird, somente leitura) os pares
descrição -> NCM das mercadorias com NCM válido, para a base de
conhecimento local (data/conhecimento.db, fora do git).

Só lê a tabela PRODUTO, e só as colunas DESCRICAO e NCM (mais o código
interno, para rastreio). Nenhum dado de cliente, fornecedor ou nota é lido.

Uso: python scripts/extrair_base_cliente.py <arquivo.fdb> <nome_curto>
     ex.: python scripts/extrair_base_cliente.py basesProduto/DADOS_LOJA_A.FDB loja_a
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firebird.driver as fb  # noqa: E402

import src.db.firebird  # noqa: E402,F401  (configura a fbclient de 64 bits)
from src.config import firebird_config  # noqa: E402
from src.ncm import conhecimento  # noqa: E402
from src.ncm.lookup import ncm_valido, normalizar_codigo_erp  # noqa: E402


def main():
    arquivo = Path(sys.argv[1]).resolve()
    nome = sys.argv[2]
    # Caminhos com acento ("Área de Trabalho") só abrem com o nome em UTF-8.
    fb.driver_config.db_defaults.utf8filename.value = True
    con = fb.connect(f"{firebird_config.host}/{firebird_config.port}:{arquivo}",
                     user=firebird_config.user, password=firebird_config.password)
    cur = con.cursor()
    cur.execute("SELECT CODIGO, DESCRICAO, NCM, SERVICO FROM PRODUTO")
    pares = []
    for codigo, descricao, ncm, servico in cur.fetchall():
        descricao = (descricao or "").strip()
        ncm = (ncm or "").strip()
        if (servico or "N").strip() == "S" or not descricao or not ncm_valido(ncm):
            continue
        pares.append((codigo, descricao, normalizar_codigo_erp(ncm)))
    con.close()
    confiaveis = [p for p in pares if conhecimento.confiavel(p[1], p[2])]
    conhecimento.salvar_base(nome, confiaveis)
    print(f"{nome}: {len(confiaveis)} produtos gravados em {conhecimento.CAMINHO} "
          f"({len(pares) - len(confiaveis)} descartados como NCM 'coringa')")


if __name__ == "__main__":
    main()
