FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY orders_service/requirements.txt /tmp/orders-requirements.txt
RUN pip install --no-cache-dir -r /tmp/orders-requirements.txt

COPY . /app

EXPOSE 8008

CMD ["python", "-m", "orders_service.main"]

