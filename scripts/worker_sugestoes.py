"""Worker de segundo plano: a cada N segundos consulta o ERP e

1. para cada produto novo com NCM inválido (vazio/inexistente), gera as
   sugestões da IA e guarda no cache local (src/db/cache_sugestoes.py);
2. em lotes pequenos, verifica produtos com NCM válido para encontrar NCM
   errado (código existente, mas de outro produto -- ver
   src/agent/ncm_verificador.py). Os mais recentes vêm primeiro, e cada
   produto só é verificado de novo se a descrição ou o NCM mudarem.

É o gatilho "cadastrou -> a IA já agiu" do TCC, sem precisar mexer no
código nem no banco do Lux Auto (só leitura, por polling -- trigger/evento
no Firebird exigiria alterar o ERP).

Com --notificar, também mostra uma notificação do Windows.

Uso:
  python scripts/worker_sugestoes.py               # roda em loop
  python scripts/worker_sugestoes.py --notificar   # + notificação do Windows
  python scripts/worker_sugestoes.py --uma-vez     # processa o que tem e sai
  python scripts/worker_sugestoes.py --sem-verificacao   # só NCM inválido
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.ncm_suggester import build_ncm_agent, sugerir_ncm  # noqa: E402
from src.agent.ncm_verificador import verificar_ncm  # noqa: E402
from src.db import cache_sugestoes  # noqa: E402
from src.db.produtos import listar_produtos_ncm_invalido, listar_produtos_ncm_valido  # noqa: E402

INTERVALO_S = 20
VERIFICACOES_POR_CICLO = 5


def _notificar(titulo: str, corpo: str) -> None:
    try:
        from win11toast import notify
    except ImportError:
        return
    notify(titulo, corpo)


def processar(modelo, notificar: bool) -> int:
    feitos = 0
    for p in listar_produtos_ncm_invalido():
        codigo, descricao = p["CODIGO"], (p["DESCRICAO"] or "").strip()
        if not descricao or cache_sugestoes.buscar(codigo, descricao):
            continue
        inicio = time.time()
        try:
            sugestao = sugerir_ncm(modelo, descricao, codigo_produto=codigo)
        except Exception as e:  # Ollama instável: tenta de novo no próximo ciclo
            print(f"  #{codigo} {descricao}: falhou ({type(e).__name__}), tento de novo depois", flush=True)
            continue
        cache_sugestoes.salvar(codigo, descricao, sugestao.model_dump())
        feitos += 1
        print(f"  #{codigo} {descricao}: {[o.codigo for o in sugestao.opcoes]} ({time.time() - inicio:.0f}s)", flush=True)
        if notificar:
            if sugestao.opcoes:
                o = sugestao.opcoes[0]
                corpo = f"Sugestão: {o.codigo} - {o.descricao[:90]}\nAbra a tela de NCM para conferir e aprovar."
            else:
                corpo = "A IA não encontrou uma sugestão. Abra a tela de NCM para classificar."
            _notificar(f"Produto #{codigo} '{descricao}' sem NCM válido", corpo)
    return feitos


def verificar_validos(modelo, notificar: bool, limite: int = VERIFICACOES_POR_CICLO) -> int:
    feitos = 0
    for p in listar_produtos_ncm_valido():
        if feitos >= limite:
            break
        codigo, descricao, ncm = p["CODIGO"], p["DESCRICAO"].strip(), (p["NCM"] or "").strip()
        if cache_sugestoes.buscar_verificacao(codigo, descricao, ncm):
            continue
        inicio = time.time()
        try:
            v = verificar_ncm(modelo, descricao, ncm, codigo_produto=codigo)
        except Exception as e:
            print(f"  #{codigo} {descricao}: verificação falhou ({type(e).__name__})", flush=True)
            break
        cache_sugestoes.salvar_verificacao(codigo, descricao, ncm, v.status, v.model_dump())
        feitos += 1
        print(f"  #{codigo} {descricao} NCM {v.ncm_cadastrado}: {v.status} ({time.time() - inicio:.0f}s)", flush=True)
        if notificar and v.status == "suspeito" and v.sugestao and v.sugestao.opcoes:
            o = v.sugestao.opcoes[0]
            _notificar(
                f"Produto #{codigo} '{descricao}': NCM {v.ncm_cadastrado} parece errado",
                f"{v.motivo}\nSugestão: {o.codigo} - {o.descricao[:80]}",
            )
    return feitos


def main():
    notificar = "--notificar" in sys.argv
    verificar = "--sem-verificacao" not in sys.argv
    modelo = build_ncm_agent()
    print(f"Worker de NCM ({modelo.model}), verificando o ERP a cada {INTERVALO_S}s...", flush=True)
    while True:
        try:
            processar(modelo, notificar)
            if verificar:
                verificar_validos(modelo, notificar)
        except Exception as e:  # ERP fora do ar etc.: não derruba o worker
            print(f"Erro no ciclo: {type(e).__name__}: {e}", flush=True)
        if "--uma-vez" in sys.argv:
            return
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    main()
