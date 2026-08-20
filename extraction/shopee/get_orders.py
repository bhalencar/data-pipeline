import hashlib
import hmac
import time
import os
import json
import requests
from datetime import datetime, timedelta, timezone, date
from dotenv import load_dotenv
from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

# Quantos dias para trás reler a cada rodada.
#
# O pipeline não relê pedido antigo por acidente: ele relê de propósito. Um pedido
# criado ontem entra na base como READY_TO_SHIP e sem escrow, porque o escrow só
# nasce depois que a Shopee libera o repasse. Se a extração nunca voltasse nele,
# o status e o financeiro ficariam congelados na primeira leitura para sempre.
# Foi o que aconteceu com julho/2026: 18 pedidos presos em status intermediário e
# 1 sem escrow nenhum, sumindo do GMV em silêncio.
#
# 30 dias cobre o ciclo completo com folga: envio, entrega, confirmação automática
# do comprador (~7 dias) e liberação do escrow.
REFRESH_WINDOW_DAYS = int(os.getenv("SHOPEE_REFRESH_WINDOW_DAYS", "30"))

# A API get_order_list limita o intervalo de create_time por chamada. Fatiamos a
# janela em pedaços seguros em vez de torcer para caber.
MAX_WINDOW_DAYS = 15


def generate_sign(path: str, timestamp: int, access_token: str, shop_id: int) -> str:
    # Fórmula "Shop APIs": partner_id + path + timestamp + access_token + shop_id
    base_string = f"{PARTNER_ID}{path}{timestamp}{access_token}{shop_id}"
    return hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def fatiar_janela(inicio: date, fim: date, max_dias: int = MAX_WINDOW_DAYS) -> list:
    """Quebra o intervalo [inicio, fim] em fatias de no máximo max_dias."""
    fatias = []
    cursor = inicio
    while cursor <= fim:
        fim_fatia = min(cursor + timedelta(days=max_dias - 1), fim)
        fatias.append((cursor, fim_fatia))
        cursor = fim_fatia + timedelta(days=1)
    return fatias


def get_order_list(time_from: int, time_to: int) -> list:
    """Busca a lista enxuta de pedidos (só order_sn + status), paginando automaticamente."""
    access_token, shop_id = get_valid_access_token()
    path = "/api/v2/order/get_order_list"

    all_orders = []
    cursor = ""
    has_more = True

    while has_more:
        timestamp = int(time.time())
        sign = generate_sign(path, timestamp, access_token, shop_id)

        url = (
            f"{API_HOST}{path}"
            f"?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
            f"&access_token={access_token}&shop_id={shop_id}"
            f"&time_range_field=create_time&time_from={time_from}&time_to={time_to}"
            f"&page_size=100&cursor={cursor}"
        )

        response = requests.get(url)
        data = response.json()

        if data.get("error"):
            raise Exception(f"Erro ao buscar lista de pedidos: {data}")

        response_data = data.get("response", {})
        all_orders.extend(response_data.get("order_list", []))

        has_more = response_data.get("more", False)
        cursor = response_data.get("next_cursor", "")

    return all_orders


def get_order_detail(order_sn_list: list) -> list:
    """Busca o detalhe completo (com item_list) de pedidos, em lotes de até 50."""
    access_token, shop_id = get_valid_access_token()
    path = "/api/v2/order/get_order_detail"

    optional_fields = [
        "item_list", "total_amount", "order_status", "pay_time",
        "buyer_username", "payment_method", "actual_shipping_fee",
        "shipping_carrier", "create_time",
    ]
    optional_fields_str = ",".join(optional_fields)

    all_details = []
    batch_size = 50

    for i in range(0, len(order_sn_list), batch_size):
        batch = order_sn_list[i:i + batch_size]
        order_sn_list_str = ",".join(batch)

        timestamp = int(time.time())
        sign = generate_sign(path, timestamp, access_token, shop_id)

        url = (
            f"{API_HOST}{path}"
            f"?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
            f"&access_token={access_token}&shop_id={shop_id}"
            f"&order_sn_list={order_sn_list_str}"
            f"&response_optional_fields={optional_fields_str}"
        )

        response = requests.get(url)
        data = response.json()

        if data.get("error"):
            raise Exception(f"Erro ao buscar detalhe dos pedidos: {data}")

        all_details.extend(data.get("response", {}).get("order_list", []))

    return all_details


def get_escrow_detail(order_sn_list: list) -> list:
    """
    Busca o detalhe financeiro (escrow) de cada pedido, um por vez.

    Pedido recém-criado ainda não tem escrow: a Shopee devolve erro, e isso é
    esperado, não é falha do pipeline. Por isso o erro não interrompe a rodada.
    Mas ele é contado e reportado — escrow que continua faltando depois da janela
    de releitura é problema de verdade, e o teste not_null em gmv_item pega isso.
    """
    access_token, shop_id = get_valid_access_token()
    path = "/api/v2/payment/get_escrow_detail"

    all_escrows = []
    falhas = []

    for order_sn in order_sn_list:
        timestamp = int(time.time())
        sign = generate_sign(path, timestamp, access_token, shop_id)

        url = (
            f"{API_HOST}{path}"
            f"?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
            f"&access_token={access_token}&shop_id={shop_id}"
            f"&order_sn={order_sn}"
        )

        response = requests.get(url)
        data = response.json()

        if data.get("error"):
            falhas.append((order_sn, data.get("error"), data.get("message", "")))
            continue

        all_escrows.append(data["response"])

    if falhas:
        print(f"Escrow indisponível para {len(falhas)} de {len(order_sn_list)} pedido(s):")
        for order_sn, erro, mensagem in falhas[:10]:
            print(f"  - {order_sn}: {erro} {mensagem}".rstrip())
        if len(falhas) > 10:
            print(f"  ... e mais {len(falhas) - 10}.")

    return all_escrows


def salvar(nome_tabela: str, conteudo: list, referencia: date) -> None:
    pasta = f"data/bronze/{nome_tabela}"
    os.makedirs(pasta, exist_ok=True)
    with open(f"{pasta}/{referencia}.json", "w") as f:
        json.dump(conteudo, f, indent=2)


if __name__ == "__main__":
    tz = timezone(timedelta(hours=-3))
    ontem = datetime.now(tz).date() - timedelta(days=1)
    inicio = ontem - timedelta(days=REFRESH_WINDOW_DAYS - 1)

    print(f"Janela de extração: {inicio} a {ontem} ({REFRESH_WINDOW_DAYS} dias, fuso de Brasília).")

    # Uma chamada por fatia de 15 dias. A janela inclui ontem, então o pedido novo
    # entra pelo mesmo caminho do pedido que está sendo relido — não há dois fluxos.
    coletados = []
    for fatia_inicio, fatia_fim in fatiar_janela(inicio, ontem):
        inicio_dt = datetime.combine(fatia_inicio, datetime.min.time(), tzinfo=tz)
        fim_dt = datetime.combine(fatia_fim, datetime.max.time(), tzinfo=tz)
        parcial = get_order_list(int(inicio_dt.timestamp()), int(fim_dt.timestamp()))
        print(f"  {fatia_inicio} a {fatia_fim}: {len(parcial)} pedido(s).")
        coletados.extend(parcial)

    # As fatias não se sobrepõem, mas deduplicar aqui é barato e protege de
    # qualquer borda da API devolver o mesmo pedido duas vezes.
    vistos = set()
    order_list = []
    for pedido in coletados:
        if pedido["order_sn"] not in vistos:
            vistos.add(pedido["order_sn"])
            order_list.append(pedido)

    print(f"{len(order_list)} pedido(s) na janela.")
    salvar("get_order_list", order_list, ontem)

    if order_list:
        order_sns = [o["order_sn"] for o in order_list]

        print("Buscando detalhes dos pedidos...")
        order_details = get_order_detail(order_sns)
        salvar("get_order_detail", order_details, ontem)
        print(f"Detalhes salvos para {len(order_details)} pedido(s).")

        print("Buscando dados financeiros (escrow)...")
        escrow_details = get_escrow_detail(order_sns)
        salvar("get_escrow_detail", escrow_details, ontem)
        print(f"Dados financeiros salvos para {len(escrow_details)} pedido(s).")
    else:
        print("Nenhum pedido encontrado na janela.")
