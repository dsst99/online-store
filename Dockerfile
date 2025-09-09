FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Системные зависимости для psycopg2/Pillow/netcat и redis-cli
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libjpeg62-turbo-dev \
        zlib1g-dev \
        netcat-openbsd \
        redis-tools \
        curl \
        ca-certificates \
        gnupg2 \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python-зависимости
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Делаем entrypoint.sh исполняемым внутри образа
RUN chmod +x /app/entrypoint.sh

# Используем entrypoint для миграций и запуска сервера
ENTRYPOINT ["/app/entrypoint.sh"]
CMD []
