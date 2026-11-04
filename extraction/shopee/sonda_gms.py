"""
Sonda 2: os endpoints GMS (GMV Max) existem e respondem para a nossa loja?

HISTORICO, porque a segunda versao deste arquivo existe por erro meu.

Sonda 1 (03/11/2026) provou:
  - `get_product_level_campaign_id_list` aceita SO [all, auto, manual]. A
    propria API devolveu a lista no error_param. Nenhum alcanca GMV Max, e
    `all` traz as mesmas 25 campanhas que `manual`.
  - `get_gms_campaign_id_list` devolve error_not_found -- nao existe. Chute meu.
  - Conciliacao direto na API: loja R$ 110,13 x campanhas R$ 89,15 = R$ 20,98.

Primeira rodada da sonda 2 (03/11/2026) bateu em `ads_rate_limit_total_api`
em tres dos quatro caminhos. Eu tinha copiado do get_ads.py tudo menos a parte
que importava: a retentativa com espera progressiva. Esta versao corrige isso
e, de quebra, gasta MENOS chamadas -- a etapa 2 so roda para o caminho que a
etapa 1 ja provou existir, e so no formato de data que funcionar.

O unico resultado limpo da primeira rodada vale ouro e esta preservado aqui:
`check_create_gms_product_campaign_eligibility` respondeu SEM ERRO. O modulo
GMS existe neste host e o nosso app tem permissao nele. O que falta e achar a
forma de enumerar e ler campanha.

COMO LER A RESPOSTA -- o codigo de erro diz em que degrau paramos:

  error_not_found      -> o caminho nao existe. Nome errado.
  error_auth/permission/sign
                       -> o caminho EXISTE, o app nao tem permissao.
  error_param          -> existe E temos permissao, so o parametro esta errado.
                          MELHOR NOTICIA POSSIVEL: foi assim que destravamos o
                          Brand Portal em outubro.
  rate limit           -> nao diz nada sobre o caminho. Espera e tenta de novo.
  sem erro             -> dado na mao.

SO LE. Nenhum create_ ou edit_ do modulo GMS entra aqui, de proposito.

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

PAUSA_SEG = 2.0

# Tres codigos ja observados em producao. O terceiro apareceu em 03/11/2026,
# na primeira rodada desta sonda, e nao estava em lugar nenhum do projeto.
ERROS_RATE_LIMIT = (
    "error_rate_limit",
    "ads.rate_limit.exceed_api",
    "ads_rate_limit_total_api",
)
TENTATIVAS = 4
ESPERA_INICIAL = 10.0
ESPERA_MAX = 90.0

# Somente leitura. Os create_/edit_ do modulo GMS existem e ficam de fora.
CAMINHOS_LEITURA = [
    "/api/v2/ads/get_gms_campaign_performance",
    "/api/v2/ads/get_gms_item_performance",
    "/api/v2/ads/list_gms_user_deleted_item",
    "/api/v2/ads/check_create_gms_product_campaign_eligibility",
]

# Product Ads usa DD-MM-YYYY. Nao ha garantia de que GMS use o mesmo, e errar
# o formato na Shopee as vezes devolve VAZIO em vez de erro -- falha silenciosa
# que ja custou uma exploracao inteira em setembro.
FORMATOS_DATA = [("DD-MM-YYYY", "%d-%m-%Y"), ("YYYY-MM-DD", "%Y-%m-%d")]


def generate_sign(path: str, ts: int, token: str, shop: int) -> str:
    base = f"{PARTNER_ID}{path}{ts}{token}{shop}"
    return hmac.new(PARTNER_KEY.encode("utf-8"), base.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def chamar(path: str, extra: dict) -> dict:
    """
    Devolve o JSON cru -- aqui o erro E o resultado -- mas retenta em rate
    limit. O sign e refeito a cada tentativa: o timestamp entra na assinatura,
    e reusar os params depois de dormir 90 s trocaria o erro de rate limit por
    um erro de assinatura, mais dificil de diagnosticar que o original.
    """
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

        erro = dados.get("error") or ""
        if erro not in ERROS_RATE_LIMIT:
            return dados

        if tentativa == TENTATIVAS:
            return dados

        print(f"      rate limit ({tentativa}/{TENTATIVAS}); "
              f"aguardando {espera:.0f}s.", flush=True)
        time.sleep(espera)
        espera = min(espera * 2, ESPERA_MAX)

    return dados


def classificar(dados: dict) -> str:
    erro = dados.get("error") or ""
    if not erro:
        return "OK"
    if erro in ERROS_RATE_LIMIT:
        return "RATE LIMIT (nada se conclui)"
    if "not_found" in erro:
        return "NAO EXISTE"
    if "param" in erro:
        return "EXISTE + PERMITIDO (so o parametro esta errado)"
    if any(t in erro for t in ("auth", "permission", "sign", "token")):
        return "EXISTE, SEM PERMISSAO"
    return f"outro ({erro})"


def mostrar(dados: dict, limite: int = 1200) -> None:
    if dados.get("error"):
        print(f"      {dados['error']}: {dados.get('message', '')}")
        return
    texto = json.dumps(dados.get("response"), ensure_ascii=False, indent=2)
    print("      resposta:")
    for linha in texto[:limite].splitlines():
        print(f"        {linha}")
    if len(texto) > limite:
        print("        ...")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        inicio = date.fromisoformat(sys.argv[1])
        fim = date.fromisoformat(sys.argv[2])
    else:
        inicio = date(2026, 10, 1)
        fim = datetime.now().date() - timedelta(days=1)

    print(f"Sonda GMS — periodo {inicio} a {fim}\n")

    # ------------------------------------------------ 1. os caminhos existem?
    print("[1/2] Os caminhos existem? (chamada minima, so para ler o codigo)")
    vivos, limitados = [], []

    for path in CAMINHOS_LEITURA:
        curto = path.rsplit("/", 1)[-1]
        print(f"  {curto}")
        dados = chamar(path, {})
        veredito = classificar(dados)
        print(f"      -> {veredito}")
        mostrar(dados)

        if veredito.startswith("RATE LIMIT"):
            limitados.append(curto)
        elif veredito != "NAO EXISTE":
            vivos.append(path)

        time.sleep(PAUSA_SEG)

    if limitados:
        print(f"\n  Ainda limitados: {', '.join(limitados)}")
        print("  O `ads_rate_limit_total_api` parece ser cota TOTAL do modulo,")
        print("  nao por endpoint. Se persistir, rode amanha -- e nao rode nada")
        print("  de Ads hoje, para nao disputar cota com a rodada das 06:00.")

    alvo = "/api/v2/ads/get_gms_campaign_performance"
    if alvo not in vivos:
        print(f"\n[2/2] {alvo.rsplit('/', 1)[-1]} nao respondeu limpo. Paro aqui")
        print("  em vez de gastar cota tentando parametro no escuro.")
        sys.exit(0)

    # --------------------------------------- 2. performance, com data de verdade
    print("\n[2/2] Performance por campanha")

    for rotulo, fmt in FORMATOS_DATA:
        print(f"  --- formato {rotulo} ---")
        dados = chamar(alvo, {
            "start_date": inicio.strftime(fmt),
            "end_date": fim.strftime(fmt),
        })
        mostrar(dados)

        if not dados.get("error"):
            print("\n  Procure por 'Lancamentos 1' e pelo gasto de R$ 8,49 em out.")
            break   # achou o formato certo; nao gasta cota no outro

        if "param" in (dados.get("error") or ""):
            print("      (mensagem de parametro = o caminho e nosso. Se pedir")
            print("       campaign_id_list, nao temos de onde tirar: nao existe")
            print("       get_gms_campaign_id_list. Ai vira pergunta a Shopee.)")

        time.sleep(PAUSA_SEG)

    print("\nFim. Me manda a saida inteira.")
