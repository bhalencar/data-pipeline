import hashlib
import hmac
import time
import os
from dotenv import load_dotenv

# Carrega as variáveis do .env (partner_id, partner_key)
load_dotenv()

# .strip() remove espaços/quebras de linha invisíveis que às vezes
# entram sem querer ao copiar e colar valores
PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "").strip())
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()

# Host de PRODUÇÃO da Shopee (Go-Live aprovado em 29/07/2026)
HOST = "https://partner.shopeemobile.com"


def generate_sign(path: str, timestamp: int) -> str:
    """
    Gera a assinatura HMAC-SHA256 exigida pela Shopee.
    A 'base_string' (texto que vira a assinatura) para chamadas
    públicas é: partner_id + caminho_da_api + timestamp
    """
    base_string = f"{PARTNER_ID}{path}{timestamp}"
    sign = hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return sign


def get_auth_url(redirect_url: str) -> str:
    """
    Monta a URL de autorização da loja. Ao acessar essa URL no navegador
    e logar com uma conta de loja Sandbox, a Shopee autoriza o app e
    redireciona de volta com um 'code' e o 'shop_id' na URL.
    """
    path = "/api/v2/shop/auth_partner"
    timestamp = int(time.time())
    sign = generate_sign(path, timestamp)

    url = (
        f"{HOST}{path}"
        f"?partner_id={PARTNER_ID}"
        f"&timestamp={timestamp}"
        f"&sign={sign}"
        f"&redirect={redirect_url}"
    )
    return url


if __name__ == "__main__":
    redirect = "https://example.com"  # precisa bater com o domínio cadastrado no app
    url = get_auth_url(redirect)
    print("Acesse esta URL no navegador para autorizar a loja Sandbox:\n")
    print(url)