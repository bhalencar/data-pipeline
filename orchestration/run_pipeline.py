import subprocess
import sys
from datetime import datetime

# Caminho absoluto da raiz do projeto — obrigatório aqui, porque o launchd
# não roda a partir do terminal, não "sabe" qual é a pasta atual
PROJECT_ROOT = "/Users/brunoalencar/Documents/Casa e Patas/data-pipeline"
VENV_PYTHON = f"{PROJECT_ROOT}/venv/bin/python3.12"
VENV_DBT = f"{PROJECT_ROOT}/venv/bin/dbt"
LOG_FILE = f"{PROJECT_ROOT}/orchestration/pipeline.log"


def log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_step(description: str, command: list, cwd: str = PROJECT_ROOT):
    log(f"Iniciando: {description}")
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"ERRO em '{description}':\n{result.stderr}")
        raise RuntimeError(f"Falha na etapa: {description}")
    log(f"Concluído: {description}")
    return result


if __name__ == "__main__":
    log("===== Início do pipeline diário =====")
    try:
        run_step("Extração de pedidos (Shopee)", [VENV_PYTHON, "extraction/shopee/get_orders.py"])
        run_step("Carga para o Postgres (bronze)", [VENV_PYTHON, "extraction/shopee/load_to_postgres.py"])
        run_step("Transformação + testes (dbt build)", [VENV_DBT, "build"], cwd=f"{PROJECT_ROOT}/dbt")
        log("===== Pipeline concluído com sucesso =====")
    except Exception as e:
        log(f"===== Pipeline FALHOU: {e} =====")
        sys.exit(1)