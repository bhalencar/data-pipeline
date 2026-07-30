import hashlib
import hmac
import time
import os
import json
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from token_manager import get_valid_access_token

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"


def generate_sign(path: str, timestamp: int, access_token: str, shop_id: int) -> str:
    # Fórmula "Shop APIs": partner_id + path + timestamp + access_token + shop_id
    base_string = f"{PARTNER_ID}{path}{timestamp}{access_token}{shop_id}"
    return hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


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
    """Busca o detalhe financeiro (escrow) de cada pedido, um por vez."""
    access_token, shop_id = get_valid_access_token()
    path = "/api/v2/payment/get_escrow_detail"

    all_escrows = []

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
            print(f"Aviso: erro ao buscar escrow do pedido {order_sn}: {data}")
            continue

        all_escrows.append(data["response"])

    return all_escrows


if __name__ == "__main__":
    # D-1: dia de ontem inteiro, fuso de Brasília (UTC-3)
    tz = timezone(timedelta(hours=-3))
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    start_of_day = datetime.combine(yesterday, datetime.min.time(), tzinfo=tz)
    end_of_day = datetime.combine(yesterday, datetime.max.time(), tzinfo=tz)
    time_from, time_to = int(start_of_day.timestamp()), int(end_of_day.timestamp())

    print(f"Buscando pedidos de {yesterday} (D-1)...")
    order_list = get_order_list(time_from, time_to)
    print(f"{len(order_list)} pedidos encontrados.")

    os.makedirs("data/bronze/get_order_list", exist_ok=True)
    with open(f"data/bronze/get_order_list/{yesterday}.json", "w") as f:
        json.dump(order_list, f, indent=2)

    if order_list:
        order_sns = [o["order_sn"] for o in order_list]
        print("Buscando detalhes dos pedidos...")
        order_details = get_order_detail(order_sns)

        os.makedirs("data/bronze/get_order_detail", exist_ok=True)
        with open(f"data/bronze/get_order_detail/{yesterday}.json", "w") as f:
            json.dump(order_details, f, indent=2)

        print(f"Detalhes salvos para {len(order_details)} pedidos.")

         # NOVO: busca o financeiro (escrow) dos mesmos pedidos
        print("Buscando dados financeiros (escrow)...")
        escrow_details = get_escrow_detail(order_sns)

        os.makedirs("data/bronze/get_escrow_detail", exist_ok=True)
        with open(f"data/bronze/get_escrow_detail/{yesterday}.json", "w") as f:
            json.dump(escrow_details, f, indent=2)

        print(f"Dados financeiros salvos para {len(escrow_details)} pedidos.")
    else:
        print("Nenhum pedido encontrado nesse período.")
