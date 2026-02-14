FROM python:3.9-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.9-slim

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin/gunicorn /usr/local/bin/gunicorn

COPY . .

# Create data directories
RUN mkdir -p /data/db /data/backups

# Ensure PYTHONPATH includes the working directory
ENV PYTHONPATH=/app

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "300", "--graceful-timeout", "30", "wsgi:app"]
