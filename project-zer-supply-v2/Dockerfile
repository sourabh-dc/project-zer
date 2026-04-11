FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml /app/
COPY src /app/src
COPY alembic.ini /app/
COPY alembic /app/alembic
COPY policy_engine /app/policy_engine

RUN pip install --no-cache-dir .

EXPOSE 8010

CMD ["python", "-m", "supply_v2.run"]
