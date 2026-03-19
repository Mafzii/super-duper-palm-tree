FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt /app
RUN pip install -r requirements.txt && crawl4ai-setup

COPY . /app

CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:8000", "app:app"]
