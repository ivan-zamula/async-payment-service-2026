# Сервис обработки платежей

Сервис создает и хранит платежи в PostgreSQL, отправляет события в RabbitMQ.
Consumer еще не подключен, платежи остаются в статусе `pending`.

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
docker-compose up -d --wait postgres rabbitmq
alembic upgrade head
uvicorn payment_service.app:create_app --factory
```

В другом терминале активируйте `.venv`, загрузите `.env` теми же командами
и запустите публикатор:

```bash
python -m payment_service.outbox
```

Swagger: <http://127.0.0.1:8000/docs>. Подключение к БД задается в `.env`
через `DATABASE_URL`. Для RabbitMQ используется `RABBITMQ_URL`.

## API

Для запросов нужен заголовок `X-API-Key`.

Создание платежа:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/payments \
  -H "X-API-Key: $API_KEY" \
  -H 'Idempotency-Key: order-42' \
  -H 'Content-Type: application/json' \
  -d '{"amount":"123.45","currency":"RUB","description":"Order 42","metadata":{"order_id":42},"webhook_url":"https://example.com/hook"}'
```

Ответ: `202 Accepted` с полями `payment_id`, `status` и `created_at`.
Повтор с тем же `Idempotency-Key` и данными вернет существующий платеж.
Если данные отличаются, сервис вернет `409`.

Получение платежа (замените UUID на `payment_id` из ответа):

```bash
curl -H "X-API-Key: $API_KEY" \
  http://127.0.0.1:8000/api/v1/payments/00000000-0000-0000-0000-000000000001
```

Если платежа нет, сервис вернет `404`. Без правильного API-ключа вернет `401`.

## Публикация outbox

Платеж и событие сохраняются одной транзакцией. Публикатор читает
события из outbox и отправляет их в `payments.new`. После подтверждения
RabbitMQ отмечает событие отправленным. При ошибке повторяет отправку.
Сообщения могут доставляться повторно.

## Тесты

```bash
pytest payment_service/tests -q
```

Для интеграционных тестов используйте отдельную БД `payments_test` и тестовый RabbitMQ.
Базу создайте заранее, затем примените миграции и запустите тесты:

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://payments:payments@127.0.0.1:5432/payments_test'
export TEST_RABBITMQ_URL='amqp://payments:payments@127.0.0.1:5672/'
DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head
pytest payment_service/tests -q
```

Без тестовых подключений интеграционные проверки пропускаются.
