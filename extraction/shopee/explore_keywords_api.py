"""
Exploracao da API de palavras-chave da Shopee — etapa 1 do card #2.

NAO escreve nada, em lugar nenhum. So le, imprime e resume.

O que ja sabemos, e nao precisa ser redescoberto:
  - `get_recommended_keyword_list(item_id)` responde. Testado em 18/08 pelo
    test_ads_access.py, com a MESMA assinatura HMAC do get_ads.py. Nao ha
    autenticacao nova neste card (isso e o card #5, de trafego).
  - Devolve keyword, search_volume, quality_score e suggested_bid.

QUATRO PERGUNTAS, e cada uma muda o desenho da tabela:

  P1. `get_item_list` funciona, e devolve o catalogo vivo?
      Decide se produto novo entra na coleta sozinho. Hoje o warehouse so
      conhece item que vendeu (12) ou que virou campanha (19) -- e 9
      anunciados nunca venderam, 2 venderam sem anuncio. As duas fontes sao
      parciais, e nenhuma inclui produto recem-cadastrado, que e justamente
      quando a pesquisa de palavra mais ajuda.

  P2. `input_keyword` devolve volume para termo FORA do nosso catalogo?
      Se sim, o Rubem ganha sondagem livre e a tabela precisa de uma coluna
      dizendo a origem da linha (sugerida pela Shopee x sondada por nos). Se
      nao, ele fica restrito ao que ja vendemos. Nao esta documentado.

  P3. Quantas palavras vem por item, e o campo de volume se chama mesmo
      `search_volume`? E o schema.

  P4. Duas chamadas seguidas no mesmo dia devolvem o mesmo numero?
      Se variarem, `search_volume` e estimativa instavel e o snapshot semanal
      precisa dizer isso no dicionario -- senao alguem vai comparar duas
      semanas e ver "crescimento" que e ruido de medicao.

Como rodar:
    cd ~/Documents/"Casa e Patas"/data-pipeline
    source venv/bin/activate          # o venv do PROJETO, nao o do dbt
    export TOKEN_BUCKET=cp-pipeline-tokens
    python3.12 extraction/shopee/explore_keywords_api.py

Evite rodar por volta das 06:00, quando o pipeline renova o token.
Mande a saida inteira, inclusive se parar no meio.
"""

import hashlib
import hmac
import json
import os
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

PAUSA_SEG = 1.0  # ads tem rate limit proprio: ads.rate_limit.exceed_api

# Escada Pet 2 Degraus -- o item que ja respondeu em 18/08.
ITEM_CONHECIDO = 58258244802

# Termos de fora do catalogo, para a P2. Escolhidos de proposito em categorias
# que a loja NAO vende, para nao haver duvida se o volume veio de item nosso.
TERMOS_DE_FORA = ["ração para gato", "coleira antipulgas", "aquário"]


def generate_sign(path: str, ts: int, token: str, shop: int) -> str:
    base = f"{PARTNER_ID}{path}{ts}{token}{shop}"
    return hmac.new(PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()


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
    try:
        r = requests.get(f"{API_HOST}{path}", params=params, timeout=45)
    except requests.RequestException as e:
        return {"erro_rede": str(e)}
    try:
        return {"status_http": r.status_code, **r.json()}
    except ValueError:
        return {"status_http": r.status_code, "corpo_bruto": r.text[:400]}


def secao(t: str) -> None:
    print(f"\n\n{'=' * 72}\n{t}\n{'=' * 72}")


def tem_erro(r: dict) -> bool:
    return str(r.get("error", "")) not in ("", "0") or "erro_rede" in r


def msg_erro(r: dict) -> str:
    return f"{r.get('error') or r.get('erro_rede', '?')} {r.get('message', '')}".strip()


def extrair_lista(r: dict) -> list:
    """Lista vazia e resposta legitima, nao ausencia -- por isso nao exijo dict."""
    resp = r.get("response")
    if isinstance(resp, list):
        return resp
    if not isinstance(resp, dict) or not resp:
        return []
    for v in resp.values():
        if isinstance(v, list):
            return v
    return [resp]


def descrever_campos(reg, ind: str = "      ") -> None:
    if not isinstance(reg, dict):
        print(f"{ind}(nao e objeto) {type(reg).__name__}: {json.dumps(reg, ensure_ascii=False)[:70]}")
        return
    for k, v in reg.items():
        a = json.dumps(v, ensure_ascii=False)
        if len(a) > 50:
            a = a[:50] + "..."
        print(f"{ind}{k:<26} {type(v).__name__:<7} {a}")


# ---------------------------------------------------------------------------
# P1 — o catalogo vivo
# ---------------------------------------------------------------------------
def explorar_catalogo() -> dict:
    secao("P1 — get_item_list: produto novo entra sozinho na coleta?")
    achados = {}

    # item_status e obrigatorio neste endpoint. NORMAL sao os ativos.
    r = chamar("/api/v2/product/get_item_list",
               {"offset": 0, "page_size": 100, "item_status": "NORMAL"})

    if tem_erro(r):
        print(f"    ERRO -- {msg_erro(r)}")
        print("\n    Tentando variacoes de item_status:")
        for status in ("NORMAL", "BANNED", "UNLIST", "NORMAL,UNLIST"):
            r2 = chamar("/api/v2/product/get_item_list",
                        {"offset": 0, "page_size": 100, "item_status": status})
            print(f"      item_status={status:<14} -> "
                  f"{'OK' if not tem_erro(r2) else msg_erro(r2)[:55]}")
            if not tem_erro(r2):
                r = r2
                break
            time.sleep(PAUSA_SEG)

    if tem_erro(r):
        print("\n    >>> get_item_list nao respondeu. A lista de itens teria de sair")
        print("        do warehouse (uniao de master_orders e master_ads = 21 itens),")
        print("        e produto novo so entraria depois de vender ou virar campanha.")
        achados["catalogo"] = "erro"
        return achados

    print(f"\n    RESPOSTA CRUA:\n{json.dumps(r.get('response'), indent=2, ensure_ascii=False)[:900]}")
    itens = extrair_lista(r)
    print(f"\n    Itens devolvidos: {len(itens)}")
    achados["itens_no_catalogo"] = len(itens)

    if itens:
        print("\n    CAMPOS DE UM ITEM:")
        descrever_campos(itens[0])

        ids = [i.get("item_id") for i in itens if isinstance(i, dict) and i.get("item_id")]
        achados["item_ids"] = ids[:60]
        print(f"\n    item_id extraidos: {len(ids)}")
        print(f"    >>> O warehouse conhece 21 itens (12 vendidos + 19 anunciados,")
        print(f"        com 10 em comum). O catalogo tem {len(ids)}.")
        if len(ids) > 21:
            print(f"        Diferenca de {len(ids) - 21} item(ns) que existem na loja e que")
            print("        NUNCA apareceriam se a lista viesse do warehouse.")

    return achados


# ---------------------------------------------------------------------------
# P2 + P3 + P4 — as palavras
# ---------------------------------------------------------------------------
def explorar_keywords() -> dict:
    secao("P2/P3/P4 — get_recommended_keyword_list")
    achados = {}

    print(f"\n[a] Sem input_keyword, item {ITEM_CONHECIDO} (Escada Pet)")
    r = chamar("/api/v2/ads/get_recommended_keyword_list", {"item_id": ITEM_CONHECIDO})
    if tem_erro(r):
        print(f"    ERRO -- {msg_erro(r)}")
        achados["keywords"] = "erro"
        return achados

    palavras = extrair_lista(r)
    print(f"    Palavras devolvidas: {len(palavras)}")
    achados["palavras_por_item"] = len(palavras)

    if palavras:
        print("\n    >>> CAMPOS DE UMA PALAVRA -- e isto que vira o schema:")
        descrever_campos(palavras[0])
        achados["campos"] = sorted(palavras[0].keys()) if isinstance(palavras[0], dict) else None

        # o nome do campo de volume pode nao ser search_volume
        if isinstance(palavras[0], dict):
            cands = [k for k in palavras[0] if any(
                t in k.lower() for t in ("volume", "search", "count"))]
            print(f"\n    Campos que parecem volume: {cands}")

        print("\n    TOP 10 por volume:")
        def vol(p):
            for k in ("search_volume", "searchVolume", "volume"):
                if isinstance(p, dict) and isinstance(p.get(k), (int, float)):
                    return p[k]
            return 0
        for p in sorted([x for x in palavras if isinstance(x, dict)], key=vol, reverse=True)[:10]:
            kw = p.get("keyword", "?")
            print(f"      {vol(p):>8}  {kw}")

    # P4 — estabilidade
    print("\n[b] P4: mesma chamada de novo, para ver se o numero e estavel")
    time.sleep(PAUSA_SEG)
    r2 = chamar("/api/v2/ads/get_recommended_keyword_list", {"item_id": ITEM_CONHECIDO})
    if not tem_erro(r2):
        p2 = extrair_lista(r2)
        def mapa(lst):
            return {x.get("keyword"): x.get("search_volume")
                    for x in lst if isinstance(x, dict)}
        m1, m2 = mapa(palavras), mapa(p2)
        comuns = set(m1) & set(m2)
        difs = [k for k in comuns if m1[k] != m2[k]]
        print(f"    {len(p2)} palavras na 2a chamada, {len(comuns)} em comum.")
        print(f"    Palavras com volume DIFERENTE entre as duas: {len(difs)}")
        if difs:
            print("    >>> O volume oscila na mesma janela. O dicionario precisa dizer")
            print("        isso, senao alguem compara duas semanas e ve crescimento")
            print("        que e ruido de medicao. Exemplos:")
            for k in difs[:5]:
                print(f"      {k}: {m1[k]} -> {m2[k]}")
        else:
            print("    >>> Estavel no mesmo dia. Variacao entre semanas sera sinal real.")
        achados["volume_instavel"] = len(difs)

    # P2 — sondagem livre
    print("\n[c] P2: input_keyword com termo FORA do catalogo")
    print("    (a loja nao vende nenhum destes -- se vier volume, e sondagem livre)")
    resultado_p2 = {}
    for termo in TERMOS_DE_FORA:
        r3 = chamar("/api/v2/ads/get_recommended_keyword_list",
                    {"item_id": ITEM_CONHECIDO, "input_keyword": termo})
        if tem_erro(r3):
            print(f"      '{termo}': ERRO -- {msg_erro(r3)[:55]}")
            resultado_p2[termo] = "erro"
        else:
            lst = extrair_lista(r3)
            achou = [x for x in lst if isinstance(x, dict)
                     and termo.lower() in str(x.get("keyword", "")).lower()]
            print(f"      '{termo}': {len(lst)} palavra(s), {len(achou)} contendo o termo")
            if achou:
                print(f"         -> {json.dumps(achou[0], ensure_ascii=False)[:110]}")
            resultado_p2[termo] = {"total": len(lst), "com_termo": len(achou)}
        time.sleep(PAUSA_SEG)

    achados["sondagem_livre"] = resultado_p2
    print("\n    >>> Se veio volume para termo de fora, a tabela precisa de coluna")
    print("        de ORIGEM (sugerida pela Shopee x sondada por nos) -- senao")
    print("        mistura catalogo com pesquisa exploratoria no mesmo grao.")

    return achados


if __name__ == "__main__":
    print(f"Partner ID: {PARTNER_ID}")
    print(f"Rodado em: {datetime.now():%d/%m/%Y %H:%M}")
    print("Card #2 -- master_keywords. Nenhuma autenticacao nova: mesma do get_ads.py.")

    resumo = {}
    try:
        resumo.update(explorar_catalogo())
        resumo.update(explorar_keywords())
    except Exception as e:
        print(f"\n\n!!! Interrompido: {type(e).__name__}: {e}")
        print("    Mande a saida ate aqui mesmo assim.")

    secao("RESUMO")
    print(json.dumps(resumo, indent=2, ensure_ascii=False, default=str))
    print(
        "\nO que decide o desenho:\n"
        "  1. get_item_list responde? Quantos itens, contra os 21 do warehouse?\n"
        "  2. input_keyword devolve volume para termo de fora?\n"
        "  3. Quantas palavras por item, e como se chama o campo de volume?\n"
        "  4. O volume oscila na mesma janela?\n"
    )
