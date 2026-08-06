"""Fixtures compartidas.

Los tests no cargan el modelo de EasyOCR —son ~6 s y 1,3 GB—: se dobla el
`Reader`. Lo que sí se ejercita de verdad es el giro, el acotado de ancho y la
traducción de las detecciones a palabras con línea, que es lo que este servicio
aporta además de invocar al modelo.
"""

import io
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

os.environ.setdefault("DEBUG", "true")

from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as instance:
        yield instance


def render_image(text: str = "LECHE ENTERA", size: tuple[int, int] = (600, 300)) -> bytes:
    """JPEG con texto oscuro sobre fondo claro."""
    image = Image.new("RGB", size, color=(255, 255, 255))
    ImageDraw.Draw(image).text((30, 60), text, fill=(0, 0, 0))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


@pytest.fixture
def image_bytes() -> bytes:
    return render_image()


@pytest.fixture
def gray_image() -> np.ndarray:
    """Escala de grises con una banda oscura, para ejercitar los filtros."""
    image = np.full((200, 600), 240, dtype=np.uint8)
    image[80:120, 50:400] = 30
    return image


@pytest.fixture
def color_image() -> np.ndarray:
    image = np.full((200, 600, 3), 240, dtype=np.uint8)
    image[80:120, 50:400] = (30, 30, 30)
    return image


class FakeReader:
    """Doble del `Reader` de EasyOCR: devuelve detecciones fijas."""

    def __init__(self, detections):
        self.detections = detections
        self.calls: list[np.ndarray] = []

    def readtext(self, image):
        self.calls.append(image)
        return self.detections


def box(left: int, top: int, width: int, height: int):
    """Cuadrilátero en el formato que devuelve EasyOCR (cuatro vértices)."""
    return [
        [left, top],
        [left + width, top],
        [left + width, top + height],
        [left, top + height],
    ]


@pytest.fixture
def fake_reader(monkeypatch):
    def install(detections):
        reader = FakeReader(detections)
        monkeypatch.setattr("app.engine.load", lambda *_args, **_kwargs: reader)
        return reader

    return install
