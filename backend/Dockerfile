FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create app directory and set permissions
RUN useradd -m -r appuser && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

COPY --chown=appuser:appuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"] 