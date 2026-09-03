"""
Orquestrador da versao em nuvem (Cloud Run Job).

Diferencas em relacao ao run_pipeline.py local:
- Sem caminhos absolutos: usa o diretorio de trabalho do container
- Sem arquivo de log: Cloud Run captura o stdout automaticamente
- Carrega no BigQuery em vez do Postgres
- dbt roda com --target bigquery
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = PROJECT_ROOT / "dbt"


def log(message: str) -> None:
    # Cloud Run coleta o stdout e joga no Cloud Logging, entao basta printar.
    # flush=True garante que a linha aparece na hora, e nao so no fim do job.
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp} UTC] {message}", flush=True)


def run_step(description: str, command: list, cwd: Path = PROJECT_ROOT) -> None:
    log(f"Iniciando: {description}")
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)

    if result.stdout:
        print(result.stdout, flush=True)

    if result.returncode != 0:
        log(f"ERRO em '{description}':\n{result.stderr}")
        raise RuntimeError(f"Falha na etapa: {description}")

    log(f"Concluido: {description}")


if __name__ == "__main__":
    log("===== Inicio do pipeline (nuvem) =====")
    try:
        run_step(
            "Extracao de pedidos (Shopee)",
            [sys.executable, "extraction/shopee/get_orders.py"],
        )
        run_step(
            "Carga para o BigQuery (bronze)",
            [sys.executable, "extraction/shopee/load_to_bigquery.py"],
        )
        # Anuncios entram depois dos pedidos e antes do dbt. A ordem importa:
        # falha de etapa interrompe a rodada inteira, entao o dado principal
        # (pedido) e carregado primeiro. Se a API de Ads cair, o pedido do dia
        # ja esta no bronze -- so o dbt e que nao roda.
        run_step(
            "Extracao de anuncios (Shopee Ads)",
            [sys.executable, "extraction/shopee/get_ads.py"],
        )
        run_step(
            "Carga de anuncios para o BigQuery (bronze)",
            [sys.executable, "extraction/shopee/load_ads_to_bigquery.py"],
        )
        run_step(
            "Transformacao + testes (dbt build)",
            ["dbt", "build", "--target", "bigquery_cloud"],
            cwd=DBT_DIR,
        )
        log("===== Pipeline concluido com sucesso =====")
    except Exception as e:
        log(f"===== Pipeline FALHOU: {e} =====")
        sys.exit(1)