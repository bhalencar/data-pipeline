import os
import json
import glob
import shutil
import psycopg2
from dotenv import load_dotenv

load_dotenv("docker/.env")

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}


def load_order_list(conn, filepath: str, extraction_date: str):
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

def load_escrow_detail(conn, filepath: str, extraction_date: str):
    with open(filepath) as f:
        escrows = json.load(f)

    with conn.cursor() as cur:
        for escrow in escrows:
            cur.execute(
                """
                INSERT INTO bronze.get_escrow_detail (order_sn, raw_data, extraction_date)
                VALUES (%s, %s, %s)
                """,
                (escrow["order_sn"], json.dumps(escrow), extraction_date),
            )
    conn.commit()
    print(f"{len(escrows)} linhas carregadas em bronze.get_escrow_detail ({extraction_date})")

def move_to_loaded(filepath: str):
    """Move o arquivo já processado para uma subpasta 'loaded/', evitando
    que ele seja processado de novo nas próximas execuções."""
    folder = os.path.dirname(filepath)
    loaded_folder = os.path.join(folder, "loaded")
    os.makedirs(loaded_folder, exist_ok=True)
    shutil.move(filepath, os.path.join(loaded_folder, os.path.basename(filepath)))


if __name__ == "__main__":
    conn = psycopg2.connect(**DB_CONFIG)

    # glob.glob("*.json") não entra em subpastas, então "loaded/" fica
    # automaticamente de fora — é isso que torna a carga incremental
    for filepath in glob.glob("data/bronze/get_order_list/*.json"):
        extraction_date = os.path.basename(filepath).replace(".json", "")
        load_order_list(conn, filepath, extraction_date)
        move_to_loaded(filepath)

    for filepath in glob.glob("data/bronze/get_order_detail/*.json"):
        extraction_date = os.path.basename(filepath).replace(".json", "")
        load_order_detail(conn, filepath, extraction_date)
        move_to_loaded(filepath)

    for filepath in glob.glob("data/bronze/get_escrow_detail/*.json"):
        extraction_date = os.path.basename(filepath).replace(".json", "")
        load_escrow_detail(conn, filepath, extraction_date)
        move_to_loaded(filepath)

    conn.close()
    print("Carga concluída.")