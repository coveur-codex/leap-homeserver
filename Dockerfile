FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LEAP_DATA_DIR=/data
WORKDIR /app
RUN useradd --system --uid 10001 --create-home leap
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data/database /data/cache /data/images /data/logs /data/distribution && chown -R leap:leap /data /app
USER leap
EXPOSE 8080
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080 --ws-max-size 16384 --ws-ping-interval 60 --ws-ping-timeout 10"]
