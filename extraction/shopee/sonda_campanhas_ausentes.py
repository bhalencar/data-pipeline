"""
Sonda: por que a campanha "Lancamentos 1" nao aparece na nossa extracao?

CONTEXTO. Em 03/11/2026 o Bruno mostrou a tela do Seller Centre com DUAS
campanhas rodando em outubro, ambas marcadas "Anuncio de Produto - GMV Max":

  Comedouro Duplo Elevado MDF ... [4]   R$ 62,83
  Lancamentos 1                         R$  8,49

A primeira esta no nosso `master_ads` (campaign_id 116939634) com exatamente
R$ 62,84. A segunda NAO esta em lugar nenhum. E a diferenca entre o nivel loja
e a soma das campanhas, medida no BigQuery, bate com ela ao centavo:

  out/26       loja 71,33   campanhas 62,84   diferenca 8,49
  nov/26 1-2   loja 38,80   campanhas 26,31   diferenca 12,49

A divergencia comeca em 30/10/2026 e e ZERO em todos os meses anteriores.

O QUE ESTA SONDA RESPONDE. O `get_ads.py` monta a lista de campanhas com
`get_product_level_campaign_id_list` usando `ad_type="all"`. A hipotese e que
"all" nao cobre campanha GMV Max criada nativamente -- a campanha 116939634
provavelmente e uma campanha manual antiga que a Shopee MIGROU para GMV Max na
interface, e por isso continua saindo na listagem com `ad_type` = "manual".

A sonda NAO assume isso. Ela varre os valores candidatos de `ad_type`, reporta
quais a API aceita e quais ids cada um devolve, e diz em qual deles (se algum)
a campanha que falta aparece.

NAO ESCREVE NADA. Nenhum arquivo no bronze, nenhuma tabela. So le e imprime.

Uso:
    cd ~/Documents/"Casa e Patas"/data-pipeline
    source ~/.venvs/cp-bigquery/bin/activate
    python extraction/shopee/sonda_campanhas_ausentes.py

Opcional, para conferir um periodo diferente do padrao (out + nov):
    python extraction/shopee/sonda_campanhas_ausentes.py 2026-10-01 2026-11-02
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
PAUSA_SEG = 1.0

# Valores candidatos de ad_type. "all" e o que o get_ads.py usa hoje. Os
# demais sao chutes informados -- a API devolve erro de parametro no que nao
# existir, e e exatamente essa a informacao que queremos.
AD_TYPES = ["all", "auto", "manual", "gmv_max", "gmvmax", "gms", "product_gmv_max"]

# Endpoints de listagem candidatos. O primeiro e o que ja usamos.
ENDPOINTS_LISTA = [
    "/api/v2/ads/get_product_level_campaign_id_list",
    "/api/v2/ads/get_gms_campaign_id_list",
]


def generate_sign(path: str, ts: int, token: str, shop: int) -> str:
    base = f"{PARTNER_ID}{path}{ts}{token}{shop}"
    return hmac.new(PARTNER_KEY.encode("utf-8"), base.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def chamar(path: str, extra: dict) -> dict:
    """
    Chamada autenticada que DEVOLVE o erro em vez de levantar.

    Diferente do `chamar()` do get_ads.py de proposito: aqui o erro e o
    resultado que interessa. "ad_type invalido" e uma resposta, nao uma falha.
    """
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
        resposta = requests.get(f"{API_HOST}{path}", params=params, timeout=45)
        return resposta.json()
    except Exception as e:                      # noqa: BLE001
        return {"error": "falha_local", "message": str(e)}


def listar(path: str, ad_type: str) -> tuple:
    """Devolve (lista_de_campanhas, erro_ou_None)."""
    campanhas, offset = [], 0

    while True:
        dados = chamar(path, {"ad_type": ad_type, "offset": offset, "limit": 100})

        if dados.get("error"):
            return campanhas, f"{dados['error']} {dados.get('message', '')}".strip()

        resposta = dados.get("response") or {}
        if isinstance(resposta, list):
            lote, tem_proxima = resposta, False
        else:
            lote = resposta.get("campaign_list") or []
            tem_proxima = bool(resposta.get("has_next_page"))

        campanhas += [c for c in lote if isinstance(c, dict)]

        if not tem_proxima or not lote:
            return campanhas, None

        offset += len(lote)
        time.sleep(PAUSA_SEG)


def gasto_por_campanha(ids: list, inicio: date, fim: date) -> dict:
    """Soma o gasto de cada campanha no periodo. Fatia de 30 dias, como o get_ads."""
    path = "/api/v2/ads/get_product_campaign_daily_performance"
    totais = {}

    fatias, cursor = [], inicio
    while cursor <= fim:
        fim_fatia = min(cursor + timedelta(days=29), fim)
        fatias.append((cursor, fim_fatia))
        cursor = fim_fatia + timedelta(days=1)

    for i in range(0, len(ids), 10):
        lote = ids[i:i + 10]
        for a, b in fatias:
            dados = chamar(path, {
                "start_date": a.strftime(FMT_ADS),
                "end_date": b.strftime(FMT_ADS),
                "campaign_id_list": ",".join(str(x) for x in lote),
            })
            if dados.get("error"):
                print(f"    erro na performance de {lote}: {dados['error']}")
                continue

            resposta = dados.get("response") or []
            if isinstance(resposta, dict):
                resposta = next((v for v in resposta.values()
                                 if isinstance(v, list)), [])

            for camp in resposta:
                if not isinstance(camp, dict):
                    continue
                cid = camp.get("campaign_id")
                nome = camp.get("ad_name")
                soma = sum(float(m.get("expense") or 0)
                           for m in camp.get("metrics_list") or [])
                atual = totais.get(cid, {"nome": nome, "gasto": 0.0,
                                         "ad_type": camp.get("ad_type")})
                atual["gasto"] += soma
                totais[cid] = atual

            time.sleep(PAUSA_SEG)

    return totais


def gasto_da_loja(inicio: date, fim: date) -> float:
    path = "/api/v2/ads/get_all_cpc_ads_daily_performance"
    total = 0.0

    cursor = inicio
    while cursor <= fim:
        fim_fatia = min(cursor + timedelta(days=29), fim)
        dados = chamar(path, {"start_date": cursor.strftime(FMT_ADS),
                              "end_date": fim_fatia.strftime(FMT_ADS)})
        if dados.get("error"):
            print(f"    erro no nivel loja: {dados['error']}")
        else:
            resposta = dados.get("response") or []
            if isinstance(resposta, dict):
                resposta = next((v for v in resposta.values()
                                 if isinstance(v, list)), [])
            total += sum(float(d.get("expense") or 0) for d in resposta)

        cursor = fim_fatia + timedelta(days=1)
        time.sleep(PAUSA_SEG)

    return round(total, 2)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        inicio = date.fromisoformat(sys.argv[1])
        fim = date.fromisoformat(sys.argv[2])
    else:
        inicio = date(2026, 10, 1)
        fim = datetime.now().date() - timedelta(days=1)

    print(f"Sonda de campanhas ausentes — periodo {inicio} a {fim}\n")

    # -------------------------------------------------- 1. varredura de ad_type
    print("[1/3] Quais valores de ad_type a listagem aceita, e o que devolvem")

    vistos = {}      # campaign_id -> {nome, de_onde}

    for path in ENDPOINTS_LISTA:
        curto = path.rsplit("/", 1)[-1]
        for tipo in AD_TYPES:
            campanhas, erro = listar(path, tipo)
            if erro:
                print(f"  {curto} ad_type={tipo:<16} -> ERRO: {erro}")
            else:
                print(f"  {curto} ad_type={tipo:<16} -> {len(campanhas)} campanha(s)")
                for c in campanhas:
                    cid = c.get("campaign_id")
                    if cid is None:
                        continue
                    vistos.setdefault(cid, {"nome": c.get("ad_name"),
                                            "de_onde": set()})
                    vistos[cid]["de_onde"].add(f"{curto}:{tipo}")
            time.sleep(PAUSA_SEG)

    print(f"\n  Total de campanhas distintas encontradas: {len(vistos)}")
    print("  (o get_ads.py de hoje enxerga so as de "
          "get_product_level_campaign_id_list:all)\n")

    base = {cid for cid, v in vistos.items()
            if any(d.endswith(":all") and d.startswith("get_product_level")
                   for d in v["de_onde"])}
    extras = set(vistos) - base

    if extras:
        print("  CAMPANHAS QUE A EXTRACAO DE HOJE NAO PEGA:")
        for cid in sorted(extras):
            v = vistos[cid]
            print(f"    {cid}  {v['nome']}")
            print(f"       aparece em: {', '.join(sorted(v['de_onde']))}")
    else:
        print("  Nenhuma campanha extra. Se 'Lancamentos 1' nao estiver na lista")
        print("  acima, ela nao sai por NENHUM ad_type -- e o caminho passa a ser")
        print("  o modulo GMS (get_gms_campaign_performance).")

    # ------------------------------------------- 2. gasto por campanha no periodo
    print("\n[2/3] Gasto por campanha no periodo")
    totais = gasto_por_campanha(sorted(vistos), inicio, fim)

    soma_campanhas = 0.0
    for cid, v in sorted(totais.items(), key=lambda kv: -kv[1]["gasto"]):
        if v["gasto"] <= 0:
            continue
        soma_campanhas += v["gasto"]
        print(f"  {cid}  R$ {v['gasto']:>8.2f}  "
              f"ad_type={v['ad_type']}  {v['nome']}")

    soma_campanhas = round(soma_campanhas, 2)

    # ------------------------------------------------------- 3. conciliacao
    print("\n[3/3] Conciliacao")
    loja = gasto_da_loja(inicio, fim)
    print(f"  Nivel loja .......... R$ {loja:.2f}")
    print(f"  Soma das campanhas .. R$ {soma_campanhas:.2f}")
    print(f"  Diferenca ........... R$ {loja - soma_campanhas:.2f}")
    print("\n  Diferenca de centavos = arredondamento por linha, normal.")
    print("  Diferenca de reais    = ainda existe campanha que nao estamos vendo.")
