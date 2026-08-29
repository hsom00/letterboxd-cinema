# Built from the repo root (see docker-compose.dev.yml and .github/workflows/images.yml).
FROM python:3.12-alpine
WORKDIR /app
COPY provision/app.py ./app.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
