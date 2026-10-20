# Сервис обработки платежей

Сервис принимает запросы на оплату, обрабатывает их через эмулятор
платежного шлюза и уведомляет клиента о результате через webhook.

## Запуск

Нужны Docker и Docker Compose v2+ с командой `docker-compose`.

```bash
cp .env.example .env
```

Укажите свой `API_KEY` в `.env`, затем запустите сервис:

```bash
docker-compose up -d --build --wait --wait-timeout 120
```

API: <http://127.0.0.1:8000>, Swagger: <http://127.0.0.1:8000/docs>.
Порты можно изменить в `.env`.

Compose запускает PostgreSQL, RabbitMQ, API, публикатор и consumer.
Миграции применяются автоматически перед запуском приложения.

Логи и остановка:

```bash
docker-compose logs -f api outbox consumer
docker-compose down
```

Данные сохраняются в томах. `docker-compose down --volumes` удаляет их.

## API

Для запросов нужен заголовок `X-API-Key`.

Перед примерами загрузите ключ из `.env` в текущий терминал:

```bash
set -a
source .env
set +a
```

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

## Как работает обработка

1. API сохраняет платеж и событие outbox одной транзакцией.
2. Публикатор отправляет событие в `payments.new` и отмечает отправку после подтверждения RabbitMQ.
3. Consumer эмулирует платежный шлюз: от 2 до 5 секунд, 90% успешных платежей и 10% отказов.
4. Сохраняет результат в БД и отправляет его POST-запросом на `webhook_url`.
5. При технической ошибке делает до трех попыток с паузами 2 и 4 секунды. После третьей ошибки отправляет сообщение в `payments.dlq`.

При недоступности RabbitMQ публикатор повторяет отправку. Сообщения могут
приходить повторно; завершенный платеж не обрабатывается заново.

Пример webhook:

```json
{"payment_id":"00000000-0000-0000-0000-000000000001","status":"succeeded","amount":"123.45","currency":"RUB","processed_at":"2026-10-20T12:30:00"}
```

Вместо `https://example.com/hook` укажите адрес, доступный из consumer.
Webhook может прийти повторно. Для защиты от дублей получатель может
использовать заголовок `Idempotency-Key`, содержащий ID платежа.

## Тесты

Нужен Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest payment_service/tests -q
```

Для интеграционных тестов используйте отдельную БД `payments_test` и тестовый RabbitMQ.
Базу создайте заранее, затем примените миграции и запустите тесты:

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://payments:payments@127.0.0.1:5432/payments_test'
export TEST_RABBITMQ_URL='amqp://payments:payments@127.0.0.1:5672/'
DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head
python -m pytest payment_service/tests -q
```

Без тестовых подключений интеграционные проверки пропускаются.
