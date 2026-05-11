FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" ghost

COPY . /app

RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -e ".[gateway]"

RUN mkdir -p /data/state && chown -R ghost:ghost /data /app

USER ghost

EXPOSE 8765 8766

CMD ["ghostchimera", "console", "--host", "0.0.0.0", "--port", "8765", "--http-port", "8766", "--state-dir", "/data/state", "--no-open"]
