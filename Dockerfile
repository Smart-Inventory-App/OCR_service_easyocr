FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch se instala desde el índice CPU: la rueda por defecto arrastra CUDA y
# agrega ~2 GB inútiles en un despliegue sin GPU.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Los modelos se descargan una sola vez, en build: así el contenedor arranca sin
# depender de la red y la primera petición no paga la descarga.
RUN python -c "import easyocr; easyocr.Reader(['es'], gpu=False, verbose=False)"

COPY . .

EXPOSE 8006

# `HOST` y `PORT` salen del entorno para no tener que rearmar la imagen al
# desplegar. En Railway `PORT` lo inyecta la plataforma; `HOST` sólo hay que
# tocarlo si el servicio tiene que escuchar en IPv6 (`::`) para la red privada.
CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8006}"]
