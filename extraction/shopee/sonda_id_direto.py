"""
Sonda 3: o endpoint de PERFORMANCE serve um id que a LISTAGEM nao devolve?

O QUE JA ESTA RESPONDIDO, e nao precisa ser perguntado de novo.

A primeira rodada desta sonda (04/11/2026) morreu na etapa 1 por erro meu --
janela de 34 dias contra um limite de 30 -- mas a etapa 2 respondeu sozinha:

    get_product_level_campaign_setting_info
    -> error_param: campaign_id_list: has invalid campaignIDs([117615261]),
       please pass campaign ids of auto & manual product ad types only

A Shopee diz com todas as letras que a campanha "Lancamentos 1" NAO e do tipo
auto nem manual. O endpoint de setting a recusa POR TIPO. Como e dele que o
`master_ads` puxa item_id, status, orcamento e meta_roas, essas colunas viriam
nulas mesmo se a performance funcionasse.

Por isso a etapa de setting saiu desta versao: a resposta ja esta acima e
repetir a chamada so gasta cota.

O QUE AINDA NAO ESTA RESPONDIDO, e e so isto:

    `get_product_campaign_daily_performance` serve esse id, ou recusa igual?

Se servir, o gasto diario e o `ad_name` entram no master_ads via seed de ids
avulsos, e so as colunas de configuracao ficam nulas -- o left join ja e de
proposito, e perder o SKU e muito melhor que perder o gasto. Se recusar, a
familia Product Ads esta fechada e o caminho e o modulo GMS.

O DESENHO EXPERIMENTAL continua o mesmo, e e o ponto do arquivo: os DOIS ids
vao na MESMA chamada.

  CONTROLE  116939634  ja esta no master_ads, sabemos que responde
  TESTE     117615261  "Lancamentos 1"

  Voltam os dois       -> o id e servido.
  Volta so o controle  -> nao e servido. Prova limpa: mesma chamada, mesmo
                          formato de data, mesma autenticacao.
  Nao volta nenhum     -> erro meu. Nada se conclui.

A terceira linha e o motivo de existir o controle -- e foi exatamente o que
aconteceu na rodada passada.

O QUE MUDOU NESTA VERSAO. Fatiamento de 30 dias, copiado do `fatiar()` do
get_ads.py. A janela de 34 dias devolveu
`ads.performance.error_date_range_too_long` e derrubou a etapa inteira.

SO LE. Gasta 2 chamadas.

Uso:
    cd ~/Documents/"Casa e Patas"/data-pipeline
    source ~/.venvs/cp-bigquery/bin/activate
    export TOKEN_BUCKET=cp-pipeline-tokens
    python extraction/shopee/sonda_id_direto.py 117615261
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
MAX_DIAS = 30          # medido: 31 dias falha. Mesmo limite do get_ads.py.
PAUSA_SEG = 2.0

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


def fatiar(inicio: date, fim: date, max_dias: int = MAX_DIAS) -> list:
    """Quebra [inicio, fim] em fatias de no maximo max_dias INCLUSIVOS."""
    fatias, cursor = [], inicio
    while cursor <= fim:
        fim_fatia = min(cursor + timedelta(days=max_dias - 1), fim)
        fatias.append((cursor, fim_fatia))
        cursor = fim_fatia + timedelta(days=1)
    return fatias


def lista_da_resposta(dados: dict) -> list:
    resposta = dados.get("response") or []
    if isinstance(resposta, dict):
        resposta = next((v for v in resposta.values() if isinstance(v, list)), [])
    return [r for r in resposta if isinstance(r, dict)]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Falta o campaign_id a testar.\n"
                 "  python extraction/shopee/sonda_id_direto.py 117615261")

    try:
        id_teste = int(sys.argv[1])
    except ValueError:
        sys.exit(f"'{sys.argv[1]}' nao e um campaign_id. Esperado so numero.")

    if id_teste == ID_CONTROLE:
        sys.exit(f"{id_teste} e o proprio controle. Passe o id da campanha nova.")

    fim = datetime.now().date() - timedelta(days=1)
    inicio = date(2026, 10, 1)
    ids = [ID_CONTROLE, id_teste]
    fatias = fatiar(inicio, fim)

    print(f"Sonda de id direto — {inicio} a {fim} "
          f"({(fim - inicio).days + 1} dias, {len(fatias)} fatia(s))")
    print(f"  controle: {ID_CONTROLE}   teste: {id_teste}\n")

    path = "/api/v2/ads/get_product_campaign_daily_performance"
    gastos, dias, nomes, tipos = {}, {}, {}, {}
    houve_erro = False

    for a, b in fatias:
        print(f"[fatia {a} a {b}]")
        dados = chamar(path, {
            "start_date": a.strftime(FMT_ADS),
            "end_date": b.strftime(FMT_ADS),
            "campaign_id_list": ",".join(str(i) for i in ids),
        })

        if dados.get("error"):
            houve_erro = True
            print(f"  {dados['error']}: {dados.get('message', '')}")
            time.sleep(PAUSA_SEG)
            continue

        campanhas = lista_da_resposta(dados)
        if not campanhas:
            print("  resposta sem nenhuma campanha (o vazio silencioso).")

        for camp in campanhas:
            cid = camp.get("campaign_id")
            metricas = camp.get("metrics_list") or []
            gastos[cid] = gastos.get(cid, 0.0) + sum(
                float(m.get("expense") or 0) for m in metricas)
            dias[cid] = dias.get(cid, 0) + len(metricas)
            nomes[cid] = camp.get("ad_name")
            tipos[cid] = camp.get("ad_type")
            print(f"  devolveu {cid}  ({len(metricas)} dia(s))")

        time.sleep(PAUSA_SEG)

    print("\n--- consolidado ---")
    for cid in ids:
        marca = "CONTROLE" if cid == ID_CONTROLE else "TESTE   "
        if cid in gastos:
            print(f"  {marca} {cid}  R$ {gastos[cid]:>8.2f} em {dias[cid]} dia(s)")
            print(f"           ad_type={tipos[cid]}  ad_name={nomes[cid]}")
        else:
            print(f"  {marca} {cid}  NAO VEIO NA RESPOSTA")

    tem_controle = ID_CONTROLE in gastos
    tem_teste = id_teste in gastos

    print()
    if tem_controle and tem_teste:
        print("  >>> O ID E SERVIDO pela performance. O conserto e uma seed de")
        print("      ids avulsos no get_campaign_ids(). As colunas de")
        print("      configuracao (item_id, status, orcamento, meta_roas) vao")
        print("      ficar NULAS, porque o setting recusa o id por tipo -- e")
        print("      isso e aceitavel: o left join existe para nao perder gasto.")
    elif tem_controle and not tem_teste:
        print("  >>> O ID NAO E SERVIDO. Prova limpa: mesma chamada, mesma")
        print("      janela, mesma autenticacao, e so o controle voltou.")
        print("      A familia Product Ads esta fechada para esta campanha.")
        print("      Caminho: modulo GMS (get_gms_campaign_performance).")
    elif not tem_controle and houve_erro:
        print("  >>> INCONCLUSIVO: houve erro de API e nem o controle voltou.")
        print("      Nada se conclui sobre o id de teste.")
    else:
        print("  >>> INCONCLUSIVO: nem o controle voltou, sem erro aparente.")

    print("\nFim. Me manda a saida inteira.")
