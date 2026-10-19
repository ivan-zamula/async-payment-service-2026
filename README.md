# Сервис обработки платежей

Сервис платежей на FastAPI и PostgreSQL. Подключены БД и миграции;
маршруты создания и получения платежей пока возвращают `501`.

## Запуск

Нужны Python 3.11+ и Docker Compose v2+ с командой `docker-compose`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Укажите свой `API_KEY` в `.env` и загрузите переменные:

```bash
set -a
source .env
set +a
```

```bash
docker-compose up -d --wait postgres
alembic upgrade head
uvicorn payment_service.app:create_app --factory
```

Swagger: <http://127.0.0.1:8000/docs>. Подключение к БД задается в `.env`
через `DATABASE_URL`.

## Тесты

```bash
pytest payment_service/tests -q
```

Для интеграционных тестов используйте отдельную БД `payments_test`.
Базу создайте заранее, затем примените миграции и запустите тесты:

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://payments:payments@127.0.0.1:5432/payments_test'
DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head
pytest payment_service/tests -q
```

Без тестовых подключений интеграционные проверки пропускаются.
