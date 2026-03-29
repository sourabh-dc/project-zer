FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/orders-requirements.txt
RUN pip install --no-cache-dir -r /tmp/orders-requirements.txt

COPY . /app

EXPOSE 80

CMD ["uvicorn", "orders_service.main:app", "--host", "0.0.0.0", "--port", "80"]

