# Diário da rodada noturna (21–22/10/2026)

Objetivos pedidos:
- **Sugestão de NCM**: chegar a pelo menos 65% de acerto.
- **Detecção de NCM errado** (código válido, mas de outro produto, não só `00000000`): chegar a 75% de acerto.

## 1. Conjuntos novos (antes de qualquer mudança no sistema)

- `scripts/conjuntos_v2.py`: 99 produtos novos, nenhum repetido dos conjuntos antigos, um terço automotivo, códigos conferidos na tabela.
- A divisão foi feita por **sorteio com semente fixa (2026)**: **DEV2** com 49 produtos, usado para melhorar o sistema, e **TESTE2** com 50, congelado e medido só no fim.
- Hash do TESTE2 congelado: `5c3713675f0045f9ad85617855d49e879d7efdef062d6c498f01fd1076693144`
- Detecção: para cada produto, um caso com o NCM certo e um com o NCM errado. O erro é de um destes tipos:
  - *troca*: NCM de outro produto, como quando se cadastra copiando um produto existente;
  - *capítulo*: outra posição do mesmo capítulo;
  - *vizinho*: outro item da mesma posição, que é o erro mais difícil de perceber.

## 2. Linha de base (sistema da versão do TCC, sem mudanças)

| Conjunto | 1º lugar | Top-3 | Busca traz o certo | Tempo |
|---|---|---|---|---|
| DEV2 (49) | 44,9% | 57,1% | 75,5% | 14,0 s |
| TESTE2 (50), só o agregado | 32,0% | 48,0% | 64,0% | 13,4 s |

Erros típicos no DEV2:
- abreviações mal interpretadas: "PIVO SUSP INF" virou "medicamento para infusão";
- vocabulário: serrote, lixa d'água, sabão em pó e água sanitária nem chegam aos candidatos;
- item vizinho errado.

## 3. Experimentos de sugestão no DEV2 (49 produtos)

| Configuração | 1º lugar | Top-3 |
|---|---|---|
| Base (Qwen2.5 7B) | 44,9% | 57,1% |
| Qwen2.5 + expansão de abreviações | 46,9% | 61,2% |
| Qwen2.5 + abreviações + dicas de posição | 40,8% | 59,2% |
| Qwen2.5 + abreviações + dicas + irmãos | 46,9% | 61,2% |
| Qwen3 8B + abreviações | **51,0%** | **63,3%** |
| Qwen3 + abreviações + dicas + irmãos | 42,9% | 57,1% |

- **Abreviações** (`src/ncm/abreviacoes.py`): ajudam. "PIVO SUSP INF" deixou de virar "medicamento para infusão".
- **Dicas de posição** (o modelo chuta posições de 4 dígitos): atrapalham nos dois modelos. Descartadas.
- **Qwen3 8B** entende melhor os produtos: "água sanitária" virou produto de desinfecção, e "serrote" virou ferramenta de corte de madeira.
- Erro recorrente: peças de uso geral indo para a 87.08 (rolamento, palheta, mangueira). Daí a regra da **Nota 2 da Seção XVII**, que exclui de "partes de veículos" rolamentos, parafusos, borracha, Cap. 84 e Cap. 85. É conhecimento oficial da tabela, não um ajuste caso a caso.
- Com 49 casos, 1 produto vale 2 pontos. Por isso as decisões seguintes usam dev + dev2 (90 produtos).

## 4. Rodada de 21/10, último resultado (dev + dev2, 90 produtos)

| Configuração | 1º lugar | Top-3 |
|---|---|---|
| Qwen3 + abreviações | 52,2% | 64,4% |
| **Qwen3 + abreviações + regra da Seção XVII** | **52,2%** | **67,8%** |
| + contexto do negócio + hipóteses | 50,0% | 67,8% |
| Qwen2.5 + abreviações + Seção XVII | 47,2% | 59,6% |

Dos 29 erros restantes, 20 são de busca: o código certo nem chega aos candidatos. A sessão caiu antes de medir a busca por radicais e de terminar a detecção.

---

# Base de conhecimento com bases reais (lojas anonimizadas) (01/11/2026)

## 5. Bases de clientes (`basesProduto/`, fora do git)

- **Loja A**: 5.223 produtos, dos quais 5.177 mercadorias com NCM válido (100%). São 400 NCMs distintos, quase tudo autopeças (capítulos 87, 40, 84 e 85). As descrições seguem o formato "MARCA CÓDIGO - DESCRIÇÃO VEÍCULO".
- **Loja B**: arquivo **incompleto**. O tamanho não é múltiplo de nenhum tamanho de página do Firebird, e a leitura dá "fim do arquivo". Precisa ser copiado de novo.
- Duas observações técnicas:
  - o Firebird só abre o arquivo neste caminho com acento ("Área de Trabalho") quando o nome é passado em UTF-8 (`utf8filename`);
  - a pasta está no OneDrive, que sincroniza dados de cliente com a nuvem; o ideal é guardá-la fora dele.

## 6. "Treinamento" como base de conhecimento (`src/ncm/conhecimento.py`)

- Não é ajuste de pesos do modelo, porque 8 GB de VRAM é pouco para isso. É uma **consulta aos produtos já classificados** (kNN): busca BM25 sobre os radicais das palavras da descrição, sem a marca e o código do fabricante, com voto ponderado entre os 10 mais parecidos.
- `scripts/extrair_base_cliente.py` lê só DESCRICAO e NCM da tabela PRODUTO (somente leitura) e grava em `data/conhecimento.db` (fora do git).

Resultado da consulta sozinha, **sem LLM**:

| Onde | 1º lugar | Top-3 |
|---|---|---|
| Dentro da Loja A (consulta em 80%, teste nos outros 20%, n=1036) | 68,6% | 83,4% |
| Idem, sem nenhuma descrição idêntica (n=947) | 67,7% | 82,4% |
| Automotivos dos conjuntos curados (n=35) | 60,0% | 80,0% |
| dev / dev2 / teste completos (muitos não automotivos) | 27% / 27% / 18% | 37% / 33% / 24% |

Combinação feita fora do modelo, com as respostas do LLM gravadas (dev + dev2): pôr o NCM mais votado em 1º lugar quando a base está confiante leva o top-3 de **67,8% para 72–74%**.

## 7. Base Loja B e o NCM "coringa"

- 36.429 produtos com NCM válido, 555 NCMs distintos, quase tudo autopeças.
- **3.407 produtos (9,4%) estão com 8708.10.00 (para-choques), e só 104 são para-choques.** O resto são molas, freios, cabos, rolamentos e outras peças. É um caso real e grande de NCM válido, porém errado.
- Esses produtos ficam fora da base de conhecimento (`conhecimento.confiavel`), para o sistema não aprender o erro da loja. Na Loja A, só 10 produtos foram descartados pelo mesmo filtro.

Consulta sozinha (kNN, sem LLM), comparando lojas:

| Cenário | 1º lugar | Top-3 |
|---|---|---|
| Loja A consultando os próprios produtos (80/20) | 66,5% | 80,2% |
| Loja B consultando os próprios produtos (80/20) | 64,7% | 83,4% |
| Loja A consultando a Loja B | 46,3% | 65,5% |
| Loja B consultando a Loja A | 31,1% | 47,0% |
| Loja B consultando Loja A + a própria | 64,9% | 83,1% |

O conhecimento da própria loja é o que mais vale. O de outra loja ajuda, mas bem menos.

## 8. LLM + base de conhecimento (dev + dev2, 90 produtos, Qwen3 8B)

| Configuração | 1º lugar | Top-3 | Tempo |
|---|---|---|---|
| Qwen3 + abreviações + Seção XVII | 52,2% | 67,8% | 14,5 s |
| + conhecimento Loja A (o LLM vê os parecidos, e os NCMs deles viram candidatos) | 63,3% | 72,2% | 16,4 s |
| **+ NCM mais votado em 1º quando a base está confiante** | **64,4%** | **75,6%** | 14,7 s |

Por setor (sem → com conhecimento):
- automotivos (31): 58%/71% → **90%/97%**;
- outros setores (59): 49%/66% → 51%/64%. Não muda, porque a Loja A só tem autopeças.

## 9. Detecção de NCM errado (Qwen3 8B + abreviações + Seção XVII + base Loja A)

A IA recebe o produto **com o NCM cadastrado** e decide se ele é suspeito.

Conjuntos:
- **DEV2**: 49 produtos com o NCM certo + 48 com erro plantado (troca 19, outro item do mesmo capítulo 16, vizinho da mesma posição 13).
- **Loja B real**: 40 produtos com o NCM "coringa" 8708.10.00 que não são para-choques (erro **real** da loja) + 40 produtos comuns da mesma loja, presumidos corretos. A base de conhecimento consultada foi só a Loja A, para não vazar.

| Regra | DEV2 acurácia | DEV2 alarme falso | Loja B acurácia | Loja B alarme falso | Erros reais pegos |
|---|---|---|---|---|---|
| fora do top-3 | 84,5% | 30,6% | 81,2% | 37,5% | 40/40 |
| texto oficial "incompatível" | 85,6% | 18,4% | 85,0% | 30,0% | 40/40 |
| **fora do top-3 E incompatível (escolhida)** | **86,6%** | **16,3%** | **88,8%** | **22,5%** | **40/40** |
| fora do top-3 E (incompatível OU comparação contra) | 88,7% | 20,4% | 85,0% | 30,0% | 40/40 |
| antiga (com a 3ª condição) | 85,6% | 18,4% | 88,8% | 22,5% | 40/40 |

- A regra foi escolhida **no DEV2**: é melhor que a antiga nas duas métricas, e mais simples. Na Loja B as duas dão o mesmo resultado.
- Por tipo de erro no DEV2: troca 19/19, capítulo 16/16, vizinho 8/13. O erro difícil é o NCM "quase certo", da mesma posição.
- O sinal da base de conhecimento **não melhorou a detecção**: as regras com ele empatam com as regras sem ele.
- Dos 9 alarmes falsos da Loja B, pelo menos 2 parecem erros reais da loja, e não da IA:
  - COXIM RADIADOR em 8708.40.90 (caixa de câmbio);
  - CILINDRO AUXILIAR EMBREAGEM em 8708.30.90 (freios; o certo seria 8708.93).

  Outros falsos alarmes vêm de abreviações não expandidas ("PRF SXTV" = parafuso sextavado).
- Tempo: 18 a 25 s por produto.
- Ressalva: no DEV2 os erros são plantados. Os 40 "corretos" da Loja B são presumidos, não conferidos.

## 10. Medição final no TESTE2 (01/11, uma única vez)

Configuração final, que agora é o padrão: Qwen3 8B + abreviações + Seção XVII + base de conhecimento da Loja A + NCM mais votado em 1º. Escolhida só com dev + DEV2.

Sugestão (50 produtos):

| Método | 1º lugar | Top-3 |
|---|---|---|
| Versão da 1ª fase (referência medida em 21/10) | 32,0% | 48,0% |
| Busca sozinha, sem LLM | 20,0% | 30,0% |
| Base de conhecimento sozinha, sem LLM | 26,0% | 36,0% |
| Base + busca, sem LLM | 28,0% | 46,0% |
| **Versão final** | **48,0%** | **58,0%** |

- Por setor: automotivos 15/18 (83,3%) no 1º lugar e no top-3; outros setores 9/32 (28,1%) e 14/32 (43,8%).
- O código certo chegou aos candidatos em 78% dos casos. A busca sozinha, com 40 candidatos, chega a 62%.
- Tempo: 13,7 s por produto.
- Dos 21 erros fora do top-3, 14 são de capítulo, 1 de posição e 6 de item. Em 11 deles, o código certo nem chegou aos candidatos.

Detecção de NCM errado (50 certos + 50 errados), com a regra escolhida no DEV2:
- acurácia 86,0%;
- alarme falso 6,0%;
- erros pegos 39/50: troca 20/20, capítulo 14/15, vizinho 5/15;
- tempo: 17,1 s por produto.

NCM inválido: 25/25 nos casos rotulados (vazio, zeros, malformado, inexistente e extinto). Nenhum falso positivo em 168 válidos nem nas 41.606 mercadorias das duas lojas.

Os nomes das lojas foram anonimizados (Loja A e Loja B) no código, nas bases e nos resultados.
