# Imagen base oficial de Playwright (Ubuntu 24.04)
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# Configuración de Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalamos FFmpeg y utilidades de fuentes básicas
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Copiamos requerimientos e instalamos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalamos Chromium y sus dependencias de sistema
RUN playwright install chromium --with-deps

# Copiamos el resto del código
COPY . .

# Refrescamos la caché de fuentes para que reconozca tu .ttf
RUN fc-cache -f -v

CMD ["bash"]
