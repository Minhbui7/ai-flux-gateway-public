FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unixodbc \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -o /tmp/ms.deb \
    && dpkg -i /tmp/ms.deb && rm /tmp/ms.deb \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY services/control-plane ./services/control-plane
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home aiflux
COPY gateway/catalog ./gateway/catalog
USER aiflux
EXPOSE 8000
CMD ["uvicorn", "aiflux.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
