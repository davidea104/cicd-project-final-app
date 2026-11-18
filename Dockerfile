FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.txt

COPY app/ ./app/

RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app
USER app

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    MODO_DEMO=false \
    COOKIE_SEGURA=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:8000", "app:create_app()"]
