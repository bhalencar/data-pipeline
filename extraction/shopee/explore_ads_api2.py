"""
Exploracao da API de Ads — rodada 2. Card #1 (master_ads).

NAO escreve nada, em lugar nenhum. So le, imprime e resume.

O QUE A RODADA 1 JA RESPONDEU (nao repetir):

  - Limite de intervalo: 30 dias inclusivos. Janela de 31 dias devolve
    `ads.performance.error_date_range_too_long`.
  - Backfill funciona: junho voltou 271.21 contra 271.20 informado pelo Bruno.
    Um centavo, arredondamento.
  - A API devolve UMA LINHA POR DIA, inclusive em dia sem campanha ativa:
    pedimos 7 dias de diferenca e vieram 8 registros; 15 e vieram 16. Como a
    midia esta pausada desde agosto, esses dias de setembro nao tem campanha e
    ainda assim vieram. Ou seja: a extracao NAO precisa preencher zero, a
    Shopee ja preenche. Ausencia de linha vai significar falha de extracao.
  - Os dois endpoints de campanha exigem `campaign_id_list`.

ERRO MEU NA RODADA 1: montei o gabarito com 01-03 a 31-03, 31 dias. Marco,
julho e agosto falharam por causa disso, nao porque o backfill nao funcione.
Junho passou por acidente de calendario -- tem 30 dias. Aqui vai corrigido.

O QUE FALTA, E E O QUE ESTE SCRIPT BUSCA:

  P4. Quais campos vem de fato, com nome e tipo? Nao vi NENHUM na rodada 1,
      porque o bloco que imprimia os campos estava dentro do teste de julho,
      que falhou. Sem isso nao da para escrever o schema.

  P5. De onde sai o campaign_id_list? A resposta esta em
      `get_product_level_campaign_id_list` (ad_type, offset, limit), que nao
      estava no card #1. Confirmar que responde e ver o que devolve.

  P6. Cardinalidade campanha -> item. Decide se SKU vira coluna ou tabela ponte.

  P7. Os meses que falharam batem com o gabarito quando fatiados em <= 30 dias?
      Marco 204.87, julho 839.18, agosto 88.91.

  P8. Ha diferenca entre o total do endpoint de LOJA e a soma do endpoint de
      CAMPANHA no mesmo periodo? Se houver, decide qual e a fonte de verdade
      do gasto no DRE.

Como rodar:
    cd ~/Documents/"Casa e Patas"/data-pipeline
    source venv/bin/activate          # o venv do PROJETO, nao o do dbt
    export TOKEN_BUCKET=cp-pipeline-tokens
    python3.12 extraction/shopee/explore_ads_api2.py

Evite rodar por volta das 06:00, quando o pipeline renova o token.
Mande a saida inteira para o Pedro, inclusive se parar no meio.
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

FMT = "%d-%m-%Y"          # a API de Ads usa DD-MM-YYYY, diferente do resto
MAX_DIAS_ADS = 30         # medido na rodada 1: 31 dias falha

# Gasto informado pelo Bruno em 21/08. Gabarito de conferencia.
GABARITO = {
    "marco":  (date(2026, 3, 1), date(2026, 3, 31), 204.87),
    "junho":  (date(2026, 6, 1), date(2026, 6, 30), 271.20),
    "julho":  (date(2026, 7, 1), date(2026, 7, 31), 839.18),
    "agosto": (date(2026, 8, 1), date(2026, 8, 31),  88.91),
}


def generate_sign(path: str, timestamp: int, access_token: str, shop_id: int) -> str:
    base = f"{PARTNER_ID}{path}{timestamp}{access_token}{shop_id}"
    return hmac.new(PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()


def chamar(path: str, extra: dict) -> dict:
    access_token, shop_id = get_valid_access_token()
    ts = int(time.time())
    params = {
        "partner_id": PARTNER_ID,
        "timestamp": ts,
        "sign": generate_sign(path, ts, access_token, shop_id),
        "access_token": access_token,
        "shop_id": shop_id,
        **extra,
    }
    try:
        r = requests.get(f"{API_HOST}{path}", params=params, timeout=30)
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
    return str(r.get("error") or r.get("erro_rede", "?")) + " " + str(r.get("message", ""))


def extrair_lista(r: dict) -> list:
    """Acha a lista de registros. Lista vazia e resposta legitima, nao ausencia."""
    resp = r.get("response")
    if isinstance(resp, list):
        return resp
    if not isinstance(resp, dict) or not resp:
        return []
    # Aceita lista de dicts E lista de escalares: get_product_level_campaign_id_list
    # pode devolver {"campaign_id_list": [111, 222]}, ids soltos. Exigir dict no
    # primeiro elemento fazia o script devolver o dicionario inteiro como se
    # fosse um registro, e a lista de ids se perdia.
    for v in resp.values():
        if isinstance(v, list):
            return v
    return [resp]


def somar(lista: list, campo: str) -> float:
    return round(sum(float(x[campo]) for x in lista
                     if isinstance(x.get(campo), (int, float))), 2)


def descrever_campos(reg, ind: str = "      ") -> None:
    # O registro nem sempre e dict: a lista de campanhas pode vir como ids
    # soltos. Imprimir o valor cru e mais util do que quebrar.
    if not isinstance(reg, dict):
        print(f"{ind}(nao e objeto) {type(reg).__name__}: {json.dumps(reg, ensure_ascii=False)[:80]}")
        return
    for k, v in reg.items():
        amostra = json.dumps(v, ensure_ascii=False)
        if len(amostra) > 55:
            amostra = amostra[:55] + "..."
        print(f"{ind}{k:<34} {type(v).__name__:<7} {amostra}")


def fatiar(inicio: date, fim: date, max_dias: int = MAX_DIAS_ADS) -> list:
    """Fatia [inicio, fim] em pedacos de no maximo max_dias INCLUSIVOS."""
    fatias, cursor = [], inicio
    while cursor <= fim:
        f = min(cursor + timedelta(days=max_dias - 1), fim)
        fatias.append((cursor, f))
        cursor = f + timedelta(days=1)
    return fatias


def performance_loja(inicio: date, fim: date) -> list:
    """Busca performance da loja no periodo, fatiando quando passa de 30 dias."""
    todos = []
    for a, b in fatiar(inicio, fim):
        r = chamar("/api/v2/ads/get_all_cpc_ads_daily_performance",
                   {"start_date": a.strftime(FMT), "end_date": b.strftime(FMT)})
        if tem_erro(r):
            print(f"      fatia {a}..{b}: ERRO -- {msg_erro(r)}")
            continue
        lista = extrair_lista(r)
        print(f"      fatia {a}..{b} ({(b - a).days + 1}d): {len(lista)} registro(s)")
        todos.extend(lista)
        time.sleep(1)
    return todos


# ---------------------------------------------------------------------------
# P4 + P7 — campos reais, e o gabarito com fatiamento correto
# ---------------------------------------------------------------------------
def explorar_campos_e_gabarito() -> dict:
    secao("P4/P7 — campos reais e conferencia contra o gabarito (fatiado em 30d)")
    achados = {}

    print("\n[a] Julho/2026 — agora fatiado, porque 31 dias estoura o limite")
    julho = performance_loja(date(2026, 7, 1), date(2026, 7, 31))
    print(f"    Total de registros em julho: {len(julho)} (esperado 31, um por dia)")

    if julho:
        print("\n    >>> CAMPOS DE UM REGISTRO -- e isto que vira o schema:")
        descrever_campos(julho[0])
        achados["campos"] = sorted(julho[0].keys())

        # o nome do campo de gasto pode nao ser 'expense'; procurar candidatos
        candidatos = [k for k in julho[0] if any(
            t in k.lower() for t in ("expense", "cost", "spend"))]
        print(f"\n    Campos que parecem gasto: {candidatos}")
        achados["campos_de_gasto"] = candidatos

        print("\n    >>> AMOSTRA de 3 dias, para ver dia com e sem campanha:")
        for reg in julho[:3]:
            print(f"      {json.dumps(reg, ensure_ascii=False)[:200]}")

    print("\n[b] Conferencia de todos os meses do gabarito")
    for nome, (ini, fim, esperado) in GABARITO.items():
        print(f"\n    {nome.upper()} (esperado R$ {esperado:.2f}):")
        lista = performance_loja(ini, fim)
        dias_esperados = (fim - ini).days + 1
        soma = somar(lista, "expense")
        delta = abs(soma - esperado)
        veredito = "BATE" if delta < 0.02 else f"DIVERGE em {delta:.2f}"
        print(f"      {len(lista)} de {dias_esperados} dia(s) | expense = {soma:.2f} -- {veredito}")
        achados[f"gabarito_{nome}"] = {"soma": soma, "esperado": esperado,
                                       "dias": len(lista), "veredito": veredito}

        # P1 confirmada: quantos dias vieram com gasto zero?
        zerados = sum(1 for x in lista if not x.get("expense"))
        print(f"      dias com expense zero/ausente: {zerados}")

    return achados


# ---------------------------------------------------------------------------
# P5 + P6 — a lista de campanhas, que faltava no card #1
# ---------------------------------------------------------------------------
def explorar_campanhas() -> dict:
    secao("P5/P6 — get_product_level_campaign_id_list (endpoint que faltava)")
    achados = {}

    print("\n[a] Listando campanhas. ad_type='all', offset=0, limit=50")
    r = chamar("/api/v2/ads/get_product_level_campaign_id_list",
               {"ad_type": "all", "offset": 0, "limit": 50})

    if tem_erro(r):
        print(f"    ERRO -- {msg_erro(r)}")
        print("\n    Tentando variacoes de ad_type:")
        for ad_type in ("all", "auto", "manual", "gms", "product"):
            r2 = chamar("/api/v2/ads/get_product_level_campaign_id_list",
                        {"ad_type": ad_type, "offset": 0, "limit": 50})
            estado = "OK" if not tem_erro(r2) else f"erro: {msg_erro(r2)[:60]}"
            print(f"      ad_type={ad_type:<8} -> {estado}")
            if not tem_erro(r2):
                r = r2
                break
            time.sleep(1)

    if tem_erro(r):
        achados["campanhas"] = "erro"
        print(json.dumps(r, indent=2, ensure_ascii=False)[:800])
        return achados

    print(f"\n    RESPOSTA CRUA:\n{json.dumps(r.get('response'), indent=2, ensure_ascii=False)[:1200]}")
    campanhas = extrair_lista(r)
    print(f"\n    Campanhas devolvidas: {len(campanhas)}")
    achados["n_campanhas"] = len(campanhas)

    if not campanhas:
        print("    >>> Nenhuma campanha. Com a midia pausada, pode ser esperado --")
        print("        mas marco a agosto tiveram gasto, entao campanha existiu.")
        print("        Se vier vazio, o backfill por campanha pode ser impossivel")
        print("        e o grao campanha x dia so valeria daqui pra frente.")
        return achados

    print("\n    CAMPOS DE UMA CAMPANHA:")
    descrever_campos(campanhas[0])
    achados["campos_campanha"] = sorted(campanhas[0].keys()) if isinstance(campanhas[0], dict) else "nao-dict"

    # extrair os ids, seja qual for o formato
    ids = []
    for c in campanhas:
        if isinstance(c, dict):
            for k in ("campaign_id", "campaignId", "id"):
                if k in c:
                    ids.append(c[k])
                    break
        elif isinstance(c, int):
            ids.append(c)
    print(f"\n    IDs extraidos: {ids[:20]}{' ...' if len(ids) > 20 else ''}")
    achados["campaign_ids"] = ids[:50]

    if not ids:
        return achados

    print("\n[b] get_product_level_campaign_setting_info — agora COM os ids")
    r2 = chamar("/api/v2/ads/get_product_level_campaign_setting_info",
                {"campaign_id_list": ",".join(str(i) for i in ids[:10])})
    if tem_erro(r2):
        print(f"    ERRO -- {msg_erro(r2)}")
        achados["setting_info"] = "erro"
    else:
        settings = extrair_lista(r2)
        print(f"    Campanhas com setting: {len(settings)}")
        if settings:
            print("\n    CAMPOS DE SETTING:")
            descrever_campos(settings[0])
            print("\n    >>> CARDINALIDADE campanha -> item (decide coluna vs ponte):")
            multi = 0
            for s in settings[:15]:
                itens = s.get("item_id_list") or []
                if isinstance(itens, list) and len(itens) > 1:
                    multi += 1
                print(f"      campanha {s.get('campaign_id','?')}: {len(itens) if isinstance(itens,list) else '?'} item(ns) -> {str(itens)[:60]}")
            print(f"\n    >>> {multi} de {len(settings[:15])} campanha(s) com MAIS DE UM item.")
            achados["campanhas_multi_item"] = multi

    print("\n[c] get_product_campaign_daily_performance — julho, com os ids")
    r3 = chamar("/api/v2/ads/get_product_campaign_daily_performance",
                {"start_date": "01-07-2026", "end_date": "30-07-2026",
                 "campaign_id_list": ",".join(str(i) for i in ids[:10])})
    if tem_erro(r3):
        print(f"    ERRO -- {msg_erro(r3)}")
        achados["perf_campanha"] = "erro"
    else:
        perf = extrair_lista(r3)
        print(f"    Registros: {len(perf)}")
        if perf:
            print("\n    CAMPOS DE PERFORMANCE POR CAMPANHA:")
            descrever_campos(perf[0])
            soma_camp = somar(perf, "expense")
            print(f"\n    >>> P8: soma de expense por campanha (01-30/07): {soma_camp:.2f}")
            print("        Compare com o total da loja no mesmo periodo, acima.")
            print("        Divergencia decide qual e a fonte de verdade do DRE.")
            achados["soma_campanha_julho"] = soma_camp
            achados["campos_perf_campanha"] = sorted(perf[0].keys())

    return achados


if __name__ == "__main__":
    print(f"Partner ID: {PARTNER_ID}  (esperado 2039225, producao)")
    print(f"Rodado em: {datetime.now():%d/%m/%Y %H:%M}")
    print(f"Limite de janela conhecido: {MAX_DIAS_ADS} dias inclusivos (medido na rodada 1)")

    resumo = {}
    try:
        resumo.update(explorar_campos_e_gabarito())
        resumo.update(explorar_campanhas())
    except Exception as e:
        print(f"\n\n!!! Interrompido: {type(e).__name__}: {e}")
        print("    Mande a saida ate aqui mesmo assim.")

    secao("RESUMO")
    print(json.dumps(resumo, indent=2, ensure_ascii=False, default=str))
    print(
        "\nO que eu preciso ver:\n"
        "  1. Os campos reais do endpoint de loja (nome e tipo) -- vira o schema.\n"
        "  2. Marco 204.87, julho 839.18, agosto 88.91: batem quando fatiado?\n"
        "  3. Existe campanha listavel? Quantas, e com quantos itens cada?\n"
        "  4. O total por campanha bate com o total da loja no mesmo periodo?\n"
    )
