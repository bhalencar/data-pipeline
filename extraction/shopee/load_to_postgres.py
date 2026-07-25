import os
import json
import glob
import psycopg2
from dotenv import load_dotenv

# Carrega as credenciais do Postgres (arquivo .env dentro de docker/)
load_dotenv("docker/.env")

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}


def load_order_list(conn, filepath: str, extraction_date: str):
    """Carrega um arquivo de get_order_list.json para bronze.get_order_list"""
    with open(filepath) as f:
        orders = json.load(f)

    with conn.cursor() as cur:
        for order in orders:
            cur.execute(
                """
                INSERT INTO bronze.get_order_list (order_sn, raw_data, extraction_date)
                VALUES (%s, %s, %s)
                """,
                (order["order_sn"], json.dumps(order), extraction_date),
            )
    conn.commit()
    print(f"{len(orders)} linhas carregadas em bronze.get_order_list ({extraction_date})")


def load_order_detail(conn, filepath: str, extraction_date: str):
    """Carrega um arquivo de get_order_detail.json para bronze.get_order_detail"""
    with open(filepath) as f:
        orders = json.load(f)

    with conn.cursor() as cur:
        for order in orders:
            cur.execute(
                """
                INSERT INTO bronze.get_order_detail (order_sn, raw_data, extraction_date)
                VALUES (%s, %s, %s)
                """,
                (order["order_sn"], json.dumps(order), extraction_date),
            )
    conn.commit()
    print(f"{len(orders)} linhas carregadas em bronze.get_order_detail ({extraction_date})")


if __name__ == "__main__":
    conn = psycopg2.connect(**DB_CONFIG)

    # Percorre todos os arquivos já extraídos em data/bronze/
    for filepath in glob.glob("data/bronze/get_order_list/*.json"):
        extraction_date = os.path.basename(filepath).replace(".json", "")
        load_order_list(conn, filepath, extraction_date)

    for filepath in glob.glob("data/bronze/get_order_detail/*.json"):
        extraction_date = os.path.basename(filepath).replace(".json", "")
        load_order_detail(conn, filepath, extraction_date)

    conn.close()
    print("Carga concluída.")