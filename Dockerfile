FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 payments

COPY alembic.ini .
COPY migrations ./migrations
COPY payment_service ./payment_service

USER payments
EXPOSE 8000

CMD ["uvicorn", "payment_service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
