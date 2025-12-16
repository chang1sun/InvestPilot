FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure PYTHONPATH includes the working directory
ENV PYTHONPATH=/app

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "--timeout", "300", "--graceful-timeout", "30", "wsgi:app"]

