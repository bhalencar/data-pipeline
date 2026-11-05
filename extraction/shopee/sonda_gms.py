"""
Sonda GMS: os endpoints de GMV Max enumeram campanha sozinhos?

A PERGUNTA, e por que ela vale mais que todas as anteriores.

Em 04/11/2026 a loja tem SEIS campanhas ativas, cinco delas multi-produto
("Lancamentos 1" a "5"), e o Bruno vai criar mais -- a otimizacao e viva. O
`get_product_level_campaign_id_list` nao enumera nenhuma das cinco: aceita so
`ad_type` in [all, auto, manual] e devolve 25 campanhas antigas.

A saida que eu tinha escrito -- cadastrar id a mao num CSV -- nasceu
desatualizada: fiz para UMA campanha e ja sao cinco. Nao escala, e o proprio
Bruno disse isso antes de mim.

A documentacao diz que `campaign_id` e OPCIONAL nos dois endpoints GMS. Se
omitir e vier tudo, acabou: descoberta automatica, nenhuma lista a mao, e o
nivel de item de brinde. Se exigir o id, voltamos ao cadastro manual sabendo
que e o unico caminho, e nao por falta de ter perguntado.

O QUE JA SABEMOS, para nao perguntar de novo:

  - `get_product_campaign_daily_performance` SERVE o id 117615261 quando a
    gente passa na mao: 34 dias, R$ 38,46, ad_type=manual.
  - `get_product_level_campaign_setting_info` RECUSA o mesmo id:
    "auto & manual product ad types only". Os dois discordam.
  - `check_create_gms_product_campaign_eligibility` respondeu SEM ERRO, entao
    o modulo GMS existe neste host e o app tem permissao nele.
  - Nao existe `get_gms_campaign_id_list` (error_not_found).

DOIS BUGS MEUS QUE ESTA VERSAO CORRIGE:

  1. A doc diz POST para os dois endpoints GMS. A versao anterior usava GET.
     No padrao da Shopee os parametros de AUTENTICACAO vao na query string e os
     de NEGOCIO vao no corpo JSON -- mesmo formato que o token_manager ja usa
     para renovar token.
  2. Faltava retentativa de rate limit. Foi o que matou a rodada de 03/11.

FORMATO DE DATA: DD-MM-YYYY, como o resto do modulo de Ads. A doc mostra
"11-11-2025" no exemplo, o que confirma.

SO LE. Nenhum create_ ou edit_ entra aqui. Gasta no maximo 4 chamadas.

Uso:
    cd ~/Documents/"Casa e Patas"/data-pipeline
    source ~/.venvs/cp-bigquery/bin/activate
    export TOKEN_BUCKET=cp-pipeline-tokens
    python extraction/shopee/sonda_gms.py
"""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

FMT_ADS = "%d-%m-%Y"
PAUSA_SEG = 2.0

# Campanha conhecida, usada so se a enumeracao falhar.
ID_CONHECIDO = 117615261

ERROS_RATE_LIMIT = (
    "error_rate_limit",
    "ads.rate_limit.exceed_api",
    "ads_rate_limit_total_api",
)
TENTATIVAS = 4
ESPERA_INICIAL = 10.0
ESPERA_MAX = 90.0

CAMPANHA = "/api/v2/ads/get_gms_campaign_performance"
ITEM = "/api/v2/ads/get_gms_item_performance"


def generate_sign(path: str, ts: int, token: str, shop: int) -> str:
    base = f"{PARTNER_ID}{path}{ts}{token}{shop}"
    return hmac.new(PARTNER_KEY.encode("utf-8"), base.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def chamar(path: str, corpo: dict) -> dict:
    """
    POST: autenticacao na query string, negocio no corpo JSON.

    E o mesmo formato que o `_refresh_access_token` do token_manager usa --
    partner_id/timestamp/sign na URL, o resto no body. A assinatura NAO inclui
    o corpo, so partner_id + path + timestamp + token + shop_id.
    """
    espera = ESPERA_INICIAL

    for tentativa in range(1, TENTATIVAS + 1):
        token, shop = get_valid_access_token()
        ts = int(time.time())
        url = (f"{API_HOST}{path}"
               f"?partner_id={PARTNER_ID}&timestamp={ts}"
               f"&access_token={token}&shop_id={shop}"
               f"&sign={generate_sign(path, ts, token, shop)}")
        try:
            dados = requests.post(url, json=corpo, timeout=45).json()
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


def mostrar(rotulo: str, dados: dict, limite: int = 2500) -> None:
    print(f"  --- {rotulo} ---")
    if dados.get("error"):
        print(f"  {dados['error']}: {dados.get('message', '')}")
        return
    texto = json.dumps(dados.get("response"), ensure_ascii=False, indent=2)
    for linha in texto[:limite].splitlines():
        print(f"    {linha}")
    if len(texto) > limite:
        print("    ... (cortado)")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        inicio = date.fromisoformat(sys.argv[1])
        fim = date.fromisoformat(sys.argv[2])
    else:
        fim = datetime.now().date() - timedelta(days=1)
        inicio = fim - timedelta(days=13)      # 14 dias, dentro do limite de 3 meses

    janela = {"start_date": inicio.strftime(FMT_ADS),
              "end_date": fim.strftime(FMT_ADS)}

    print(f"Sonda GMS — {inicio} a {fim} (POST, datas em DD-MM-YYYY)\n")

    # ------------------------------------------------ 1. enumera campanha?
    print("[1/3] get_gms_campaign_performance SEM campaign_id")
    print("      (a pergunta que decide: ele lista as campanhas sozinho?)")
    camp = chamar(CAMPANHA, dict(janela))
    mostrar("campanha, sem id", camp)
    time.sleep(PAUSA_SEG)

    # ------------------------------------------------ 2. enumera item?
    print("\n[2/3] get_gms_item_performance SEM campaign_id")
    print("      (e o print 'Desempenho do Produto' do Seller Centre)")
    itens = chamar(ITEM, dict(janela, offset=0, limit=100))
    mostrar("item, sem id", itens)
    time.sleep(PAUSA_SEG)

    # ------------------------------------- 3. so se os dois acima falharem
    precisa_id = bool(camp.get("error")) and bool(itens.get("error"))
    if precisa_id:
        print(f"\n[3/3] Os dois recusaram sem id. Tentando com "
              f"campaign_id={ID_CONHECIDO}")
        print("      (se funcionar, o id e obrigatorio e o cadastro manual")
        print("       passa a ser o unico caminho conhecido)")
        com_id = chamar(CAMPANHA, dict(janela, campaign_id=ID_CONHECIDO))
        mostrar(f"campanha, id={ID_CONHECIDO}", com_id)
    else:
        print("\n[3/3] Pulado: pelo menos um dos dois respondeu sem id.")

    print("\n=== o que procurar na saida ===")
    print("  Vieram VARIAS campanhas/itens sem passar id -> descoberta")
    print("    automatica. Nenhuma lista a mao, e o nivel de item resolve o")
    print("    'quais anuncios pausar dentro da campanha'.")
    print("  Veio UMA so, ou erro pedindo campaign_id -> o id e obrigatorio;")
    print("    o cadastro manual vira o unico caminho e a gente assume isso")
    print("    de olhos abertos.")
    print("  error_not_whitelisted_for_product_gms -> a loja nao esta liberada")
    print("    no modulo; vira pedido a Shopee, nao conserto de codigo.")
    print("\nFim. Me manda a saida inteira.")
