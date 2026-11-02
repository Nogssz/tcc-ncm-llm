# Classificação fiscal NCM assistida por LLM local

Protótipo do Trabalho de Conclusão de Curso de Gabriel Nogueira (Ciência da Computação, IFC Câmpus Videira, 2026), com orientação de Fabricio Bizotto.

O protótipo lê o cadastro de produtos de um ERP (Lux Auto, banco Firebird). Ele:

- aponta produtos com **NCM inválido** (vazio, malformado, inexistente ou extinto);
- aponta produtos com **NCM válido, mas possivelmente errado**;
- **sugere as 3 classificações mais prováveis** a partir da descrição do produto.

O modelo de linguagem (Qwen3 8B) roda localmente, pelo [Ollama](https://ollama.com). Ele só escolhe entre códigos que existem na tabela oficial, e **nada é gravado no ERP sem a aprovação de uma pessoa** na tela de supervisão (Streamlit).

O texto do TCC está em [`tcc_latex/`](tcc_latex/). O PDF mais recente fica em `tcc_latex/TCC_Gabriel_Nogueira_*.pdf`.

## Como funciona

1. **Detecção de NCM inválido** ([`src/ncm/lookup.py`](src/ncm/lookup.py)): consulta direta à tabela NCM vigente, sem IA.
2. **Sugestão** ([`src/agent/ncm_suggester.py`](src/agent/ncm_suggester.py)):
   1. expande as abreviações do cadastro;
   2. o LLM reescreve a descrição em termos técnicos;
   3. uma busca BM25 (SQLite FTS5, com sinônimos e fusão RRF) encontra candidatos na tabela;
   4. o LLM escolhe o capítulo e depois os 3 itens. A resposta é travada por esquema JSON e só aceita os códigos apresentados;
   5. produtos parecidos já classificados por outras lojas (kNN) entram como candidatos e como voto.
3. **Verificação de NCM possivelmente errado** ([`src/agent/ncm_verificador.py`](src/agent/ncm_verificador.py)): o produto é suspeito quando o NCM cadastrado fica fora das 3 sugestões **e** o LLM julga o texto oficial do código incompatível com o produto.
4. **Worker** ([`scripts/worker_sugestoes.py`](scripts/worker_sugestoes.py)) processa em segundo plano, e a **tela** ([`src/app/ncm_dashboard.py`](src/app/ncm_dashboard.py)) é onde a pessoa aprova.

## Instalação

Requisitos:
- Python 3.13;
- Ollama;
- Firebird 3.0, para usar com o ERP;
- placa de vídeo com cerca de 6 GB de memória.

```bash
pip install -r requirements.txt
ollama pull qwen3:8b
cp .env.example .env          # ajustar caminho do banco do ERP e credenciais
```

O cliente Firebird de 64 bits (`fbclient.dll`) vem da instalação do Firebird. Aponte para ele em `FIREBIRD_CLIENT_LIBRARY` no `.env`.

### Base local da tabela NCM

A base `data/ncm.db` não está no repositório, porque é gerada a partir do PDF oficial em `docs/Tabela_NCM.pdf`:

```bash
python scripts/extract_ncm.py          # PDF -> data/ncm.db e data/ncm.csv
python scripts/repair_ncm.py           # corrige linhas embaralhadas pelo PDF
python scripts/build_ncm_capitulos.py  # hierarquia capítulo/posição/item
python scripts/build_ncm_fts.py        # índice de busca BM25
python scripts/build_ncm_stem.py       # índice de radicais
```

### Base de conhecimento (opcional)

A base `data/conhecimento.db` guarda produtos já classificados por outras lojas. Ela também **não** está no repositório, porque vem de bases de clientes. Para montar a sua a partir de um banco Firebird de cliente (só leitura, apenas descrição e NCM):

```bash
python scripts/extrair_base_cliente.py caminho/DADOS.FDB loja_a
```

Sem essa base, o protótipo funciona, mas com o acerto da linha "sem base de conhecimento" do TCC. Para desligá-la, use `CONFIG["conhecimento"] = ""` em `src/agent/ncm_suggester.py`.

## Uso

```bash
python scripts/worker_sugestoes.py --notificar   # detecção e sugestões em segundo plano
streamlit run src/app/ncm_dashboard.py           # tela de aprovação (só localhost)
```

## Avaliação (reproduzir os números do TCC)

| Script | O que mede |
|---|---|
| `scripts/avaliar.py --conjunto devtudo` | sugestão nos conjuntos de desenvolvimento |
| `scripts/avaliar.py --conjunto teste2 --final` | sugestão no conjunto de teste congelado (rodar uma única vez) |
| `scripts/avaliar_sem_llm.py --conjunto teste2 --final` | busca e kNN **sem** LLM (linha de base) |
| `scripts/avaliar_deteccao.py --conjunto dev2` | detecção de NCM errado (erros plantados) |
| `scripts/avaliar_ncm_invalido.py` | detecção de NCM inválido por categoria |
| `scripts/avaliar_knn.py`, `scripts/avaliar_knn_cruzado.py` | base de conhecimento sozinha |

- **Conjuntos:** estão em [`scripts/conjuntos_v2.py`](scripts/conjuntos_v2.py) e [`scripts/avaliar.py`](scripts/avaliar.py).
- **Resultados de cada execução:** em [`data/avaliacoes/`](data/avaliacoes/), em JSON. Cada arquivo traz, por produto, as opções sugeridas, a resposta esperada, o capítulo escolhido, a interpretação do modelo e o tempo.
- **Histórico dos experimentos:** em [`docs/diario_noturno.md`](docs/diario_noturno.md).

Os arquivos de avaliação feitos com produtos das lojas não estão no repositório.

## Segurança

- O LLM nunca acessa o banco. As consultas são fixas e só de leitura (`SELECT`).
- A única escrita é `UPDATE PRODUTO SET NCM = ? WHERE CODIGO = ?`, disparada pelo botão de aprovação.
- A tela de supervisão deve ser servida só em `localhost`, porque altera o banco de produção.
