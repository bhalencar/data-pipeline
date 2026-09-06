"""
Carrega os JSONs de palavras-chave da camada bronze no BigQuery.

Segue o mesmo formato dos outros loaders do projeto (raw_data como STRING,
particao por extraction_date, APPEND com desempate por loaded_at no silver),
com UMA diferenca deliberada, explicada abaixo.

POR QUE A CHAVE NATURAL AQUI E SO RASTREABILIDADE, NAO O GRAO:

O load_ads_to_bigquery.py monta `chave_natural` concatenando campos com "|" e
o silver deduplica por essa string. Funciona la porque os campos sao numericos
e datas.

Aqui um dos campos do grao e a propria PALAVRA -- texto livre, com espaco e
acento ("escada para pet subir na cama", "movel pet"). Concatenar texto livre
numa chave delimitada e fragil: uma palavra que contenha o delimitador quebra
a interpretacao. Improvavel numa busca real, mas evitavel a custo zero.

Entao o silver deduplica pelas TRES COLUNAS de verdade -- item_id, keyword e
data_snapshot -- extraidas do JSON. A `chave_natural` continua existindo
porque o schema do bronze e compartilhado e porque ajuda a rastrear uma linha
especifica na depuracao, mas nao e ela que garante o grao.

Uso:
    python extraction/shopee/load_keywords_to_bigquery.py
    python extraction/shopee/load_keywords_to_bigquery.py --truncate
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
TABELA = "get_keywords"

# raw_data como STRING pelo mesmo motivo dos outros loaders: o BigQuery nao tem
# JSONB e a extracao acontece com JSON_VALUE() no silver. E, como no card #1,
# guardar texto evita que o BigQuery infira INTEGER para um campo que num dia
# de valor zero vem como int e nos outros vem como float.
SCHEMA = [
    bigquery.SchemaField("chave_natural", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("raw_data", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("extraction_date", "DATE"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]


def get_client() -> bigquery.Client:
    if KEYFILE.exists():
        creds = service_account.Credentials.from_service_account_file(str(KEYFILE))
        return bigquery.Client(project=PROJECT_ID, credentials=creds, location=LOCATION)
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


def garantir_tabela(client: bigquery.Client) -> str:
    table_id = f"{PROJECT_ID}.{DATASET}.{TABELA}"
    try:
        client.get_table(table_id)
    except Exception:
        tabela = bigquery.Table(table_id, schema=SCHEMA)
        tabela.time_partitioning = bigquery.TimePartitioning(field="extraction_date")
        client.create_table(tabela)
        print(f"Tabela criada: {table_id}")
    return table_id


def montar_linhas(arquivos: list) -> list:
    linhas = []
    agora = datetime.now(timezone.utc).isoformat()

    for arquivo in arquivos:
        try:
            extraction_date = datetime.strptime(arquivo.stem, "%Y-%m-%d").date().isoformat()
        except ValueError:
            extraction_date = None

        with open(arquivo) as f:
            conteudo = json.load(f)

        if not isinstance(conteudo, list):
            conteudo = [conteudo]

        for registro in conteudo:
            item_id = registro.get("item_id")
            keyword = registro.get("keyword")
            snapshot = registro.get("data_snapshot")

            # Registro sem uma das tres partes do grao e descartado, com aviso.
            # Descartar em silencio ja escondeu problema neste projeto antes.
            if not item_id or not keyword or not snapshot:
                print(f"  aviso: registro incompleto em {arquivo.name} "
                      f"(item_id={item_id!r}, keyword={keyword!r}, "
                      f"data_snapshot={snapshot!r}), ignorado.")
                continue

            linhas.append({
                # Rastreabilidade, nao o grao -- ver o docstring do modulo.
                "chave_natural": f"{item_id}|{snapshot}|{keyword}",
                "raw_data": json.dumps(registro, ensure_ascii=False),
                "extraction_date": extraction_date,
                "loaded_at": agora,
            })

    return linhas


def main() -> None:
    truncar = "--truncate" in sys.argv
    client = get_client()

    pasta = BRONZE_DIR / TABELA
    arquivos = sorted(pasta.glob("*.json")) if pasta.exists() else []

    if not arquivos:
        print(f"{TABELA}: nenhum arquivo encontrado, pulando.")
        print("  (normal em dia que nao e o da coleta semanal)")
        return

    table_id = garantir_tabela(client)
    linhas = montar_linhas(arquivos)

    if not linhas:
        print(f"{TABELA}: {len(arquivos)} arquivo(s), 0 registros.")
        return

    config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition=(
            bigquery.WriteDisposition.WRITE_TRUNCATE if truncar
            else bigquery.WriteDisposition.WRITE_APPEND
        ),
    )
    client.load_table_from_json(linhas, table_id, job_config=config).result()

    total = client.get_table(table_id).num_rows
    print(f"{TABELA}: {len(linhas)} linha(s) carregada(s). Total na tabela: {total}")
    print("Carga de palavras-chave concluida.")


if __name__ == "__main__":
    main()
