FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WECHAT_BOT_DEPLOYMENT_TARGET=web-api \
    WECHAT_BOT_DATA_DIR=/app/data

WORKDIR /app

COPY requirements-container.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-container.txt

COPY . .

EXPOSE 5000

CMD ["python", "run.py", "web", "--host", "0.0.0.0", "--port", "5000"]
