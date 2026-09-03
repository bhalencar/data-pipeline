"""
Teste de acesso ao modulo de Ads (105) da Shopee, em PRODUCAO.

Motivo: o API Test Tool do Open Platform so aceita o partner_id de sandbox
(1238362), entao nao serve para responder se o app de producao (2039225) tem
a permissao do modulo de Ads. Este script pergunta direto, reusando a mesma
assinatura e o mesmo token que o pipeline ja usa todo dia.

NAO escreve nada. So le e imprime a resposta crua.

Como rodar:
    source venv/bin/activate          # o venv do PROJETO, nao o do dbt
    export TOKEN_BUCKET=cp-pipeline-tokens
    python3.12 extraction/shopee/test_ads_access.py

O TOKEN_BUCKET faz o script usar o mesmo cache de token que o Cloud Run usa,
que e o que esta atualizado. Sem ele, o script cai no arquivo local, que pode
estar velho. Evite rodar por volta das 06:00, quando o pipeline esta renovando
o token.
"""

import hashlib
import hmac
import json
import os
import time

import requests
from dotenv import load_dotenv

from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

# Item real da loja, usado no teste de palavras-chave: Escada Pet 2 Degraus
ITEM_ID_TESTE = 58258244802


def generate_sign(path: str, timestamp: int, access_token: str, shop_id: int) -> str:
    """Formula das Shop APIs: partner_id + path + timestamp + access_token + shop_id"""
    base_string = f"{PARTNER_ID}{path}{timestamp}{access_token}{shop_id}"
    return hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def chamar(path: str, extra_params: dict) -> dict:
    access_token, shop_id = get_valid_access_token()
    timestamp = int(time.time())
    sign = generate_sign(path, timestamp, access_token, shop_id)

    params = {
        "partner_id": PARTNER_ID,
        "timestamp": timestamp,
        "sign": sign,
        "access_token": access_token,
        "shop_id": shop_id,
        **extra_params,
    }

    resposta = requests.get(f"{API_HOST}{path}", params=params, timeout=30)
    try:
        return {"status_http": resposta.status_code, **resposta.json()}
    except ValueError:
        return {"status_http": resposta.status_code, "corpo_bruto": resposta.text[:500]}


def interpretar(nome: str, resultado: dict) -> None:
    print(f"\n{'=' * 70}\n{nome}\n{'=' * 70}")
    print(json.dumps(resultado, indent=2, ensure_ascii=False)[:2000])

    erro = str(resultado.get("error", ""))
    if erro in ("", "0"):
        print("\n>>> VEREDITO: ACESSO LIBERADO. O modulo de Ads responde.")
    elif "permission" in erro:
        print("\n>>> VEREDITO: SEM PERMISSAO no modulo 105.")
        print("    O app existe; falta habilitar. Abrir ticket, nao criar app novo.")
    elif "token" in erro:
        print("\n>>> VEREDITO: problema de TOKEN, nao de permissao.")
        print("    Rode de novo com TOKEN_BUCKET definido e fora do horario do pipeline.")
    else:
        print(f"\n>>> VEREDITO: erro nao previsto ({erro}). Levar a mensagem para analise.")


if __name__ == "__main__":
    print(f"Partner ID em uso: {PARTNER_ID}  (esperado: 2039225, o de producao)")
    print(f"Host: {API_HOST}")

    # 1) Performance diaria de anuncios — so precisa de datas. Formato DD-MM-YYYY.
    interpretar(
        "1. v2.ads.get_all_cpc_ads_daily_performance",
        chamar(
            "/api/v2/ads/get_all_cpc_ads_daily_performance",
            {"start_date": "01-08-2026", "end_date": "16-08-2026"},
        ),
    )

    # 2) Palavras-chave recomendadas — precisa de um item_id real da loja.
    interpretar(
        "2. v2.ads.get_recommended_keyword_list",
        chamar(
            "/api/v2/ads/get_recommended_keyword_list",
            {"item_id": ITEM_ID_TESTE},
        ),
    )

    print(
        "\n\nSe o teste 2 responder, confira se vem 'search_volume' nas palavras.\n"
        "E o campo que decide se o Rubem ganha volume de busca ou nao."
    )
