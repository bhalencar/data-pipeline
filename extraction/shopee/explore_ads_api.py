"""
Exploracao da API de Ads da Shopee — etapa 1 do card #1 (master_ads).

NAO escreve nada, em lugar nenhum. So le, imprime e resume.

Por que este script existe antes de qualquer modelo: o card #1 lista os campos
que a documentacao promete, e a documentacao ja errou antes neste projeto. Sao
seis perguntas que so o dado real responde, e cada uma muda o desenho da tabela:

  P1. Um dia SEM campanha ativa devolve linha com zero, devolve nada, ou devolve
      erro? A midia esta pausada desde agosto, entao a maioria dos dias hoje e
      assim. Decide se a extracao preenche zero ou se ausencia vira ambigua --
      que foi exatamente o problema do bronze antes da releitura de 30 dias.

  P2. O backfill de marco funciona? A API pode limitar quanto se pode voltar no
      tempo, e o card assume marco a agosto sem ninguem ter testado.

  P3. Qual o intervalo maximo por chamada? O get_order_list aceita 15 dias. Se
      o de Ads for menor, o backfill precisa ser fatiado igual.

  P4. Quais campos vem DE FATO, com que nome e que tipo? O card lista onze
      metricas. Conferir antes de escrever o schema.

  P5. O campaign_id_list e obrigatorio no endpoint de campanha? Se for, existe
      um passo antes: descobrir quais campanhas existem.

  P6. O item_id_list liga campanha a SKU -- mas uma campanha pode ter varios
      itens. Precisa ver a cardinalidade real para decidir se vira coluna ou
      tabela ponte.

Como rodar:
    cd ~/Documents/"Casa e Patas"/data-pipeline
    source venv/bin/activate          # o venv do PROJETO, nao o do dbt
    export TOKEN_BUCKET=cp-pipeline-tokens
    python3.12 extraction/shopee/explore_ads_api.py

O TOKEN_BUCKET faz usar o mesmo cache de token do Cloud Run, que e o
atualizado. Evite rodar por volta das 06:00, quando o pipeline renova o token.

A saida e longa de proposito. Mande ela inteira para o Pedro.
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

# A API de Ads usa DD-MM-YYYY, diferente de todo o resto do projeto, que usa
# timestamp unix. Errar isso devolve dado vazio em vez de erro -- silencioso.
FMT_DATA_ADS = "%d-%m-%Y"

# Periodos com gasto conhecido, informados pelo Bruno em 21/08. Servem de
# gabarito: se a API devolver numero diferente, o problema e nosso.
GASTO_CONHECIDO = {
    "marco":  ("01-03-2026", "31-03-2026", 204.87),
    "junho":  ("01-06-2026", "30-06-2026", 271.20),
    "julho":  ("01-07-2026", "31-07-2026", 839.18),
    "agosto": ("01-08-2026", "31-08-2026",  88.91),
}


def generate_sign(path: str, timestamp: int, access_token: str, shop_id: int) -> str:
    """Formula das Shop APIs: partner_id + path + timestamp + access_token + shop_id"""
    base_string = f"{PARTNER_ID}{path}{timestamp}{access_token}{shop_id}"
    return hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def chamar(path: str, extra_params: dict) -> dict:
    """Uma chamada GET assinada. Devolve o JSON cru, sem interpretar."""
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

    try:
        resposta = requests.get(f"{API_HOST}{path}", params=params, timeout=30)
    except requests.RequestException as e:
        return {"erro_rede": str(e)}

    try:
        return {"status_http": resposta.status_code, **resposta.json()}
    except ValueError:
        return {"status_http": resposta.status_code, "corpo_bruto": resposta.text[:500]}


def secao(titulo: str) -> None:
    print(f"\n\n{'=' * 72}\n{titulo}\n{'=' * 72}")


def mostrar(rotulo: str, resultado: dict, limite: int = 1500) -> None:
    print(f"\n--- {rotulo} ---")
    texto = json.dumps(resultado, indent=2, ensure_ascii=False)
    print(texto[:limite])
    if len(texto) > limite:
        print(f"... (+{len(texto) - limite} caracteres omitidos)")


def tem_erro(resultado: dict) -> bool:
    erro = str(resultado.get("error", ""))
    return erro not in ("", "0") or "erro_rede" in resultado


def descrever_campos(registro: dict, indent: str = "    ") -> None:
    """Imprime nome, tipo e exemplo de cada campo. E isto que vira o schema."""
    for chave, valor in registro.items():
        tipo = type(valor).__name__
        amostra = json.dumps(valor, ensure_ascii=False)
        if len(amostra) > 60:
            amostra = amostra[:60] + "..."
        print(f"{indent}{chave:<32} {tipo:<8} {amostra}")


# ---------------------------------------------------------------------------
# P1 + P4 — performance diaria da loja, com e sem campanha ativa
# ---------------------------------------------------------------------------
def explorar_performance_loja() -> dict:
    secao("P1/P4 — get_all_cpc_ads_daily_performance (nivel loja, diario)")

    path = "/api/v2/ads/get_all_cpc_ads_daily_performance"
    achados = {}

    # Julho: mes com gasto alto conhecido (839,18). Aqui TEM que vir dado.
    print("\n[a] Julho/2026 — mes com gasto conhecido de R$ 839,18")
    julho = chamar(path, {"start_date": "01-07-2026", "end_date": "31-07-2026"})
    if tem_erro(julho):
        mostrar("ERRO em julho", julho)
        achados["julho_ok"] = False
        return achados

    achados["julho_ok"] = True
    lista = _extrair_lista(julho)
    print(f"    Registros devolvidos: {len(lista)}")

    if lista:
        print("\n    CAMPOS DE UM REGISTRO (nome, tipo, exemplo):")
        descrever_campos(lista[0])
        achados["campos"] = sorted(lista[0].keys())

        soma = _somar_campo(lista, "expense")
        print(f"\n    Soma de 'expense' em julho: {soma}")
        print(f"    Esperado (Bruno, 21/08):        839.18")
        print(f"    >>> {'BATE' if abs(soma - 839.18) < 0.02 else 'NAO BATE -- investigar antes de modelar'}")
        achados["soma_julho"] = soma

    # Setembro: midia pausada. E AQUI que a P1 se responde.
    print("\n[b] Setembro/2026 — midia pausada, dias sem campanha")
    setembro = chamar(path, {"start_date": "01-09-2026", "end_date": "30-09-2026"})
    if tem_erro(setembro):
        print("    Devolveu ERRO para periodo sem campanha:")
        mostrar("erro", setembro, 600)
        achados["dia_vazio"] = "erro"
    else:
        vazia = _extrair_lista(setembro)
        print(f"    Registros devolvidos: {len(vazia)}")
        if not vazia:
            print("    >>> Periodo sem campanha devolve LISTA VAZIA.")
            print("        A extracao precisa preencher zero, senao ausencia de linha")
            print("        vira ambigua entre 'nao gastou' e 'nao extraiu'.")
            achados["dia_vazio"] = "lista_vazia"
        else:
            print("    >>> Devolve linha mesmo sem campanha. Amostra:")
            descrever_campos(vazia[0])
            achados["dia_vazio"] = "linha_com_zero"

    return achados


# ---------------------------------------------------------------------------
# P2 + P3 — ate onde volta no tempo, e qual o intervalo maximo
# ---------------------------------------------------------------------------
def explorar_limites_de_janela() -> dict:
    secao("P2/P3 — limite de data antiga e de tamanho de intervalo")

    path = "/api/v2/ads/get_all_cpc_ads_daily_performance"
    achados = {}

    print("\n[a] Backfill: a API aceita voltar ate marco/2026?")
    for nome, (inicio, fim, esperado) in GASTO_CONHECIDO.items():
        r = chamar(path, {"start_date": inicio, "end_date": fim})
        if tem_erro(r):
            erro = r.get("error") or r.get("erro_rede")
            print(f"    {nome:<8} {inicio} a {fim}: ERRO -- {erro}")
            achados[f"backfill_{nome}"] = f"erro: {erro}"
        else:
            lista = _extrair_lista(r)
            soma = _somar_campo(lista, "expense")
            bate = "BATE" if abs(soma - esperado) < 0.02 else f"DIVERGE (esperado {esperado})"
            print(f"    {nome:<8} {inicio} a {fim}: {len(lista):>3} registro(s), expense={soma:.2f} -- {bate}")
            achados[f"backfill_{nome}"] = soma
        time.sleep(1)  # respeitar o rate limit proprio de ads

    print("\n[b] Intervalo maximo por chamada")
    hoje = date.today()
    for dias in (7, 15, 31, 60, 90, 180):
        inicio = (hoje - timedelta(days=dias)).strftime(FMT_DATA_ADS)
        fim = hoje.strftime(FMT_DATA_ADS)
        r = chamar(path, {"start_date": inicio, "end_date": fim})
        if tem_erro(r):
            erro = r.get("error") or r.get("erro_rede")
            print(f"    {dias:>3} dias: ERRO -- {erro}")
            achados[f"janela_{dias}d"] = f"erro: {erro}"
        else:
            n = len(_extrair_lista(r))
            print(f"    {dias:>3} dias: OK, {n} registro(s)")
            achados[f"janela_{dias}d"] = n
        time.sleep(1)

    return achados


# ---------------------------------------------------------------------------
# P5 + P6 — campanhas: quais existem, e como ligam a SKU
# ---------------------------------------------------------------------------
def explorar_campanhas() -> dict:
    secao("P5/P6 — campanhas e a ligacao com SKU")

    achados = {}

    print("\n[a] get_product_level_campaign_setting_info — sem campaign_id")
    print("    (se responder, ele mesmo lista as campanhas; se exigir id,")
    print("     existe um passo anterior que o card #1 nao previu)")
    r = chamar("/api/v2/ads/get_product_level_campaign_setting_info", {})
    mostrar("resposta", r, 1200)
    achados["setting_info_sem_id"] = "erro" if tem_erro(r) else "ok"

    if not tem_erro(r):
        campanhas = _extrair_lista(r)
        print(f"\n    Campanhas devolvidas: {len(campanhas)}")
        if campanhas:
            print("\n    CAMPOS DE UMA CAMPANHA:")
            descrever_campos(campanhas[0])

            # P6: a cardinalidade item x campanha decide coluna vs tabela ponte
            print("\n    CARDINALIDADE campanha -> item:")
            for c in campanhas[:10]:
                itens = c.get("item_id_list") or []
                cid = c.get("campaign_id", "?")
                print(f"      campanha {cid}: {len(itens)} item(ns) -> {itens[:5]}")
            multi = [c for c in campanhas if len(c.get("item_id_list") or []) > 1]
            print(f"\n    >>> {len(multi)} de {len(campanhas)} campanha(s) com MAIS DE UM item.")
            if multi:
                print("        Gasto por SKU exigiria rateio arbitrario. Confirma a")
                print("        decisao de manter o grao em campanha x dia.")
            achados["campanhas"] = len(campanhas)
            achados["campanhas_multi_item"] = len(multi)

    print("\n[b] get_product_campaign_daily_performance — precisa de campaign_id_list?")
    r2 = chamar(
        "/api/v2/ads/get_product_campaign_daily_performance",
        {"start_date": "01-07-2026", "end_date": "31-07-2026"},
    )
    mostrar("sem campaign_id_list", r2, 900)
    achados["campanha_perf_sem_id"] = "erro" if tem_erro(r2) else "ok"

    return achados


# ---------------------------------------------------------------------------
# Auxiliares — a estrutura de resposta da Shopee varia por endpoint
# ---------------------------------------------------------------------------
def _extrair_lista(resultado: dict) -> list:
    """
    Acha a lista de registros dentro da resposta.

    Nao assumimos o nome da chave: os endpoints de Ads nao seguem o mesmo padrao
    dos de pedido, e descobrir isso e parte do objetivo deste script.
    """
    resposta = resultado.get("response")
    if isinstance(resposta, list):
        return resposta
    if not isinstance(resposta, dict) or not resposta:
        return []

    # Primeiro procura uma lista de registros, cheia OU vazia. Testar so a lista
    # cheia era um bug meu: com {"campaign_list": []} -- que e justamente o que
    # um periodo sem campanha deve devolver -- o codigo caia no fallback abaixo
    # e inventava UM registro contendo a lista vazia. O script contaria "1
    # registro" onde ha zero, e responderia a P1 errado.
    for valor in resposta.values():
        if isinstance(valor, list):
            if not valor or isinstance(valor[0], dict):
                return valor

    # Sem nenhuma lista: a resposta em si e o registro unico.
    return [resposta]


def _somar_campo(lista: list, campo: str) -> float:
    total = 0.0
    for registro in lista:
        valor = registro.get(campo)
        if isinstance(valor, (int, float)):
            total += float(valor)
    return round(total, 2)


if __name__ == "__main__":
    print(f"Partner ID: {PARTNER_ID}  (esperado 2039225, producao)")
    print(f"Host: {API_HOST}")
    print(f"Rodado em: {datetime.now():%d/%m/%Y %H:%M}")

    resumo = {}
    try:
        resumo.update(explorar_performance_loja())
        resumo.update(explorar_limites_de_janela())
        resumo.update(explorar_campanhas())
    except Exception as e:
        print(f"\n\n!!! Interrompido por excecao: {type(e).__name__}: {e}")
        print("    Mande a saida ate aqui mesmo assim -- ela ja diz bastante.")

    secao("RESUMO — e isto que decide o desenho")
    print(json.dumps(resumo, indent=2, ensure_ascii=False))
    print(
        "\nAs quatro respostas que eu preciso ver:\n"
        "  1. Dia sem campanha: lista vazia, linha zerada, ou erro?\n"
        "  2. Backfill de marco: funciona? A soma de julho bate com 839,18?\n"
        "  3. Qual a maior janela aceita numa chamada?\n"
        "  4. Campanha com mais de um item: quantas?\n"
    )
