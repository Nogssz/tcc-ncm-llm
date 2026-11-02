"""Gera tcc_latex/postextuais/apendice.tex a partir do código e dos
resultados gravados, para o texto nunca divergir do protótipo:

A. conjuntos de casos (dev15, dev, teste, DEV2, TESTE2);
B. prompts da versão final (copiados das constantes do código);
C. respostas da versão final no TESTE2 (arquivo de avaliação indicado).

Uso: python scripts/gerar_apendice.py data/avaliacoes/teste2_final_<...>.json
"""
import json
import sys
import textwrap
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.avaliar import DEV  # noqa: E402
from scripts.conjuntos_v2 import DEV2, TESTE2  # noqa: E402
from scripts.eval_ncm_suggestions import CASOS as DEV15  # noqa: E402
from scripts.seed_produtos_teste import PRODUTOS as TESTE  # noqa: E402
from src.agent.ncm_suggester import PROMPT_ANALISE, REGRA_SECAO17, SYSTEM_PROMPT  # noqa: E402
from src.agent.ncm_verificador import PROMPT_VERIFICACAO  # noqa: E402

SAIDA = RAIZ / "tcc_latex" / "postextuais" / "apendice.tex"


def tex(s: str) -> str:
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}")]:
        s = s.replace(a, b)
    return s


def tabela(titulo: str, rotulo: str, colunas: list[tuple[str, str]], linhas: list[list[str]]) -> str:
    spec = " ".join(c for c, _ in colunas)
    cab = " & ".join(rf"\textbf{{{t}}}" for _, t in colunas) + r" \\"
    corpo = "\n".join(" & ".join(linha) + r" \\" for linha in linhas)
    return f"""
\\begin{{center}}
\\small
\\begin{{longtable}}{{{spec}}}
\\caption{{{titulo}}}\\label{{{rotulo}}} \\\\
\\hline
{cab}
\\hline
\\endfirsthead
\\hline
{cab}
\\hline
\\endhead
\\hline
\\endfoot
{corpo}
\\end{{longtable}}
\\end{{center}}
"""


def tabela_conjunto(titulo, rotulo, casos, com_setor=True):
    if not com_setor:
        linhas = [[str(i), tex(c[0]), ", ".join(c[1])] for i, c in enumerate(casos, 1)]
        return tabela(titulo, rotulo, [("r", "Nº"), ("p{7.6cm}", "Descrição"), ("p{6.4cm}", "NCM aceito(s)")], linhas)
    linhas = [[str(i), tex(d), ", ".join(e), tex(s)] for i, (d, e, s) in enumerate(casos, 1)]
    return tabela(titulo, rotulo, [("r", "Nº"), ("p{6.6cm}", "Descrição cadastrada"),
                                   ("p{4.4cm}", "NCM aceito(s)"), ("p{2.6cm}", "Setor")], linhas)


def verbatim(texto: str) -> str:
    linhas = []
    for linha in texto.strip("\n").split("\n"):
        linhas += textwrap.wrap(linha, 66, break_on_hyphens=False) or [""]
    return "{\\small\n\\begin{verbatim}\n" + "\n".join(linhas) + "\n\\end{verbatim}\n}\n"


def apendice_resultados(caminho: Path) -> str:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    linhas = []
    for i, c in enumerate(dados["casos"], 1):
        pos = c.get("posicao_certo")
        acerto = "1º" if pos == 1 else (f"{pos}º" if pos else "não")
        opcoes = r" \newline ".join(c.get("opcoes", [])) or "--"
        linhas.append([str(i), tex(c["descricao"]), ", ".join(c["esperados"]), opcoes, acerto])
    return tabela("Respostas da versão final no conjunto TESTE2", "tab:ap_teste2_respostas",
                  [("r", "Nº"), ("p{5.2cm}", "Descrição cadastrada"), ("p{3.0cm}", "NCM aceito(s)"),
                   ("p{2.6cm}", "Opções sugeridas (em ordem)"), ("c", "Acerto")], linhas)


def main():
    resultado = Path(sys.argv[1])
    partes = [r"""\begin{apendicesenv}

\chapter{Conjuntos de Casos}
\label{ap:conjuntos}

Este apêndice lista os produtos dos conjuntos utilizados na avaliação da sugestão, com as descrições exatamente como foram fornecidas ao sistema e os códigos NCM aceitos como corretos. Os conjuntos dev15, dev e teste foram usados nas primeiras versões; o DEV2 e o TESTE2 foram sorteados, com semente fixa, de um mesmo grupo de 99 produtos novos, e o TESTE2 foi medido uma única vez, com a versão final.
"""]
    partes.append(tabela_conjunto("Conjunto dev15", "tab:ap_dev15", DEV15, com_setor=False))
    partes.append(tabela_conjunto("Conjunto dev", "tab:ap_dev", DEV))
    partes.append(tabela_conjunto("Conjunto teste", "tab:ap_teste", TESTE))
    partes.append(tabela_conjunto("Conjunto DEV2", "tab:ap_dev2", DEV2))
    partes.append(tabela_conjunto("Conjunto TESTE2", "tab:ap_teste2", TESTE2))
    partes.append(r"""
\chapter{\textit{Prompts} da Versão Final}
\label{ap:prompts}

Os \textit{prompts} são reproduzidos sem acentuação, como no código-fonte do protótipo. Os exemplos citados neles não pertencem a nenhum conjunto de avaliação.

\section*{\textit{Prompt} da análise do produto}
""")
    partes.append(verbatim(PROMPT_ANALISE))
    partes.append("\n\\section*{\\textit{Prompt} de sistema das escolhas de capítulo e itens}\n")
    partes.append(verbatim(SYSTEM_PROMPT + REGRA_SECAO17))
    partes.append("\n\\section*{\\textit{Prompt} de sistema da verificação do NCM cadastrado}\n")
    partes.append(verbatim(PROMPT_VERIFICACAO))
    partes.append(r"""
\chapter{Respostas da Versão Final no Conjunto de Teste}
\label{ap:respostas}

Este apêndice apresenta, para cada produto do TESTE2, as três opções sugeridas pela versão final e a posição em que o código correto apareceu. A execução completa, com a interpretação do modelo, os capítulos escolhidos e o tempo de cada produto, está disponível no repositório do protótipo, no diretório \texttt{data/avaliacoes}.
""")
    partes.append(apendice_resultados(resultado))
    partes.append("\n\\end{apendicesenv}\n")
    SAIDA.write_text("".join(partes), encoding="utf-8")
    print(f"ok: {SAIDA}")


if __name__ == "__main__":
    main()
