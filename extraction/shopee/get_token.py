import hashlib
import hmac
import time
import os
import requests
from dotenv import load_dotenv

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()

# Host da API para chamadas de backend no Sandbox
API_HOST = "https://openplatform.sandbox.test-stable.shopee.sg"


def generate_sign(path: str, timestamp: int) -> str:
    base_string = f"{PARTNER_ID}{path}{timestamp}"
    return hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def get_access_token(code: str, shop_id: int) -> dict:
    path = "/api/v2/auth/token/get"
    timestamp = int(time.time())
    sign = generate_sign(path, timestamp)

    # sign, partner_id e timestamp vão na URL (query string)
    url = f"{API_HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"

    # code, partner_id e shop_id vão no corpo da requisição (JSON)
    body = {
        "code": code,
        "partner_id": PARTNER_ID,
        "shop_id": shop_id,
    }

    response = requests.post(url, json=body)
    return response.json()


if __name__ == "__main__":
    # Valores obtidos na URL de redirecionamento, depois de autorizar
    CODE = "4b69416975754e63777a795270717276"
    SHOP_ID = 227751727

    result = get_access_token(CODE, SHOP_ID)
    print(result)