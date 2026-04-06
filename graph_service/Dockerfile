FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared/ /app/shared/
COPY graph_service/ /app/graph_service/

EXPOSE 8015

CMD ["uvicorn", "graph_service.main:app", "--host", "0.0.0.0", "--port", "8015"]
