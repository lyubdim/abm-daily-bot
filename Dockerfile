FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

RUN python -m pip install --no-cache-dir .

USER 10001:10001

CMD ["sh", "-c", "alembic upgrade head && exec abm-bot"]

