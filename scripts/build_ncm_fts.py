"""Constroi um indice de busca textual (FTS5) sobre os codigos-folha (8
digitos) do NCM, com o "caminho completo" de cada item: titulo do
Capitulo + Posicao + Subposicao (quando existirem) + descricao propria do
item. Isso resolve o problema de a descricao de um item nao repetir o
contexto do pai (ex.: '4011.10.00 - Do tipo utilizado em automoveis de
passageiros' nao menciona 'pneu' -- so o cabecalho '40.11 Pneumaticos
novos' menciona).

Depende de scripts/build_ncm_capitulos.py ja ter rodado (usa a tabela
`capitulos`, que ja trata corretamente os capitulos 01-09 que sao gravados
sem zero a esquerda na tabela `ncm` -- reconstruir isso de um dicionario
cru erraria silenciosamente ~7,5% dos itens).
"""
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "data" / "ncm.db"

NIVEIS_ANCESTRAIS = (2, 4, 5, 6, 7)


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT capitulo, titulo FROM capitulos")
    capitulo_titulo = dict(cur.fetchall())

    cur.execute("SELECT codigo, descricao FROM ncm")
    todas_linhas = cur.fetchall()
    digitos_para_descricao = {
        codigo.replace(".", ""): descricao for codigo, descricao in todas_linhas
    }

    folhas = [
        (codigo, descricao)
        for codigo, descricao in todas_linhas
        if len(codigo.replace(".", "")) == 8 and codigo.replace(".", "").isdigit()
    ]

    linhas_fts = []
    sem_ancestral_nivel4 = 0
    for codigo, descricao in folhas:
        digitos = codigo.replace(".", "")
        ancestrais = []

        titulo_capitulo = capitulo_titulo.get(digitos[:2])
        if titulo_capitulo:
            ancestrais.append(titulo_capitulo)

        achou_nivel4 = False
        for nivel in NIVEIS_ANCESTRAIS[1:]:
            prefixo = digitos[:nivel]
            desc_ancestral = digitos_para_descricao.get(prefixo)
            if desc_ancestral:
                ancestrais.append(desc_ancestral)
                if nivel == 4:
                    achou_nivel4 = True
        if not achou_nivel4:
            sem_ancestral_nivel4 += 1

        texto_ancestrais = " > ".join(ancestrais)
        # Versao "colada" (sem hifen): palavras compostas oficiais como
        # 'para-choques' viram dois tokens separados no FTS ('para',
        # 'choques'), mas no dia a dia o produto costuma ser digitado grudado
        # ('parachoque'). Remover o hifen (sem trocar por espaco) gera o
        # token grudado tambem, sem quebrar o resto do texto (um '-' usado
        # so como marcador de item, ex. '- Outros', vira so um espaco a mais).
        texto_colado = (descricao + " " + texto_ancestrais).replace("-", "")
        linhas_fts.append((codigo, descricao, texto_ancestrais, texto_colado))

    cur.execute("DROP TABLE IF EXISTS ncm_fts")
    cur.execute(
        """CREATE VIRTUAL TABLE ncm_fts USING fts5(
            codigo UNINDEXED,
            texto_proprio,
            texto_ancestrais,
            texto_colado,
            tokenize = 'unicode61 remove_diacritics 2'
        )"""
    )
    cur.executemany(
        "INSERT INTO ncm_fts (codigo, texto_proprio, texto_ancestrais, texto_colado) "
        "VALUES (?, ?, ?, ?)",
        linhas_fts,
    )
    con.commit()
    con.close()

    print(f"Itens-folha indexados: {len(linhas_fts)}")
    print(f"Sem ancestral de nivel 4 (posicao): {sem_ancestral_nivel4} "
          f"({100 * sem_ancestral_nivel4 / len(linhas_fts):.1f}%) -- esperado, "
          "hierarquia e irregular")


if __name__ == "__main__":
    main()
