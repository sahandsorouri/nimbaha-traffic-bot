FROM python:3.12-slim

WORKDIR /app

# Install deps first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY auth.py database.py scraper.py bot.py ./

# data/ volume is mounted at runtime — not baked into the image
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
