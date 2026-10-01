# ==================== STAGE 1: WebApp (React/Vite) ====================
FROM node:20-slim AS webapp

WORKDIR /webapp
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY webapp/ ./
RUN npm run build

# ==================== STAGE 2: Python dependencies ====================
FROM python:3.13-slim AS builder

WORKDIR /app

# Python dependencies (hammasi tayyor wheel — gcc/libpq kerak emas)
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ==================== STAGE 3: Runtime ====================
FROM python:3.13-slim

WORKDIR /app

# Python packagelarni ko'chirish
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# Loyiha fayllari + tayyor WebApp build
COPY . .
COPY --from=webapp /webapp/dist ./webapp/dist

# Ma'lumotlar papkasi (audio, savol rasmlari, arxiv, hisobotlar).
# Railway'da bu yerga Volume ulanadi: Mount path = /app/data
RUN mkdir -p data/audios data/uploads data/exports data/archive data/reports

# Port — Railway PORT o'zgaruvchisini o'zi beradi (run.py uni o'qiydi)
EXPOSE 8000

# Ishga tushirish
CMD ["python", "run.py"]
