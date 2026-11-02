"""Expansao de sinonimos pra busca de NCM. Duas camadas:

1. WordNet em portugues (via NLTK/Open Multilingual Wordnet) -- automatico,
   gratuito, offline, sem depender do Ollama. Cobre a maioria dos casos
   testados (ex.: 'bateria' -> 'acumulador', 'carro' -> 'automovel').
2. Lista manual pequena -- so pros casos que nem WordNet nem o LLM
   conhecem (ex.: 'azulejo' -> 'ladrilho', termo oficial da tabela NCM).
   Cresce de forma REATIVA: só ganha uma entrada quando um caso real
   aparece e nem a camada automatica resolve (ver historico de testes com
   'AZULEIJO DE BANHEIRO AZUL').

Testamos tambem pedir sinonimos direto pro llama3.1 (geracao de texto, nao
embedding) -- resultado pior que o WordNet e nao deterministico (varia a
cada chamada), entao nao foi usado aqui.
"""
import nltk

try:
    nltk.data.find("corpora/wordnet")
except LookupError:
    nltk.download("wordnet", quiet=True)
try:
    nltk.data.find("corpora/omw-1.4")
except LookupError:
    nltk.download("omw-1.4", quiet=True)

from nltk.corpus import wordnet as wn  # noqa: E402

# So os pares que nenhuma fonte automatica (WordNet, embeddings, LLM)
# conseguiu conectar sozinha, descobertos testando produtos reais.
SINONIMOS_MANUAIS = {
    "azulejo": {"ladrilho"},
    "azuleijo": {"ladrilho"},  # erro de digitacao comum, visto em teste real
}


def obter_sinonimos(palavra: str) -> set[str]:
    """Sinonimos conhecidos de uma palavra (WordNet + lista manual). Nao
    inclui a propria palavra -- so os termos alternativos."""
    palavra = palavra.lower()
    sinonimos: set[str] = set(SINONIMOS_MANUAIS.get(palavra, set()))

    try:
        for synset in wn.synsets(palavra, lang="por"):
            for lemma in synset.lemma_names("por"):
                termo = lemma.lower().replace("_", " ")
                if termo != palavra:
                    sinonimos.add(termo)
    except Exception:
        pass  # WordNet indisponivel nao deve quebrar a busca

    return sinonimos
