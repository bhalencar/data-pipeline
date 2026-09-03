"""
Exploracao da API de Ads — rodada 3, a ultima. Card #1 (master_ads).

NAO escreve nada. So le, imprime e resume.

JA RESPONDIDO NAS RODADAS 1 E 2 -- nao repetir:

  - Janela maxima: 30 dias inclusivos.
  - Uma linha por dia, inclusive dia sem campanha (a Shopee ja preenche zero).
  - Gabarito bate nos quatro meses, com <= 2 centavos de diferenca no mes.
  - 16 campos no endpoint de LOJA, ja mapeados.
  - 24 campanhas na loja, todas ad_type='manual'.
    Endpoint: get_product_level_campaign_id_list (ad_type, offset, limit).

DUAS PENDENCIAS, E AS DUAS SAO ERRO MEU NA RODADA 2:

  P8. O total por campanha bate com o total da loja?
      A rodada 2 respondeu "0.00" e isso e BUG MEU, nao ausencia de gasto:
      o endpoint de campanha devolve ANINHADO --

          {campaign_id, ad_type, ad_name, campaign_placement,
           metrics_list: [{date, impression, clicks, expense, ...}, ...]}

      e o meu somar() procurou 'expense' no nivel de cima, onde ele nao existe.
      Somou zero e eu quase concluí que campanha nao tem gasto. Aqui vai
      somando de dentro do metrics_list, que e onde o dado esta.

      Isso importa porque decide a FONTE DE VERDADE do gasto no DRE: se os
      dois totais baterem, o endpoint de loja basta e o modelo fica simples;
      se divergirem, e preciso decidir qual vale e registrar o motivo.

  P6. Cardinalidade campanha -> item, que decide se SKU vira coluna ou tabela
      ponte. O setting_info exige info_type_list, que eu nao mandei.

Como rodar:
    cd ~/Documents/"Casa e Patas"/data-pipeline
    source venv/bin/activate
    export TOKEN_BUCKET=cp-pipeline-tokens
    python3.12 extraction/shopee/explore_ads_api3.py
"""

import hashlib
import hmac
import json
import os
import time
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

FMT = "%d-%m-%Y"
MAX_DIAS_ADS = 30

# Julho: mes de maior gasto (839.18) e o unico com zero dias sem campanha.
# E o melhor periodo possivel para comparar loja contra campanha.
JULHO_A = date(2026, 7, 1)
JULHO_B = date(2026, 7, 31)


def generate_sign(path: str, ts: int, token: str, shop: int) -> str:
    base = f"{PARTNER_ID}{path}{ts}{token}{shop}"
    return hmac.new(PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()


def chamar(path: str, extra: dict) -> dict:
    token, shop = get_valid_access_token()
    ts = int(time.time())
    params = {"partner_id": PARTNER_ID, "timestamp": ts,
              "sign": generate_sign(path, ts, token, shop),
              "access_token": token, "shop_id": shop, **extra}
    try:
        r = requests.get(f"{API_HOST}{path}", params=params, timeout=45)
    except requests.RequestException as e:
        return {"erro_rede": str(e)}
    try:
        return {"status_http": r.status_code, **r.json()}
    except ValueError:
        return {"status_http": r.status_code, "corpo_bruto": r.text[:500]}


def secao(t: str) -> None:
    print(f"\n\n{'=' * 72}\n{t}\n{'=' * 72}")


def tem_erro(r: dict) -> bool:
    return str(r.get("error", "")) not in ("", "0") or "erro_rede" in r


def msg_erro(r: dict) -> str:
    return f"{r.get('error') or r.get('erro_rede', '?')} {r.get('message', '')}".strip()


def extrair_lista(r: dict) -> list:
    resp = r.get("response")
    if isinstance(resp, list):
        return resp
    if not isinstance(resp, dict) or not resp:
        return []
    for v in resp.values():
        if isinstance(v, list):
            return v
    return [resp]


def fatiar(a: date, b: date, max_dias: int = MAX_DIAS_ADS) -> list:
    out, cur = [], a
    while cur <= b:
        f = min(cur + timedelta(days=max_dias - 1), b)
        out.append((cur, f))
        cur = f + timedelta(days=1)
    return out


def descrever_campos(reg, ind: str = "      ") -> None:
    if not isinstance(reg, dict):
        print(f"{ind}(nao e objeto) {type(reg).__name__}: {json.dumps(reg, ensure_ascii=False)[:80]}")
        return
    for k, v in reg.items():
        a = json.dumps(v, ensure_ascii=False)
        if len(a) > 55:
            a = a[:55] + "..."
        print(f"{ind}{k:<30} {type(v).__name__:<7} {a}")


# ---------------------------------------------------------------------------
# P8 — loja contra campanha, somando de dentro do metrics_list
# ---------------------------------------------------------------------------
def comparar_loja_e_campanha() -> dict:
    secao("P8 — total da LOJA x soma das CAMPANHAS (julho, o mes mais movimentado)")
    achados = {}

    # --- lado A: total da loja
    print("\n[a] Total da loja em julho")
    dias_loja = []
    for a, b in fatiar(JULHO_A, JULHO_B):
        r = chamar("/api/v2/ads/get_all_cpc_ads_daily_performance",
                   {"start_date": a.strftime(FMT), "end_date": b.strftime(FMT)})
        if tem_erro(r):
            print(f"    fatia {a}..{b}: ERRO -- {msg_erro(r)}")
            continue
        dias_loja.extend(extrair_lista(r))
        time.sleep(1)

    total_loja = round(sum(float(d.get("expense") or 0) for d in dias_loja), 2)
    gmv_loja = round(sum(float(d.get("direct_gmv") or 0) for d in dias_loja), 2)
    print(f"    {len(dias_loja)} dia(s) | expense = {total_loja:.2f} | direct_gmv = {gmv_loja:.2f}")
    achados["loja_expense_julho"] = total_loja
    achados["loja_direct_gmv_julho"] = gmv_loja

    # --- lado B: todas as 24 campanhas
    print("\n[b] Listando TODAS as campanhas (nao so as 10 primeiras)")
    r = chamar("/api/v2/ads/get_product_level_campaign_id_list",
               {"ad_type": "all", "offset": 0, "limit": 100})
    if tem_erro(r):
        print(f"    ERRO -- {msg_erro(r)}")
        return achados

    campanhas = extrair_lista(r)
    ids = [c["campaign_id"] for c in campanhas
           if isinstance(c, dict) and "campaign_id" in c]
    print(f"    {len(ids)} campanha(s): {ids}")
    achados["n_campanhas"] = len(ids)

    print("\n[c] Performance por campanha, somando DE DENTRO do metrics_list")
    print("    (o bug da rodada 2 foi somar no nivel de cima, onde expense nao existe)")

    total_campanhas = 0.0
    linhas_grao = 0
    por_campanha = {}
    campos_metrica = None

    # 10 ids por chamada, para nao esbarrar no limite de tamanho de parametro
    for i in range(0, len(ids), 10):
        lote = ids[i:i + 10]
        for a, b in fatiar(JULHO_A, JULHO_B):
            r = chamar("/api/v2/ads/get_product_campaign_daily_performance",
                       {"start_date": a.strftime(FMT), "end_date": b.strftime(FMT),
                        "campaign_id_list": ",".join(str(x) for x in lote)})
            if tem_erro(r):
                print(f"    lote {i//10 + 1}, fatia {a}..{b}: ERRO -- {msg_erro(r)}")
                continue

            for camp in extrair_lista(r):
                if not isinstance(camp, dict):
                    continue
                cid = camp.get("campaign_id")
                nome = camp.get("ad_name", "")
                metricas = camp.get("metrics_list") or []

                if campos_metrica is None and metricas:
                    campos_metrica = sorted(metricas[0].keys())
                    print("\n    >>> CAMPOS DENTRO DE metrics_list -- o grao real:")
                    descrever_campos(metricas[0])
                    print()

                soma = round(sum(float(m.get("expense") or 0) for m in metricas), 2)
                linhas_grao += len(metricas)
                total_campanhas += soma
                if soma > 0:
                    por_campanha[cid] = (nome[:45], soma)
            time.sleep(1)

    total_campanhas = round(total_campanhas, 2)
    achados["campanha_expense_julho"] = total_campanhas
    achados["linhas_campanha_x_dia"] = linhas_grao
    achados["campos_metrics_list"] = campos_metrica

    print(f"\n    Linhas campanha x dia: {linhas_grao}")
    print(f"    Campanhas com gasto > 0: {len(por_campanha)} de {len(ids)}")
    for cid, (nome, soma) in sorted(por_campanha.items(), key=lambda x: -x[1][1]):
        print(f"      {cid}  R$ {soma:>8.2f}  {nome}")

    # --- o veredito
    delta = round(total_campanhas - total_loja, 2)
    print(f"\n    {'-' * 60}")
    print(f"    LOJA      : {total_loja:>9.2f}")
    print(f"    CAMPANHAS : {total_campanhas:>9.2f}")
    print(f"    DELTA     : {delta:>+9.2f}")
    achados["delta_loja_campanha"] = delta

    if abs(delta) < 0.05:
        print("\n    >>> BATEM. O endpoint de loja e suficiente para o DRE, e o de")
        print("        campanha serve para atribuir por campanha sem risco de")
        print("        divergir do total. Modelo simples.")
        achados["veredito_p8"] = "batem"
    elif total_campanhas < total_loja:
        print(f"\n    >>> CAMPANHA MENOR em {abs(delta):.2f}. Provavel: gasto que nao")
        print("        pertence a nenhuma campanha viva (campanha apagada, ou tipo")
        print("        de anuncio fora do product-level). A LOJA e a fonte de")
        print("        verdade do DRE; campanha serve so para atribuicao relativa.")
        achados["veredito_p8"] = "campanha_menor"
    else:
        print(f"\n    >>> CAMPANHA MAIOR em {abs(delta):.2f}. Suspeitar de dupla")
        print("        contagem entre campanhas -- mesmo defeito do broad_gmv.")
        achados["veredito_p8"] = "campanha_maior"

    return achados


# ---------------------------------------------------------------------------
# P6 — cardinalidade campanha -> item
# ---------------------------------------------------------------------------
def explorar_cardinalidade() -> dict:
    secao("P6 — campanha -> item (decide coluna vs tabela ponte)")
    achados = {}

    r = chamar("/api/v2/ads/get_product_level_campaign_id_list",
               {"ad_type": "all", "offset": 0, "limit": 100})
    ids = [c["campaign_id"] for c in extrair_lista(r)
           if isinstance(c, dict) and "campaign_id" in c]
    if not ids:
        print("    Sem campanhas para consultar.")
        return achados

    # O erro da rodada 2 foi omitir info_type_list. A doc nao diz os valores
    # aceitos, entao testamos os plausiveis ate um responder.
    print("\n[a] setting_info exige info_type_list. Testando valores:")
    settings = []
    for tipo in ("1,2,3", "1", "2", "3", "all", "common,item,budget"):
        r2 = chamar("/api/v2/ads/get_product_level_campaign_setting_info",
                    {"campaign_id_list": ",".join(str(i) for i in ids[:10]),
                     "info_type_list": tipo})
        if tem_erro(r2):
            print(f"    info_type_list={tipo:<18} -> {msg_erro(r2)[:70]}")
        else:
            print(f"    info_type_list={tipo:<18} -> OK")
            settings = extrair_lista(r2)
            achados["info_type_list_valido"] = tipo
            print(f"\n    RESPOSTA CRUA (primeira campanha):")
            print(json.dumps(settings[0] if settings else {}, indent=2, ensure_ascii=False)[:1500])
            break
        time.sleep(1)

    if not settings:
        print("\n    Nenhum valor aceito. A ligacao campanha->SKU fica pendente.")
        print("    NAO e bloqueio: o grao campanha x dia ja atende o Inacio, e o")
        print("    ad_name identifica o produto por texto. Registrar como lacuna.")
        achados["cardinalidade"] = "nao_resolvida"
        return achados

    print("\n[b] Cardinalidade:")
    multi = 0
    for s in settings:
        if not isinstance(s, dict):
            continue
        itens = s.get("item_id_list") or s.get("item_list") or []
        n = len(itens) if isinstance(itens, list) else 0
        if n > 1:
            multi += 1
        print(f"      campanha {s.get('campaign_id','?')}: {n} item(ns) {str(itens)[:50]}")

    print(f"\n    >>> {multi} de {len(settings)} campanha(s) com mais de um item.")
    if multi:
        print("        Confirma o grao campanha x dia: gasto por SKU exigiria")
        print("        rateio arbitrario, numero que parece exato e nao e.")
    achados["campanhas_multi_item"] = multi
    return achados


if __name__ == "__main__":
    print(f"Partner ID: {PARTNER_ID}")
    print(f"Rodado em: {datetime.now():%d/%m/%Y %H:%M}")
    print("Rodada 3 -- fecha P8 (fonte de verdade do gasto) e P6 (campanha->SKU).")
    print("Faz varias chamadas com pausa de 1s. Deve levar 1 a 2 minutos.")

    resumo = {}
    try:
        resumo.update(comparar_loja_e_campanha())
        resumo.update(explorar_cardinalidade())
    except Exception as e:
        print(f"\n\n!!! Interrompido: {type(e).__name__}: {e}")
        print("    Mande a saida ate aqui mesmo assim.")

    secao("RESUMO")
    print(json.dumps(resumo, indent=2, ensure_ascii=False, default=str))
    print(
        "\nO que decide o desenho:\n"
        "  1. O delta loja x campanha. Zero = modelo simples.\n"
        "  2. Campanha com mais de um item: confirma o grao campanha x dia.\n"
    )
