"""
Carrega os JSONs de Ads da camada bronze no BigQuery.

POR QUE UM SCRIPT SEPARADO do load_to_bigquery.py, e nao um parametro nele:

O loader de pedidos tem `order_sn` como coluna REQUIRED e descarta em silencio
qualquer registro sem ela. Dado de Ads nao tem `order_sn` -- a chave e a data --
entao ele nao passa por la de jeito nenhum.

Restava generalizar o loader existente ou escrever este. Generalizar mexeria no
caminho que carrega pedido todo dia desde julho, para economizar umas 40 linhas.
Nao vale: o risco fica no que ja funciona e o ganho e cosmetico. Os dois
compartilham o formato (raw_data como STRING, particao por extraction_date,
APPEND com desempate por loaded_at no silver), que e o que realmente importa.

Uso:
    python extraction/shopee/load_ads_to_bigquery.py
    python extraction/shopee/load_ads_to_bigquery.py --truncate
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

# chave_natural e o que identifica a linha dentro do arquivo. Diferente do
# loader de pedidos, aqui ela nao e sempre uma coluna so: campanha precisa de
# campanha + dia, e setting nao tem data nenhuma.
TABELAS = {
    "get_ads_shop_daily":      ["date_iso"],
    "get_ads_campaign_daily":  ["campaign_id", "date_iso"],
    "get_ads_campaign_setting": ["campaign_id"],
}

# raw_data como STRING pelo mesmo motivo do loader de pedidos: o BigQuery nao
# tem JSONB e a extracao acontece com JSON_VALUE() no silver.
#
# E aqui esta a razao de NAO deixar o BigQuery inferir schema: na exploracao de
# 02/09 o metrics_list veio com TODOS os numericos como int -- inclusive ctr,
# expense e cpc -- porque a amostra caiu num dia zerado, e 0 e int em JSON.
# Schema inferido dali faria `expense` virar INTEGER e truncar centavo: 13.66
# viraria 13. Guardando tudo como texto, o cast fica no silver, explicito.
SCHEMA = [
    bigquery.SchemaField("chave_natural", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("raw_data", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("extraction_date", "DATE"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]


def get_client() -> bigquery.Client:
    # No Cloud Run a credencial vem da service account do proprio job.
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
        tabela.time_partitioning = bigquery.TimePartitioning(field="extraction_date")
        client.create_table(tabela)
        print(f"Tabela criada: {table_id}")
    return table_id


def montar_linhas(arquivos: list, campos_chave: list) -> list:
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
            partes = [str(registro.get(c)) for c in campos_chave]

            # Registro sem chave completa e descartado, mas com aviso. O loader
            # de pedidos descarta calado, e isso ja escondeu problema antes.
            if any(p in ("None", "") for p in partes):
                print(f"  aviso: registro sem {campos_chave} em {arquivo.name}, ignorado.")
                continue

            linhas.append({
                "chave_natural": "|".join(partes),
                "raw_data": json.dumps(registro, ensure_ascii=False),
                "extraction_date": extraction_date,
                "loaded_at": agora,
            })

    return linhas


def main() -> None:
    truncar = "--truncate" in sys.argv
    client = get_client()

    for nome, campos_chave in TABELAS.items():
        pasta = BRONZE_DIR / nome
        arquivos = sorted(pasta.glob("*.json")) if pasta.exists() else []

        if not arquivos:
            print(f"{nome}: nenhum arquivo encontrado, pulando.")
            continue

        table_id = garantir_tabela(client, nome)
        linhas = montar_linhas(arquivos, campos_chave)

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
        client.load_table_from_json(linhas, table_id, job_config=config).result()

        total = client.get_table(table_id).num_rows
        print(f"{nome}: {len(linhas)} linha(s) carregada(s). Total na tabela: {total}")

    print("Carga de Ads concluida.")


if __name__ == "__main__":
    main()
