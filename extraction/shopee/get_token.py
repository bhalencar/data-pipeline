import hashlib
import hmac
import time
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()

# Host da API para chamadas de backend de Produção
API_HOST = "https://partner.shopeemobile.com"

# Caminho do cache de tokens (mesmo que o token_manager.py usa)
TOKEN_FILE = "extraction/shopee/.token_cache.json"


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


def save_token_cache(result: dict, shop_id: int) -> None:
    """
    Salva os tokens no formato que o token_manager.py espera.
    'obtained_at' é o timestamp local do momento da obtenção — é o que
    permite ao token_manager calcular se o token já expirou.
    """
    tokens = {
        "shop_id": shop_id,
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "expire_in": result["expire_in"],
        "obtained_at": int(time.time()),
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"Tokens salvos em {TOKEN_FILE}")


if __name__ == "__main__":
    # Valores obtidos na URL de redirecionamento, depois de autorizar (PRODUÇÃO)
    CODE = "434f7a5373514372516d50477a6e4d4b"
    SHOP_ID = 1523269919

    result = get_access_token(CODE, SHOP_ID)

    if result.get("error"):
        print(f"ERRO ao obter token: {result}")
    else:
        print(f"Token obtido com sucesso. Expira em {result['expire_in']}s")
        save_token_cache(result, SHOP_ID)