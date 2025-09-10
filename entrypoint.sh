#!/bin/bash
set -e  # Прерывать выполнение при любой ошибке

echo "Starting entrypoint..."

# --- Ждем Postgres ---
echo "Waiting for Postgres..."
until python - <<EOF
import psycopg2
import sys
try:
    psycopg2.connect(
        dbname='${POSTGRES_DB:-onlinestore}',
        user='${POSTGRES_USER:-onlinestore}',
        password='${POSTGRES_PASSWORD:-onlinestore}',
        host='db'
    )
except psycopg2.OperationalError:
    sys.exit(1)
EOF
do
    echo "Waiting for Postgres..."
    sleep 2
done
echo "Postgres is ready"

# --- Ждем Redis ---
echo "Waiting for Redis..."
until redis-cli -h redis ping | grep PONG; do
    echo "Waiting for Redis..."
    sleep 2
done
echo "Redis is ready"

# --- Ждем Memcached ---
echo "Waiting for Memcached..."
until echo "stats" | nc -w 1 memcached 11211 | grep -q "version"; do
    echo "Waiting for Memcached..."
    sleep 2
done
echo "Memcached is ready"

# --- Создаём миграции для всех приложений ---
echo "Creating migrations for all apps..."
python manage.py makemigrations --noinput || echo "No new migrations to create"

# --- Применяем все миграции ---
echo "Applying migrations..."
python manage.py migrate --noinput

# --- Запускаем сервер ---
echo "Starting Django server..."
exec python manage.py runserver 0.0.0.0:8000
