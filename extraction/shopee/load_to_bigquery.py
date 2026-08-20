"""
Carrega os JSONs brutos da camada bronze no BigQuery.

Uso:
    python extraction/shopee/load_to_bigquery.py                  # carga normal
    python extraction/shopee/load_to_bigquery.py --truncate       # apaga antes
    python extraction/shopee/load_to_bigquery.py --incluir-loaded # inclui data/bronze/*/loaded/

Sobre --incluir-loaded: a pasta loaded/ guarda os JSONs que o load_to_postgres.py
ja tinha processado, e existia para popular o BigQuery na migracao de 2026 sem
depender do Postgres. Essa migracao terminou.

Ler loaded/ por padrao virou perigoso. A carga e APPEND e o silver desempata por
loaded_at desc, entao recarregar um snapshot antigo faz o dado velho ganhar do
novo: o pedido volta para o status que tinha em julho, com um loaded_at de hoje.
Por isso a pasta so entra quando pedida explicitamente.
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
    # No Cloud Run nao existe arquivo de chave: a autenticacao vem da
    # identidade da propria service account do job (credencial padrao).
    # Localmente, usa o keyfile se ele existir.
    if KEYFILE.exists():
        creds = service_account.Credentials.from_service_account_file(str(KEYFILE))
        return bigquery.Client(project=PROJECT_ID, credentials=creds, location=LOCATION)
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


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


def coletar_arquivos(nome_tabela: str, incluir_loaded: bool = False) -> list[Path]:
    """Pega os JSONs da pasta principal. Ver o docstring do modulo sobre loaded/."""
    pasta = BRONZE_DIR / nome_tabela
    if not pasta.exists():
        return []
    arquivos = sorted(pasta.glob("*.json"))
    if incluir_loaded:
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
    incluir_loaded = "--incluir-loaded" in sys.argv
    client = get_client()

    if incluir_loaded:
        print("Atencao: incluindo data/bronze/*/loaded/ — snapshots antigos podem "
              "sobrescrever dado mais novo no desempate por loaded_at.")

    for nome in TABELAS:
        table_id = garantir_tabela(client, nome)
        arquivos = coletar_arquivos(nome, incluir_loaded=incluir_loaded)

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