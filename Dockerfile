FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md config.json ./
COPY app ./app

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["personal-memory", "--config", "/app/config.json", "web", "--host", "0.0.0.0", "--port", "8000"]
