"""
Sonda minima: `ad_type` vazio devolve mais campanhas que `ad_type=all`?

POR QUE ISTO EXISTE, depois de eu ter declarado teto.

A varredura da documentacao em 04/11/2026 confirmou que o modulo 105 tem 25
endpoints e que `get_product_level_campaign_id_list` e o UNICO de listagem.
Mas a propria pagina dele diz, na tabela de parametros:

    ad_type   string   Required: False   Any of ["","all","auto","manual"]

A string vazia esta listada como valor valido, SEPARADA de "all". Na sonda 1
eu testei all, auto e manual -- e chutes invalidos -- e nunca testei "".

A hipotese: "all" pode significar "todos os tipos QUE ESTE ENDPOINT COBRE"
(auto + manual) enquanto "" pode significar "sem filtro nenhum". E so uma
hipotese, mas a descricao do endpoint reforca a suspeita de que falta algo:

    "Call this API to fetch all the product campaign ids displayed on
     advertiser platform under a specific Shop"

Hoje isso e falso. As campanhas "Lancamentos" aparecem na plataforma e nao
vem na listagem. Ou a descricao esta errada, ou existe um jeito de pedir que
a gente ainda nao usou.

COMO LER O RESULTADO:

  "" devolve MAIS que 25  -> achamos o caminho. Nada de cadastro manual.
  "" devolve 25, igual    -> teto confirmado por mais um lado. Cadastro manual.
  "" devolve erro         -> a doc lista um valor que a API nao aceita; vale
                             registrar, mas nao muda nada na pratica.

Gasta 2 chamadas: uma com "" e uma com "all", na mesma rodada, para comparar
sem depender de memoria de execucao anterior.

Uso:
    cd ~/Documents/"Casa e Patas"/data-pipeline
    source ~/.venvs/cp-bigquery/bin/activate
    export TOKEN_BUCKET=cp-pipeline-tokens
    python extraction/shopee/sonda_adtype_vazio.py
"""

import hashlib
import hmac
import os
import time

import requests
from dotenv import load_dotenv

from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"
PATH = "/api/v2/ads/get_product_level_campaign_id_list"

# Campanhas que sabemos existir na plataforma e que o `all` nao devolve.
# 117615261 e a "Lancamentos 1", medida em 04/11/2026.
ESPERADAS_AUSENTES = {117615261}

ERROS_RATE_LIMIT = ("error_rate_limit", "ads.rate_limit.exceed_api",
                    "ads_rate_limit_total_api")
TENTATIVAS = 4
ESPERA_INICIAL = 10.0
ESPERA_MAX = 90.0


def generate_sign(path: str, ts: int, token: str, shop: int) -> str:
    base = f"{PARTNER_ID}{path}{ts}{token}{shop}"
    return hmac.new(PARTNER_KEY.encode("utf-8"), base.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def chamar(extra: dict) -> dict:
    espera = ESPERA_INICIAL
    for tentativa in range(1, TENTATIVAS + 1):
        token, shop = get_valid_access_token()
        ts = int(time.time())
        params = {
            "partner_id": PARTNER_ID,
            "timestamp": ts,
            "sign": generate_sign(PATH, ts, token, shop),
            "access_token": token,
            "shop_id": shop,
            **extra,
        }
        try:
            dados = requests.get(f"{API_HOST}{PATH}", params=params,
                                 timeout=45).json()
        except Exception as e:                  # noqa: BLE001
            return {"error": "falha_local", "message": str(e)}

        if (dados.get("error") or "") not in ERROS_RATE_LIMIT:
            return dados
        if tentativa == TENTATIVAS:
            return dados
        print(f"    rate limit ({tentativa}/{TENTATIVAS}); "
              f"aguardando {espera:.0f}s.", flush=True)
        time.sleep(espera)
        espera = min(espera * 2, ESPERA_MAX)
    return dados


def listar(ad_type: str) -> tuple:
    """Devolve (set_de_ids, erro_ou_None). Pagina ate acabar."""
    ids, offset = set(), 0
    while True:
        dados = chamar({"ad_type": ad_type, "offset": offset, "limit": 100})
        if dados.get("error"):
            return ids, f"{dados['error']} {dados.get('message','')}".strip()

        resposta = dados.get("response") or {}
        lote = resposta.get("campaign_list") or []
        ids |= {c["campaign_id"] for c in lote
                if isinstance(c, dict) and "campaign_id" in c}

        if not resposta.get("has_next_page") or not lote:
            return ids, None
        offset += len(lote)
        time.sleep(1.0)


if __name__ == "__main__":
    print("Sonda: ad_type vazio x ad_type=all\n")

    resultados = {}
    for rotulo, valor in [('vazio ("")', ""), ('"all"', "all")]:
        print(f"[{rotulo}]")
        ids, erro = listar(valor)
        if erro:
            print(f"  ERRO: {erro}")
        else:
            print(f"  {len(ids)} campanha(s)")
        resultados[valor] = ids
        time.sleep(2.0)

    vazio, todos = resultados.get("", set()), resultados.get("all", set())

    print("\n--- comparacao ---")
    print(f"  vazio: {len(vazio)}   all: {len(todos)}")

    so_no_vazio = vazio - todos
    if so_no_vazio:
        print(f"\n  >>> O VAZIO DEVOLVE {len(so_no_vazio)} CAMPANHA(S) A MAIS:")
        for cid in sorted(so_no_vazio):
            marca = "  <-- a que faltava!" if cid in ESPERADAS_AUSENTES else ""
            print(f"        {cid}{marca}")
        print("      Trocar ad_type='all' por ad_type='' no get_campaign_ids()")
        print("      resolve sem cadastro manual nenhum.")
    elif vazio and vazio == todos:
        print("\n  >>> IDENTICOS. O teto esta confirmado por mais um lado:")
        print("      nenhum valor de ad_type alcanca as campanhas novas.")
        print("      O cadastro manual do campaign_id e o caminho.")
    else:
        print("\n  >>> Inconclusivo (erro em alguma das duas chamadas).")

    if ESPERADAS_AUSENTES & todos:
        print("\n  NOTA: a Shopee passou a listar sozinha o que antes faltava.")
