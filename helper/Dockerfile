# Built from the repo root (see docker-compose.yml) so it can include the provisioner module.
FROM python:3.12-alpine
WORKDIR /app
COPY provision/app.py ./provision.py
COPY helper/app.py ./app.py
ENV CACHE_PATH=/data/cache.json SETTINGS_PATH=/data/settings.json PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "app.py"]
