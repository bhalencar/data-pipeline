import hashlib
import hmac
import time
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

# Carrega o token salvo
with open("extraction/shopee/.token_cache.json") as f:
    tokens = json.load(f)

SHOP_ID = tokens["shop_id"]
ACCESS_TOKEN = tokens["access_token"]


def generate_sign(path: str, timestamp: int) -> str:
    # Fórmula para "Shop APIs": partner_id + path + timestamp + access_token + shop_id
    base_string = f"{PARTNER_ID}{path}{timestamp}{ACCESS_TOKEN}{SHOP_ID}"
    return hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def get_shop_info():
    path = "/api/v2/shop/get_shop_info"
    timestamp = int(time.time())
    sign = generate_sign(path, timestamp)

    url = (
        f"{API_HOST}{path}"
        f"?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
        f"&access_token={ACCESS_TOKEN}&shop_id={SHOP_ID}"
    )

    response = requests.get(url)
    return response.json()


if __name__ == "__main__":
    print(get_shop_info())