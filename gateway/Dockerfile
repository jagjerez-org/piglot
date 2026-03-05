FROM python:3.12-slim

WORKDIR /app

# Install deps
COPY requirements-gateway.txt .
RUN pip install --no-cache-dir -r requirements-gateway.txt

# Copy gateway code
COPY src/gateway/ src/gateway/
COPY gateway/run.py .

# Edge TTS runs on gateway (free)
# API keys come from environment variables

EXPOSE 8080

CMD ["python", "run.py"]
