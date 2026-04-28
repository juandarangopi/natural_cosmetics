FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5033

CMD ["gunicorn", "--bind", "0.0.0.0:5033", "--workers", "2", "--timeout", "30", "app:app"]
