FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/app.py ./app.py

EXPOSE 8085

CMD ["gunicorn", \
     "--bind", "0.0.0.0:8085", \
     "--workers", "1", \
     "--threads", "4", \
     "--access-logfile", "-", \
     "app:app"]
