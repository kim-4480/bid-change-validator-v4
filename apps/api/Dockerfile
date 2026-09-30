# Build context is the repository root (see docker-compose.yml) so the image can
# include the engine package. Dockerfile.dockerignore limits what is sent.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine /opt/engine
RUN pip install --no-cache-dir --no-deps /opt/engine

COPY apps/api/app ./app
COPY apps/api/alembic.ini .
COPY apps/api/alembic ./alembic

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
