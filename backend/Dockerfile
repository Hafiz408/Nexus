FROM python:3.11-slim

WORKDIR /app

# Copy dependencies first — Docker layer cache skips pip install on code-only changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --reload is appropriate for local dev; remove for production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
