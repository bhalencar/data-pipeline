"""
Sonda 3: o endpoint de PERFORMANCE serve um id que a LISTAGEM nao devolve?

A PERGUNTA, e por que ela e boa. Em 03/11/2026 provei que
`get_product_level_campaign_id_list` nao enumera campanha GMV Max -- a propria
API devolveu "ad_type: value must be in list [ all auto manual]". Dai eu
concluí que a familia Product Ads inteira estava fechada para GMV Max, e
parti para o modulo GMS.

Foi salto meu. Listagem e performance sao endpoints DIFERENTES. A restricao
que provei e da listagem. Se `get_product_campaign_daily_performance` aceitar
o id da campanha GMV Max, o conserto inteiro vira uma seed de ids avulsos e o
`master_ads` nao muda uma linha -- com grao diario e com `ad_name` trazendo o
nome de campanha que o Bruno quer.

O DESENHO EXPERIMENTAL, que e o ponto deste arquivo. A API de Ads deste
projeto tem um modo de falha documentado: formato de data errado devolve
VAZIO em vez de erro. Entao pedir so o id novo e receber vazio nao prova
nada -- pode ser id nao servido, pode ser erro meu de parametro.

Por isso a sonda manda OS DOIS IDS NA MESMA CHAMADA:

  CONTROLE  116939634  campanha que ja esta no master_ads e sabemos que responde
  TESTE     <o id que voce passar>

  Voltam os dois  -> o id e servido. Conserto trivial.
  Volta so o controle -> o id nao e servido. Prova limpa: mesma chamada,
                         mesmo formato, mesma autenticacao.
  Nao volta nenhum -> erro meu de parametro. Nada se conclui sobre o id.

A terceira linha e o motivo de existir o controle. Sem ele, esse caso seria
confundido com o segundo.

Uso -- pegue o campaign_id na URL do Seller Centre ao abrir a campanha:

    cd ~/Documents/"Casa e Patas"/data-pipeline
    source ~/.venvs/cp-bigquery/bin/activate
    export TOKEN_BUCKET=cp-pipeline-tokens
    python extraction/shopee/sonda_id_direto.py 123456789

Gasta 4 chamadas no total. SO LE.
"""

import hashlib
import hmac
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

# Campanha que ja esta no master_ads com gasto conhecido: R$ 62,84 em out/26.
# E o controle do experimento.
ID_CONTROLE = 116939634

ERROS_RATE_LIMIT = (
    "error_rate_limit",
    "ads.rate_limit.exceed_api",
    "ads_rate_limit_total_api",
)
TENTATIVAS = 4
ESPERA_INICIAL = 10.0
ESPERA_MAX = 90.0


def generate_sign(path: str, ts: int, token: str, shop: int) -> str:
    base = f"{PARTNER_ID}{path}{ts}{token}{shop}"
    return hmac.new(PARTNER_KEY.encode("utf-8"), base.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def chamar(path: str, extra: dict) -> dict:
    """Sign refeito a cada tentativa: o timestamp entra na assinatura."""
    espera = ESPERA_INICIAL

    for tentativa in range(1, TENTATIVAS + 1):
        token, shop = get_valid_access_token()
        ts = int(time.time())
        params = {
            "partner_id": PARTNER_ID,
            "timestamp": ts,
            "sign": generate_sign(path, ts, token, shop),
            "access_token": token,
            "shop_id": shop,
            **extra,
        }
        try:
            dados = requests.get(f"{API_HOST}{path}", params=params,
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


def lista_da_resposta(dados: dict) -> list:
    resposta = dados.get("response") or []
    if isinstance(resposta, dict):
        resposta = next((v for v in resposta.values() if isinstance(v, list)), [])
    return [r for r in resposta if isinstance(r, dict)]


def veredito(devolvidos: set, teste: int) -> None:
    tem_controle = ID_CONTROLE in devolvidos
    tem_teste = teste in devolvidos

    print()
    if tem_controle and tem_teste:
        print("  >>> O ID E SERVIDO. O endpoint de performance aceita a campanha")
        print("      GMV Max mesmo ela nao saindo na listagem. O conserto e uma")
        print("      seed de ids avulsos no get_campaign_ids(); master_ads nao muda.")
    elif tem_controle and not tem_teste:
        print("  >>> O ID NAO E SERVIDO. Prova limpa: mesma chamada, mesmo")
        print("      formato de data, mesma autenticacao, e so o controle voltou.")
        print("      O caminho volta a ser a familia GMS (get_gms_campaign_performance).")
    elif not tem_controle:
        print("  >>> INCONCLUSIVO. Nem o controle voltou, entao errei algum")
        print("      parametro. Nada se conclui sobre o id de teste.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Falta o campaign_id a testar.\n"
                 "  python extraction/shopee/sonda_id_direto.py 123456789\n"
                 "O id esta na URL do Seller Centre ao abrir a campanha.")

    try:
        id_teste = int(sys.argv[1])
    except ValueError:
        sys.exit(f"'{sys.argv[1]}' nao e um campaign_id. Esperado so numero.")

    if id_teste == ID_CONTROLE:
        sys.exit(f"{id_teste} e o proprio controle. Passe o id da campanha nova.")

    fim = datetime.now().date() - timedelta(days=1)
    inicio = date(2026, 10, 1)
    ids = [ID_CONTROLE, id_teste]

    print(f"Sonda de id direto — {inicio} a {fim}")
    print(f"  controle: {ID_CONTROLE}   teste: {id_teste}\n")

    # --------------------------------------------- 1. performance diaria
    print("[1/2] get_product_campaign_daily_performance, os dois ids juntos")
    dados = chamar("/api/v2/ads/get_product_campaign_daily_performance", {
        "start_date": inicio.strftime(FMT_ADS),
        "end_date": fim.strftime(FMT_ADS),
        "campaign_id_list": ",".join(str(i) for i in ids),
    })

    if dados.get("error"):
        print(f"  {dados['error']}: {dados.get('message', '')}")
        devolvidos = set()
    else:
        devolvidos = set()
        for camp in lista_da_resposta(dados):
            cid = camp.get("campaign_id")
            devolvidos.add(cid)
            gasto = sum(float(m.get("expense") or 0)
                        for m in camp.get("metrics_list") or [])
            dias = len(camp.get("metrics_list") or [])
            marca = "CONTROLE" if cid == ID_CONTROLE else "TESTE   "
            print(f"  {marca} {cid}  R$ {gasto:>8.2f} em {dias} dia(s)")
            print(f"           ad_type={camp.get('ad_type')}  "
                  f"ad_name={camp.get('ad_name')}")

        if not devolvidos:
            print("  Resposta sem nenhuma campanha -- o vazio silencioso.")

    veredito(devolvidos, id_teste)

    # --------------------------------------------- 2. setting (item, status)
    # O master_ads faz left join com o setting para trazer item_id, status,
    # orcamento e meta_roas. Se o id passar na performance e nao no setting,
    # a linha entra com essas colunas nulas -- melhor saber agora.
    print("\n[2/2] get_product_level_campaign_setting_info, os dois ids juntos")
    time.sleep(PAUSA_SEG)
    dados = chamar("/api/v2/ads/get_product_level_campaign_setting_info", {
        "campaign_id_list": ",".join(str(i) for i in ids),
        "info_type_list": "1,2,3",
    })

    if dados.get("error"):
        print(f"  {dados['error']}: {dados.get('message', '')}")
    else:
        vistos = set()
        for camp in lista_da_resposta(dados):
            cid = camp.get("campaign_id")
            vistos.add(cid)
            comum = camp.get("common_info") or {}
            marca = "CONTROLE" if cid == ID_CONTROLE else "TESTE   "
            print(f"  {marca} {cid}  ad_name={comum.get('ad_name')}  "
                  f"status={comum.get('campaign_status')}")
            print(f"           item_id_list={comum.get('item_id_list')}")
        if id_teste in vistos:
            print("\n  Setting tambem responde: o left join do master_ads fica completo.")
        elif ID_CONTROLE in vistos:
            print("\n  Setting NAO responde para o id de teste: a linha entraria com")
            print("  item_id, status, orcamento e meta_roas nulos. O gasto entra")
            print("  igual -- o left join e de proposito -- mas vale saber.")

    print("\nFim. Me manda a saida inteira.")
