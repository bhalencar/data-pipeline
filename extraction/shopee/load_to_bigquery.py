"""
Carrega os JSONs brutos da camada bronze no BigQuery.

Le os mesmos arquivos que o load_to_postgres.py ja processou (pasta loaded/),
permitindo popular o BigQuery sem depender do Postgres.

Uso:
    python extraction/shopee/load_to_bigquery.py            # carga completa
    python extraction/shopee/load_to_bigquery.py --truncate # apaga antes
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT_ID = "cp-pipeline-503623"
DATASET = "bronze"
LOCATION = "southamerica-east1"
KEYFILE = Path.home() / ".gcp-keys" / "dbt-bigquery-sa-key.json"

BRONZE_DIR = Path(__file__).resolve().parents[2] / "data" / "bronze"
TABELAS = ["get_order_list", "get_order_detail", "get_escrow_detail"]

# raw_data vai como STRING: o BigQuery nao tem JSONB, e a extracao e feita
# com JSON_VALUE() nos modelos silver.
SCHEMA = [
    bigquery.SchemaField("order_sn", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("raw_data", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("extraction_date", "DATE"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]


def get_client() -> bigquery.Client:
    creds = service_account.Credentials.from_service_account_file(str(KEYFILE))
    return bigquery.Client(project=PROJECT_ID, credentials=creds, location=LOCATION)


def garantir_tabela(client: bigquery.Client, nome: str) -> str:
    table_id = f"{PROJECT_ID}.{DATASET}.{nome}"
    try:
        client.get_table(table_id)
    except Exception:
        tabela = bigquery.Table(table_id, schema=SCHEMA)
        # Particionar por data de extracao mantem as queries baratas conforme
        # o historico cresce: o BigQuery so le as particoes filtradas.
        tabela.time_partitioning = bigquery.TimePartitioning(field="extraction_date")
        client.create_table(tabela)
        print(f"Tabela criada: {table_id}")
    return table_id


def coletar_arquivos(nome_tabela: str) -> list[Path]:
    """Pega os JSONs tanto da pasta principal quanto da subpasta loaded/."""
    pasta = BRONZE_DIR / nome_tabela
    if not pasta.exists():
        return []
    arquivos = sorted(pasta.glob("*.json"))
    loaded = pasta / "loaded"
    if loaded.exists():
        arquivos += sorted(loaded.glob("*.json"))
    return arquivos


def montar_linhas(arquivos: list[Path]) -> list[dict]:
    linhas = []
    agora = datetime.now(timezone.utc).isoformat()

    for arquivo in arquivos:
        # O nome do arquivo e a data da janela de extracao (ex: 2026-06-15.json)
        try:
            extraction_date = datetime.strptime(arquivo.stem, "%Y-%m-%d").date().isoformat()
        except ValueError:
            extraction_date = None

        with open(arquivo) as f:
            conteudo = json.load(f)

        if not isinstance(conteudo, list):
            conteudo = [conteudo]

        for registro in conteudo:
            order_sn = registro.get("order_sn")
            if not order_sn:
                continue
            linhas.append({
                "order_sn": order_sn,
                "raw_data": json.dumps(registro, ensure_ascii=False),
                "extraction_date": extraction_date,
                "loaded_at": agora,
            })

    return linhas


def main() -> None:
    truncar = "--truncate" in sys.argv
    client = get_client()

    for nome in TABELAS:
        table_id = garantir_tabela(client, nome)
        arquivos = coletar_arquivos(nome)

        if not arquivos:
            print(f"{nome}: nenhum arquivo encontrado, pulando.")
            continue

        linhas = montar_linhas(arquivos)
        if not linhas:
            print(f"{nome}: {len(arquivos)} arquivo(s), 0 registros.")
            continue

        config = bigquery.LoadJobConfig(
            schema=SCHEMA,
            write_disposition=(
                bigquery.WriteDisposition.WRITE_TRUNCATE if truncar
                else bigquery.WriteDisposition.WRITE_APPEND
            ),
        )
        job = client.load_table_from_json(linhas, table_id, job_config=config)
        job.result()

        total = client.get_table(table_id).num_rows
        print(f"{nome}: {len(linhas)} linha(s) carregada(s). Total na tabela: {total}")

    print("Carga concluida.")


if __name__ == "__main__":
    main()