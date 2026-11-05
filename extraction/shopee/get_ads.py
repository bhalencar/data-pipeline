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
  - O rate limit usa DOIS codigos de erro, nao um. `ads.rate_limit.exceed_api`
    era o conhecido; em 31/10/2026 apareceu `error_rate_limit`, com a mensagem
    "Too many requests. You have reached the rate limit. Please try again
    later.". Tratar so um dos dois nao protege.
  - O rate limit e TRANSITORIO por definicao: a propria resposta manda tentar
    de novo mais tarde. Por isso o `chamar()` retenta; ver a nota la.

Uso:
    python extraction/shopee/get_ads.py                      # janela padrao
    python extraction/shopee/get_ads.py 2026-03-01 2026-08-31  # backfill

Sem argumentos, refaz os ultimos SHOPEE_ADS_WINDOW_DAYS dias (padrao 30).
A releitura existe pelo mesmo motivo da de pedidos: a Shopee ajusta metrica
de atribuicao depois do fato, porque `broad_*` credita conversao numa janela
de 7 dias a partir do clique.
"""

import csv
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

# Retentativa em rate limit. Os dois codigos abaixo foram observados em
# producao; qualquer outro erro continua sendo fatal na primeira ocorrencia,
# porque erro de parametro ou de permissao nao melhora com espera.
ERROS_RATE_LIMIT = ("error_rate_limit", "ads.rate_limit.exceed_api")
RATE_LIMIT_TENTATIVAS = 5
RATE_LIMIT_ESPERA_INICIAL = 5.0
RATE_LIMIT_ESPERA_MAX = 60.0

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
    """
    Chamada autenticada, com retentativa apenas em rate limit.

    POR QUE EXISTE: em 31/10/2026 a primeira recusa por rate limit levantava
    RuntimeError, derrubava a etapa de Ads e com ela o pipeline inteiro --
    incluindo o `dbt build`, que ja tinha os pedidos do dia no bronze esperando
    para ser processados. Uma manha de gold velho por uma recusa que a propria
    Shopee classificou como "tente mais tarde".

    O QUE NAO FAZ, de proposito: nao retenta erro de rede nem JSON invalido, e
    nao engole erro de parametro, de assinatura ou de permissao. Esses nao
    melhoram com espera, e transformar todo erro em retentativa esconderia
    defeito nosso atras de cinco tentativas silenciosas.

    O SIGN E REFEITO A CADA TENTATIVA. Isso nao e detalhe de estilo: a
    assinatura entra `timestamp`, e a Shopee rejeita timestamp fora da janela
    de tolerancia. Reusar os params da tentativa anterior depois de dormir 60 s
    trocaria o erro de rate limit por um erro de assinatura -- mais dificil de
    diagnosticar que o original.
    """
    espera = RATE_LIMIT_ESPERA_INICIAL
    ultimo_erro = None

    for tentativa in range(1, RATE_LIMIT_TENTATIVAS + 1):
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

        erro = dados.get("error")
        if not erro:
            return dados

        mensagem = dados.get("message", "")
        ultimo_erro = f"{erro} {mensagem}".strip()

        if erro not in ERROS_RATE_LIMIT:
            raise RuntimeError(f"Erro da API em {path}: {ultimo_erro}")

        if tentativa == RATE_LIMIT_TENTATIVAS:
            break

        print(f"  rate limit em {path} (tentativa {tentativa}"
              f"/{RATE_LIMIT_TENTATIVAS}); aguardando {espera:.0f}s.",
              flush=True)
        time.sleep(espera)
        espera = min(espera * 2, RATE_LIMIT_ESPERA_MAX)

    raise RuntimeError(
        f"Erro da API em {path}: {ultimo_erro} "
        f"(persistiu apos {RATE_LIMIT_TENTATIVAS} tentativas com espera "
        f"progressiva ate {RATE_LIMIT_ESPERA_MAX:.0f}s)"
    )


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


def carregar_campanhas_extras(ja_listadas: list) -> list:
    """
    Campanhas que a listagem da Shopee NAO devolve, cadastradas a mao.

    POR QUE ISTO EXISTE. Em 30/10/2026 a loja passou a gastar numa campanha
    que o `get_product_level_campaign_id_list` nao enumera: ele aceita apenas
    `ad_type` in [all, auto, manual] -- a propria API devolve essa lista no
    error_param -- e a campanha "Lancamentos 1" (multi-produto) nao cai em
    nenhum deles. Resultado: R$ 39,18 de gasto sem campanha atribuida em cinco
    dias, invisivel ate alguem conferir a mao contra a plataforma.

    O que FOI MEDIDO em 04/11/2026, mandando o id novo junto com um id
    conhecido na mesma chamada:

      get_product_campaign_daily_performance  -> SERVE o id normalmente,
          34 dias de metrica, R$ 38,46, e ainda devolve ad_type=manual.
      get_product_level_campaign_setting_info -> RECUSA, com
          "please pass campaign ids of auto & manual product ad types only".

    Os dois endpoints discordam sobre o tipo da mesma campanha. E inconsistencia
    da Shopee, nao nossa, e e por isso que a lista extra entra SO na chamada de
    performance -- ver o bloco principal.

    COMO CADASTRAR UMA NOVA. Abra a campanha no Seller Centre e pegue o id da
    URL (.../pas/product/manual-mpd/<id>). Acrescente uma linha no
    `campanhas_extras.csv`. Quem avisa que falta cadastrar e o teste dbt
    `assert_ads_conciliacao_loja_campanha`, que compara o nivel loja com a soma
    das campanhas.

    Falha de leitura aqui NAO derruba a extracao: sem o arquivo seguimos com a
    lista da API, que e o comportamento de antes. Perder a campanha extra e
    ruim; perder a rodada inteira por causa de um CSV e pior.
    """
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "campanhas_extras.csv")
    extras = []

    try:
        with open(caminho, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                bruto = (linha.get("campaign_id") or "").strip()
                if not bruto:
                    continue
                try:
                    cid = int(bruto)
                except ValueError:
                    print(f"  AVISO: campaign_id invalido no CSV: {bruto!r}")
                    continue
                if cid in ja_listadas:
                    # A Shopee passou a enumerar sozinha. Nao e erro -- e a
                    # deixa para tirar a linha do CSV.
                    print(f"  {cid} ja vem na listagem da API; linha do CSV "
                          f"virou redundante.")
                    continue
                extras.append(cid)
    except FileNotFoundError:
        print("  campanhas_extras.csv nao encontrado; seguindo so com a API.")
        return []
    except Exception as e:                      # noqa: BLE001
        print(f"  AVISO: falha ao ler campanhas_extras.csv ({e}); "
              f"seguindo so com a API.")
        return []

    return extras


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
    ids_listados = get_campaign_ids()
    print(f"  {len(ids_listados)} campanha(s) na listagem da API.")

    ids_extras = carregar_campanhas_extras(ids_listados)
    if ids_extras:
        print(f"  {len(ids_extras)} campanha(s) extra(s) do campanhas_extras.csv: "
              f"{', '.join(str(i) for i in ids_extras)}")

    # DUAS LISTAS, DE PROPOSITO, E A DIFERENCA NAO E COSMETICA.
    #
    # A performance aceita os ids extras; o setting NAO -- ele responde
    # `error_param: please pass campaign ids of auto & manual product ad types
    # only`. E `chamar()` levanta RuntimeError em error_param, porque erro de
    # parametro nao melhora com retentativa.
    #
    # Mandar a lista completa para o setting derrubaria a etapa de Ads inteira
    # e, com ela, o `dbt build` da rodada. O conserto da campanha ausente teria
    # trocado um gasto invisivel por um pipeline quebrado todo dia.
    ids_performance = ids_listados + ids_extras

    campanhas = []
    if ids_performance:
        campanhas = get_campaign_daily(ids_performance, inicio, fim)
        salvar("get_ads_campaign_daily", campanhas, fim)
    else:
        print("  Nenhuma campanha. Nada a salvar na performance.")

    if ids_listados:
        settings = get_campaign_settings(ids_listados)
        salvar("get_ads_campaign_setting", settings, fim)
    else:
        print("  Nenhuma campanha listada. Nada a salvar no setting.")

    print("\n[3/3] Conferencia")
    total_loja = round(sum(float(d.get("expense") or 0) for d in shop), 2)
    print(f"  Gasto no periodo (nivel loja): R$ {total_loja:.2f}")

    # Conciliacao na propria extracao. O docstring deste arquivo afirmava que
    # loja e campanhas batiam e que a separacao era "seguranca contra dupla
    # contagem, nao reconciliacao". Isso deixou de ser verdade em 30/10/2026 e
    # ninguem viu por cinco dias. Agora a rodada diz o numero em voz alta.
    # O detector automatico e o teste dbt assert_ads_conciliacao_loja_campanha;
    # isto aqui e o aviso antecipado, visivel no log do Cloud Run.
    total_campanhas = round(sum(
        float(linha.get("expense") or 0) for linha in campanhas
    ), 2)
    diferenca = round(total_loja - total_campanhas, 2)
    print(f"  Gasto no periodo (soma das campanhas): R$ {total_campanhas:.2f}")
    print(f"  Diferenca: R$ {diferenca:.2f}")
    if abs(diferenca) > 1.00:
        print("  ATENCAO: diferenca acima de R$ 1,00. Provavel campanha que a "
              "listagem nao devolve.\n  Pegue o id na URL do Seller Centre e "
              "cadastre em extraction/shopee/campanhas_extras.csv.")
    print(f"  Dias com gasto zero: {sum(1 for d in shop if not d.get('expense'))} de {len(shop)}")
    print("\n  Dia zerado e normal com a midia pausada -- a Shopee devolve a linha "
          "mesmo assim.\n  Dia AUSENTE, nao. Se o total de dias for menor que o "
          "periodo pedido, houve falha de extracao.")