FROM python:3.12-slim

ARG PIP_TRUSTED_HOST=""
ARG PIP_INDEX_URL="https://pypi.org/simple"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos "" ghost

COPY . /app

RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -e ".[gateway]"

RUN mkdir -p /data/state && chown -R ghost:ghost /data /app

USER ghost

EXPOSE 8765 8766

CMD ["ghostchimera", "console", "--host", "0.0.0.0", "--port", "8765", "--http-port", "8766", "--state-dir", "/data/state", "--no-open"]
