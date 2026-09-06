"""
Extracao de volume de busca da Shopee (palavras-chave), camada bronze.

Card #2 do Roadmap de Dados. Fonte: Shopee Ads API, mesmo modulo 105 e mesma
autenticacao do get_ads.py -- nao ha credencial nova aqui.

POR QUE ESTE SCRIPT E DIFERENTE DE TODOS OS OUTROS DO PROJETO:

  O `search_volume` e uma janela MOVEL de 30 dias e a Shopee NAO guarda
  historico. Snapshot que nao for coletado esta perdido para sempre -- nao ha
  backfill possivel, diferente dos pedidos e do Ads, que a gente relê.

  Consequencia pratica: uma semana sem coleta e um buraco permanente na serie.
  Por isso a coleta e tolerante a falha por item (um item que der erro nao
  derruba os outros 24) e por isso o resumo final conta explicitamente quantos
  itens falharam.

FATOS DA API, medidos em 06/09/2026, nenhum suposto:

  - get_recommended_keyword_list(item_id) devolve keyword, quality_score,
    search_volume e suggested_bid. 38 palavras para a Escada Pet.
  - O volume e ESTAVEL dentro do mesmo dia: duas chamadas seguidas devolveram
    as mesmas 38 palavras com zero diferenca. Variacao entre semanas e sinal
    real, nao ruido de medicao.
  - `input_keyword` NAO faz sondagem livre. Testado com "racao para gato",
    "coleira antipulgas" e "aquario": devolveu 18 palavras em cada caso, todas
    do proprio item, NENHUMA contendo o termo. E teto da plataforma: nao da
    para pesquisar palavra fora do catalogo. Por isso este script nao usa o
    parametro.
  - get_item_list(item_status=NORMAL) devolve o catalogo ATIVO -- 10 itens.

DE ONDE SAI A LISTA DE ITENS, e por que nao e so o catalogo:

  Catalogo e warehouse sao parciais em direcoes OPOSTAS. Medido em 06/09:
  10 no catalogo, 21 no warehouse, apenas 6 em comum. O catalogo tem produto
  novo que nunca vendeu (o caso de uso do Rubem, que precisa da palavra na
  hora de escrever o titulo); o warehouse tem produto com historico que saiu
  do ar.

  A uniao dos dois da 25 itens, e e o que este script consulta.

  Produto pausado continua sendo consultado de proposito. O caso que fundou a
  regra: a "Caminha Pet MDF Tipo Berco" vendeu 5 pedidos, o ultimo em 09/08, e
  esta fora do catalogo porque o FORNECEDOR ficou sem estoque -- nao porque o
  produto morreu. Ela volta, e quando voltar a serie dela nao tera buraco.

Uso:
    python extraction/shopee/get_keywords.py            # so coleta na segunda
    python extraction/shopee/get_keywords.py --forcar   # coleta agora

A trava de dia existe porque o pipeline roda diario e a janela e de 30 dias:
coletar todo dia geraria 7 snapshots quase identicos por semana, sem ganho.
"""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

PROJECT_ID = "cp-pipeline-503623"
LOCATION = "southamerica-east1"
KEYFILE = os.path.join(os.path.expanduser("~"), ".gcp-keys", "dbt-bigquery-sa-key.json")

PAUSA_SEG = 1.0    # ads tem rate limit proprio: ads.rate_limit.exceed_api
DIA_DA_COLETA = 0  # segunda-feira (datetime.weekday(): 0=seg, 6=dom)

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


def extrair_lista(resultado: dict) -> list:
    """Lista vazia e resposta legitima, nao ausencia."""
    resp = resultado.get("response")
    if isinstance(resp, list):
        return resp
    if not isinstance(resp, dict) or not resp:
        return []
    for valor in resp.values():
        if isinstance(valor, list):
            return valor
    return [resp]


def get_client() -> bigquery.Client:
    # No Cloud Run a credencial vem da service account do proprio job.
    if os.path.exists(KEYFILE):
        creds = service_account.Credentials.from_service_account_file(KEYFILE)
        return bigquery.Client(project=PROJECT_ID, credentials=creds, location=LOCATION)
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


def itens_do_catalogo() -> set:
    """Catalogo ativo da loja. Produto novo entra aqui assim que cadastrado."""
    path = "/api/v2/product/get_item_list"
    ids, offset = set(), 0

    while True:
        dados = chamar(path, {"offset": offset, "page_size": 100,
                              "item_status": "NORMAL"})
        resposta = dados.get("response") or {}
        lote = resposta.get("item") or []
        ids.update(i["item_id"] for i in lote
                   if isinstance(i, dict) and i.get("item_id"))

        if not resposta.get("has_next_page") or not lote:
            break
        offset += len(lote)
        time.sleep(PAUSA_SEG)

    return ids


def itens_do_warehouse(client: bigquery.Client) -> set:
    """
    Itens que ja venderam ou foram anunciados, mesmo que fora do catalogo hoje.

    Sem isto, produto pausado por falta de estoque no fornecedor sairia da
    coleta e a serie dele ganharia um buraco do tamanho da pausa.
    """
    sql = f"""
        select distinct item_id from `{PROJECT_ID}.gold.master_orders`
        where item_id is not null
        union distinct
        select distinct item_id from `{PROJECT_ID}.gold.master_ads`
        where item_id is not null
    """
    return {linha.item_id for linha in client.query(sql).result()}


def keywords_do_item(item_id: int) -> list:
    dados = chamar("/api/v2/ads/get_recommended_keyword_list", {"item_id": item_id})
    return [k for k in extrair_lista(dados) if isinstance(k, dict)]


def salvar(nome_tabela: str, conteudo: list, referencia) -> None:
    pasta = os.path.join(BRONZE_DIR, nome_tabela)
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"{referencia}.json")
    with open(caminho, "w") as f:
        json.dump(conteudo, f, indent=2, ensure_ascii=False)
    print(f"  -> {caminho} ({len(conteudo)} registro(s))")


if __name__ == "__main__":
    tz = timezone(timedelta(hours=-3))
    agora = datetime.now(tz)
    hoje = agora.date()
    forcar = "--forcar" in sys.argv

    if agora.weekday() != DIA_DA_COLETA and not forcar:
        dias = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
        print(f"Hoje e {dias[agora.weekday()]}; a coleta de palavras-chave roda "
              f"as {dias[DIA_DA_COLETA]}s. Nada a fazer.")
        print("Use --forcar para coletar mesmo assim.")
        sys.exit(0)

    print(f"Coleta de palavras-chave — {hoje} (fuso de Brasilia).")

    print("\n[1/3] Montando a lista de itens")
    catalogo = itens_do_catalogo()
    print(f"  catalogo ativo: {len(catalogo)} item(ns)")

    client = get_client()
    warehouse = itens_do_warehouse(client)
    print(f"  warehouse (vendidos + anunciados): {len(warehouse)} item(ns)")

    itens = sorted(catalogo | warehouse)
    print(f"  uniao: {len(itens)} item(ns) — {len(catalogo & warehouse)} em comum, "
          f"{len(catalogo - warehouse)} so no catalogo, "
          f"{len(warehouse - catalogo)} so no warehouse")

    print("\n[2/3] Consultando palavras-chave")
    linhas, falhas = [], []

    for i, item_id in enumerate(itens, 1):
        try:
            palavras = keywords_do_item(item_id)
        except Exception as e:
            # Um item que falha nao pode derrubar os outros: snapshot perdido
            # nao volta, entao 24 de 25 e muito melhor que zero.
            falhas.append((item_id, str(e)[:90]))
            print(f"  [{i:>2}/{len(itens)}] item {item_id}: FALHOU — {str(e)[:70]}")
            time.sleep(PAUSA_SEG)
            continue

        for palavra in palavras:
            linha = dict(palavra)
            linha["item_id"] = item_id
            linha["data_snapshot"] = hoje.isoformat()
            linha["no_catalogo"] = item_id in catalogo
            linhas.append(linha)

        marca = "" if item_id in catalogo else "  (fora do catalogo)"
        print(f"  [{i:>2}/{len(itens)}] item {item_id}: {len(palavras)} palavra(s){marca}")
        time.sleep(PAUSA_SEG)

    salvar("get_keywords", linhas, hoje)

    print("\n[3/3] Conferencia")
    print(f"  {len(linhas)} linha(s) de {len(itens) - len(falhas)} item(ns).")

    if falhas:
        print(f"\n  ATENCAO: {len(falhas)} item(ns) falharam e ficam SEM snapshot")
        print("  desta semana. A Shopee nao guarda historico -- isso nao volta.")
        for item_id, erro in falhas[:10]:
            print(f"    - {item_id}: {erro}")
        if len(falhas) > 10:
            print(f"    ... e mais {len(falhas) - 10}.")
        print("\n  Se a falha for de rate limit, rode de novo com --forcar em alguns")
        print("  minutos: o carregamento e por data, entao reexecutar no mesmo dia")
        print("  substitui o arquivo em vez de duplicar.")
    else:
        print("  Nenhuma falha: todos os itens têm snapshot desta semana.")
