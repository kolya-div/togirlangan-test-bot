# ==================== STAGE 1: Build ====================
FROM python:3.13-slim AS builder

WORKDIR /app

# Tizim paketlari
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ==================== STAGE 2: Runtime ====================
FROM python:3.13-slim

WORKDIR /app

# Tizim paketlari (runtime uchun)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python packagelarni ko'chirish
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Loyiha fayllari
COPY . .

# Papkalarni yaratish
RUN mkdir -p data/audios data/uploads data/exports

# Port
EXPOSE 8000

# Ishga tushirish
CMD ["python", "run.py"]