# Imagem slim: menor e mais rapida de subir que a completa
FROM python:3.12-slim

# Evita .pyc no container e garante log em tempo real no Cloud Logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias primeiro, em camada propria: o Docker so reinstala
# quando o requirements muda, nao a cada alteracao de codigo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codigo da aplicacao
COPY extraction/ ./extraction/
COPY orchestration/ ./orchestration/
COPY dbt/ ./dbt/

# O dbt procura o profiles.yml no diretorio do projeto
ENV DBT_PROFILES_DIR=/app/dbt

CMD ["python", "orchestration/run_pipeline_cloud.py"]
