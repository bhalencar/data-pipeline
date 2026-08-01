import hashlib
import hmac
import time
import os
import json
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
API_HOST = "https://partner.shopeemobile.com"

# Caminho do arquivo de cache, relativo à raiz do projeto
TOKEN_FILE = "extraction/shopee/.token_cache.json"

# Onde guardar o token: local (arquivo) ou GCS (bucket).
# No Cloud Run o disco e efemero, entao o cache precisa viver fora do container.
# Definir TOKEN_BUCKET no ambiente ativa o modo GCS automaticamente.
TOKEN_BUCKET = os.getenv("TOKEN_BUCKET", "").strip()
TOKEN_BLOB = os.getenv("TOKEN_BLOB", "token_cache.json").strip()

# Margem de segurança: renovamos o token um pouco antes de expirar de verdade,
# pra evitar erro caso a chamada demore alguns segundos
SAFETY_MARGIN_SECONDS = 300  # 5 minutos


def _generate_sign(path: str, timestamp: int) -> str:
    base_string = f"{PARTNER_ID}{path}{timestamp}"
    return hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def _gcs_blob():
    """So importa a lib do GCS quando realmente for usar (modo nuvem)."""
    from google.cloud import storage
    client = storage.Client()
    return client.bucket(TOKEN_BUCKET).blob(TOKEN_BLOB)


def _load_tokens() -> dict:
    if TOKEN_BUCKET:
        return json.loads(_gcs_blob().download_as_text())
    with open(TOKEN_FILE) as f:
        return json.load(f)


def _save_tokens(data: dict) -> None:
    if TOKEN_BUCKET:
        _gcs_blob().upload_from_string(
            json.dumps(data, indent=2),
            content_type="application/json",
        )
        return
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _is_expired(tokens: dict) -> bool:
    expiry_time = tokens["obtained_at"] + tokens["expire_in"]
    return time.time() > (expiry_time - SAFETY_MARGIN_SECONDS)


def _refresh_access_token(tokens: dict) -> dict:
    """Usa o refresh_token para pedir um access_token novo."""
    path = "/api/v2/auth/access_token/get"
    timestamp = int(time.time())
    sign = _generate_sign(path, timestamp)

    url = f"{API_HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    body = {
        "refresh_token": tokens["refresh_token"],
        "partner_id": PARTNER_ID,
        "shop_id": tokens["shop_id"],
    }

    response = requests.post(url, json=body)
    result = response.json()

    if result.get("error"):
        raise Exception(f"Falha ao renovar token: {result}")

    # Monta o novo registro de tokens, já com o timestamp de quando foi obtido
    new_tokens = {
        "shop_id": tokens["shop_id"],
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "expire_in": result["expire_in"],
        "obtained_at": int(time.time()),
    }
    _save_tokens(new_tokens)
    print("Token renovado com sucesso.")
    return new_tokens


def get_valid_access_token() -> tuple[str, int]:
    """
    Função principal que os scripts de extração vão usar.
    Retorna (access_token, shop_id) sempre válidos — renovando
    automaticamente se necessário.
    """
    tokens = _load_tokens()

    if _is_expired(tokens):
        print("Token expirado ou perto de expirar, renovando...")
        tokens = _refresh_access_token(tokens)

    return tokens["access_token"], tokens["shop_id"]


if __name__ == "__main__":
    # Teste manual: mostra se o token atual está válido ou se acabou de renovar
    access_token, shop_id = get_valid_access_token()
    print(f"Token válido em uso (shop_id={shop_id}): {access_token[:15]}...")