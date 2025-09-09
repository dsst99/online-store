#!/bin/bash
set -e

# Ждем Postgres
until python -c "import psycopg2; psycopg2.connect(
    dbname='${POSTGRES_DB:-onlinestore}',
    user='${POSTGRES_USER:-onlinestore}',
    password='${POSTGRES_PASSWORD:-onlinestore}',
    host='db')"; do
  echo "Waiting for Postgres..."
  sleep 2
done

echo "Postgres is ready, running migrations..."
python manage.py migrate

echo "Starting Django server..."
exec python manage.py runserver 0.0.0.0:8000
