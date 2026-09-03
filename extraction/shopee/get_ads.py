"""
Extracao de performance de anuncios da Shopee (Ads), camada bronze.

O que sai daqui, e por que sao dois arquivos:

  get_ads_shop_daily     — uma linha por DIA, nivel loja. E a FONTE DE VERDADE
                           do gasto no DRE.
  get_ads_campaign_daily — uma linha por CAMPANHA x DIA. Serve para atribuir
                           gasto por campanha e por produto.

Medido em 02/09/2026 (julho inteiro): loja 839.17 x campanhas 839.20. Tres
centavos sobre 744 linhas. Os dois totais batem, entao a divisao acima e
seguranca contra dupla contagem, nao reconciliacao.

FATOS DA API, todos medidos, nenhum suposto:

  - Janela maxima de 30 dias INCLUSIVOS por chamada. 31 dias devolve
    `ads.performance.error_date_range_too_long`. Por isso o fatiamento.
  - Datas em DD-MM-YYYY, diferente do resto do projeto, que usa timestamp unix.
    Errar o formato devolve vazio em vez de erro -- falha silenciosa.
  - A API devolve UMA LINHA POR DIA mesmo em dia sem campanha ativa: agosto/2026
    teve 27 de 31 dias com gasto zero e ainda assim vieram as 31 linhas. Por
    isso a extracao NAO preenche dia faltante: ausencia de linha aqui significa
    falha de extracao, e e essa propriedade que deixa o alerta de frescor
    funcionar.
  - `campaign_id_list` e obrigatorio nos endpoints de campanha. A lista sai de
    `get_product_level_campaign_id_list`, que o card #1 nao previa.
  - A performance por campanha vem ANINHADA em `metrics_list`. O gasto NAO esta
    no nivel de cima -- ler ali devolve zero em silencio.

Uso:
    python extraction/shopee/get_ads.py                      # janela padrao
    python extraction/shopee/get_ads.py 2026-03-01 2026-08-31  # backfill

Sem argumentos, refaz os ultimos SHOPEE_ADS_WINDOW_DAYS dias (padrao 30).
A releitura existe pelo mesmo motivo da de pedidos: a Shopee ajusta metrica
de atribuicao depois do fato, porque `broad_*` credita conversao numa janela
de 7 dias a partir do clique.
"""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

FMT_ADS = "%d-%m-%Y"
MAX_DIAS_ADS = 30          # medido: 31 dias falha
CAMPANHAS_POR_CHAMADA = 10 # o card #1 fala em 100; 10 mantem a URL curta
PAUSA_SEG = 1.0            # ads tem rate limit proprio: ads.rate_limit.exceed_api

WINDOW_DAYS = int(os.getenv("SHOPEE_ADS_WINDOW_DAYS", "30"))

BRONZE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "bronze",
)


def generate_sign(path: str, ts: int, token: str, shop: int) -> str:
    base = f"{PARTNER_ID}{path}{ts}{token}{shop}"
    return hmac.new(PARTNER_KEY.encode("utf-8"), base.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def chamar(path: str, extra: dict) -> dict:
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
    resposta = requests.get(f"{API_HOST}{path}", params=params, timeout=45)
    dados = resposta.json()
    if dados.get("error"):
        raise RuntimeError(
            f"Erro da API em {path}: {dados.get('error')} {dados.get('message', '')}"
        )
    return dados


def fatiar(inicio: date, fim: date, max_dias: int = MAX_DIAS_ADS) -> list:
    """Quebra [inicio, fim] em fatias de no maximo max_dias INCLUSIVOS."""
    fatias, cursor = [], inicio
    while cursor <= fim:
        fim_fatia = min(cursor + timedelta(days=max_dias - 1), fim)
        fatias.append((cursor, fim_fatia))
        cursor = fim_fatia + timedelta(days=1)
    return fatias


def data_ads_para_iso(valor: str) -> str:
    """DD-MM-YYYY -> YYYY-MM-DD. Sem isso o silver compara data como texto."""
    return datetime.strptime(valor, FMT_ADS).date().isoformat()


# ---------------------------------------------------------------------------
# Nivel loja
# ---------------------------------------------------------------------------
def get_shop_daily(inicio: date, fim: date) -> list:
    path = "/api/v2/ads/get_all_cpc_ads_daily_performance"
    todos = []

    for a, b in fatiar(inicio, fim):
        dados = chamar(path, {"start_date": a.strftime(FMT_ADS),
                              "end_date": b.strftime(FMT_ADS)})
        resposta = dados.get("response") or []
        if isinstance(resposta, dict):
            resposta = next((v for v in resposta.values() if isinstance(v, list)), [])

        for reg in resposta:
            reg["date_iso"] = data_ads_para_iso(reg["date"])
            todos.append(reg)

        print(f"  loja {a} a {b} ({(b - a).days + 1}d): {len(resposta)} dia(s).")
        time.sleep(PAUSA_SEG)

    return todos


# ---------------------------------------------------------------------------
# Nivel campanha
# ---------------------------------------------------------------------------
def get_campaign_ids() -> list:
    """
    Lista as campanhas da loja. Passo que o card #1 nao previa: os dois
    endpoints de campanha exigem campaign_id_list e nenhum deles o produz.
    """
    path = "/api/v2/ads/get_product_level_campaign_id_list"
    ids, offset = [], 0

    while True:
        dados = chamar(path, {"ad_type": "all", "offset": offset, "limit": 100})
        resposta = dados.get("response") or {}
        lote = resposta.get("campaign_list") or []
        ids += [c["campaign_id"] for c in lote if isinstance(c, dict) and "campaign_id" in c]

        if not resposta.get("has_next_page") or not lote:
            break
        offset += len(lote)
        time.sleep(PAUSA_SEG)

    return ids


def get_campaign_daily(ids: list, inicio: date, fim: date) -> list:
    """
    Performance por campanha x dia.

    A resposta vem aninhada -- {campaign_id, ad_name, metrics_list: [{date,
    expense, ...}]} -- e o achatamento aqui e o ponto do metodo. Ler `expense`
    no nivel de cima devolve zero sem erro nenhum; foi o que aconteceu comigo
    na exploracao de 02/09.
    """
    path = "/api/v2/ads/get_product_campaign_daily_performance"
    linhas = []

    for i in range(0, len(ids), CAMPANHAS_POR_CHAMADA):
        lote = ids[i:i + CAMPANHAS_POR_CHAMADA]
        for a, b in fatiar(inicio, fim):
            dados = chamar(path, {
                "start_date": a.strftime(FMT_ADS),
                "end_date": b.strftime(FMT_ADS),
                "campaign_id_list": ",".join(str(x) for x in lote),
            })
            resposta = dados.get("response") or []
            if isinstance(resposta, dict):
                resposta = next((v for v in resposta.values() if isinstance(v, list)), [])

            for camp in resposta:
                if not isinstance(camp, dict):
                    continue
                for metrica in camp.get("metrics_list") or []:
                    linha = dict(metrica)
                    linha["campaign_id"] = camp.get("campaign_id")
                    linha["ad_type"] = camp.get("ad_type")
                    linha["ad_name"] = camp.get("ad_name")
                    linha["campaign_placement"] = camp.get("campaign_placement")
                    linha["date_iso"] = data_ads_para_iso(metrica["date"])
                    linhas.append(linha)

            print(f"  campanhas {i + 1}-{i + len(lote)}, {a} a {b}: "
                  f"{len(resposta)} campanha(s).")
            time.sleep(PAUSA_SEG)

    return linhas


def get_campaign_settings(ids: list) -> list:
    """
    Configuracao de cada campanha, incluindo item_id_list -- a ligacao com SKU.

    info_type_list=1,2,3 e o valor aceito; sem ele a API devolve
    'InfoTypeList is required'. O item_id_list vem DENTRO de common_info.
    """
    path = "/api/v2/ads/get_product_level_campaign_setting_info"
    settings = []

    for i in range(0, len(ids), CAMPANHAS_POR_CHAMADA):
        lote = ids[i:i + CAMPANHAS_POR_CHAMADA]
        dados = chamar(path, {
            "campaign_id_list": ",".join(str(x) for x in lote),
            "info_type_list": "1,2,3",
        })
        resposta = dados.get("response") or []
        if isinstance(resposta, dict):
            resposta = next((v for v in resposta.values() if isinstance(v, list)), [])
        settings.extend(r for r in resposta if isinstance(r, dict))
        print(f"  settings {i + 1}-{i + len(lote)}: {len(resposta)} campanha(s).")
        time.sleep(PAUSA_SEG)

    return settings


def salvar(nome_tabela: str, conteudo: list, referencia: date) -> None:
    pasta = os.path.join(BRONZE_DIR, nome_tabela)
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"{referencia}.json")
    with open(caminho, "w") as f:
        json.dump(conteudo, f, indent=2, ensure_ascii=False)
    print(f"  -> {caminho} ({len(conteudo)} registro(s))")


if __name__ == "__main__":
    tz = timezone(timedelta(hours=-3))
    hoje = datetime.now(tz).date()

    if len(sys.argv) == 3:
        inicio = date.fromisoformat(sys.argv[1])
        fim = date.fromisoformat(sys.argv[2])
        modo = "backfill"
    else:
        # Ontem como limite: o dia de hoje ainda esta aberto e a metrica muda.
        fim = hoje - timedelta(days=1)
        inicio = fim - timedelta(days=WINDOW_DAYS - 1)
        modo = f"janela de {WINDOW_DAYS} dias"

    if inicio > fim:
        sys.exit(f"Periodo invalido: {inicio} depois de {fim}.")

    print(f"Extracao de Ads — {modo}: {inicio} a {fim} "
          f"({(fim - inicio).days + 1} dias, fuso de Brasilia).")

    print("\n[1/3] Performance da loja (fonte de verdade do gasto)")
    shop = get_shop_daily(inicio, fim)
    salvar("get_ads_shop_daily", shop, fim)

    print("\n[2/3] Campanhas")
    ids = get_campaign_ids()
    print(f"  {len(ids)} campanha(s) na loja.")

    if ids:
        campanhas = get_campaign_daily(ids, inicio, fim)
        salvar("get_ads_campaign_daily", campanhas, fim)

        settings = get_campaign_settings(ids)
        salvar("get_ads_campaign_setting", settings, fim)
    else:
        print("  Nenhuma campanha. Nada a salvar nos dois arquivos de campanha.")

    print("\n[3/3] Conferencia")
    total_loja = round(sum(float(d.get("expense") or 0) for d in shop), 2)
    print(f"  Gasto no periodo (nivel loja): R$ {total_loja:.2f}")
    print(f"  Dias com gasto zero: {sum(1 for d in shop if not d.get('expense'))} de {len(shop)}")
    print("\n  Dia zerado e normal com a midia pausada -- a Shopee devolve a linha "
          "mesmo assim.\n  Dia AUSENTE, nao. Se o total de dias for menor que o "
          "periodo pedido, houve falha de extracao.")
