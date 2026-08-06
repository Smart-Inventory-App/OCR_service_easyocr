"""Servicio de motor OCR — EasyOCR.

El otro motor de la comparativa. Vive en su propio repositorio porque arrastra
PyTorch: ~2 GB de imagen y ~1,3 GB de memoria en ejecución. Tenerlo separado
permite levantar el coordinador y el motor liviano sin pagar ese costo, y
encenderlo sólo cuando se lo quiere usar o comparar.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.routes import router
from app import engine

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not engine.is_available():
        logger.error("`easyocr` no está instalado: /engine/run va a responder 503")
    else:
        if settings.PRELOAD_MODEL:
            # Cargarlo acá y no en la primera petición: son ~6 s que, si no, los
            # paga el primer usuario.
            engine.load()
        logger.info(
            "Motor EasyOCR %s listo (ancho máximo %d px)", engine.version(), settings.MAX_WIDTH
        )

    yield


app = FastAPI(
    title="Smart Inventory — Motor OCR EasyOCR",
    description=(
        "Ejecuta EasyOCR sobre una imagen y devuelve las palabras reconocidas con "
        "su caja y su confianza. Mismo contrato que el servicio de Tesseract: la "
        "interpretación del resultado es responsabilidad de `ocr_service`."
    ),
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.include_router(router)
