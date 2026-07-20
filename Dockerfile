FROM python:3.12-slim

# Logs sin buffer: se ven en tiempo real con `docker compose logs -f`
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py ushahidi.py config.py ./

CMD ["python", "bot.py"]
