# Stage 1: Build the React Frontend
FROM node:20 AS frontend-builder
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

# Stage 2: Build the Python Backend
FROM python:3.12-slim
WORKDIR /app

# Copy the built frontend from Stage 1
COPY --from=frontend-builder /app/dashboard/dist /app/dashboard/dist

# Install python dependencies
COPY pyproject.toml .
# Assume dependencies are standard if using pyproject or setup.py
COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8080

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRA_EVENT_STORE_TYPE=sqlite \
    TRA_LOG_LEVEL=INFO \
    TRA_DASHBOARD_TYPE=fastapi \
    TRA_DASHBOARD=0

# Use the standard Railway port if needed (Railway injects PORT env variable)
# FastAPI will bind to PORT in src/main.py

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + __import__('os').environ.get('PORT', '8080') + '/health')"

CMD ["python", "-m", "src.main"]