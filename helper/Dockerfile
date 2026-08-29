FROM python:3.12-alpine
WORKDIR /app
COPY app.py .
ENV CACHE_PATH=/data/cache.json PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "app.py"]
