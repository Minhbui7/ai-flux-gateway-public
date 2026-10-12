FROM mcr.microsoft.com/azure-functions/python:4.1055.150-0-python3.11
ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /home/site/wwwroot
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unixodbc \
    && . /etc/os-release \
    && curl -fsSL "https://packages.microsoft.com/config/debian/${VERSION_ID}/packages-microsoft-prod.deb" -o /tmp/ms.deb \
    && dpkg -i /tmp/ms.deb && rm /tmp/ms.deb \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY services/control-plane ./services/control-plane
RUN pip install --no-cache-dir .
RUN python -c "import pyodbc; assert 'ODBC Driver 18 for SQL Server' in pyodbc.drivers()"
COPY services/usage-ingestion/handlers.py services/usage-ingestion/runtime_check.py services/usage-ingestion/host.json ./
COPY services/usage-ingestion/ingest_usage ./ingest_usage
COPY services/usage-ingestion/ingestion_ready ./ingestion_ready
COPY gateway/catalog/dev-models.json ./gateway/catalog/dev-models.json
