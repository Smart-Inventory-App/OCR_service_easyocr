"""Ejecución de EasyOCR.

La propuesta lo describe como "buena relación entre facilidad de uso y
precisión", con mayor consumo de memoria y tiempo que Tesseract en CPU. Medido
sobre fotos reales de producto, esa descripción se cumple con creces: lee
envases curvos, brillantes y con tipografías de fantasía donde Tesseract no
levanta nada, y paga por ello segundos de latencia y más de un giga de RAM.

Como el de Tesseract, este módulo hace una sola cosa: correr el motor y devolver
las palabras con su caja y su confianza.
"""

import logging
import threading
import time

import numpy as np

from app.core.config import settings
from app.prepare import run as prepare
from app.schemas import EngineResponse, Transform, Word

logger = logging.getLogger(__name__)

NAME = "easyocr"

# EasyOCR usa códigos ISO-639-1; el resto del sistema habla en códigos de
# Tesseract (`spa`, `eng`).
_LANG_CODES = {"spa": "es", "eng": "en"}

# Alto en píxeles por debajo del cual dos cajas se consideran de la misma línea.
_LINE_TOLERANCE_RATIO = 0.6

_reader = None
_reader_lang: str | None = None
# Cargar el modelo no es reentrante y el servidor atiende en varios threads.
_lock = threading.Lock()


def is_available() -> bool:
    try:
        import easyocr  # noqa: F401
        return True
    except ImportError:
        return False


def version() -> str:
    try:
        import easyocr
        return getattr(easyocr, "__version__", "desconocida")
    except ImportError:
        return "no instalado"


def languages() -> list[str]:
    return sorted(_LANG_CODES)


def load(lang: str | None = None):
    """Carga el modelo (costoso) y lo memoiza. Es idempotente."""
    global _reader, _reader_lang

    code = _LANG_CODES.get(lang or settings.DEFAULT_LANG, lang or "es")

    with _lock:
        if _reader is None or _reader_lang != code:
            import easyocr

            started = time.perf_counter()
            _reader = easyocr.Reader([code], gpu=False, verbose=False)
            _reader_lang = code
            logger.info(
                "Modelo EasyOCR '%s' cargado en %.1f s", code, time.perf_counter() - started
            )

    return _reader


def run(image: np.ndarray, lang: str, layout: str, transform: Transform) -> EngineResponse:
    """Reconoce sobre la imagen en color.

    `layout` se acepta por contrato pero se ignora: EasyOCR detecta las regiones
    de texto por su cuenta y no expone nada equivalente al *page segmentation
    mode* de Tesseract.
    """
    started = time.perf_counter()

    reader = load(lang)
    prepared, scale = prepare(image, transform)

    detections = reader.readtext(prepared)

    words = _assign_lines(
        [
            # Las cajas se devuelven en coordenadas de la imagen recibida, para
            # que el coordinador no sepa del recorte interno.
            _to_word(box, text, confidence, scale)
            for box, text, confidence in detections
            if text.strip()
        ]
    )

    height, width = prepared.shape[:2]

    return EngineResponse(
        engine=NAME,
        text=render_text(words),
        words=words,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        image_width=width,
        image_height=height,
        lang=_LANG_CODES.get(lang, lang),
    )


def render_text(words: list[Word]) -> str:
    grouped: dict[int, list[Word]] = {}
    for word in words:
        if word.text.strip():
            grouped.setdefault(word.line_num, []).append(word)

    return "\n".join(
        " ".join(w.text for w in sorted(line, key=lambda w: w.left))
        for _, line in sorted(grouped.items())
    )


def _to_word(box, text: str, confidence: float, scale: float) -> Word:
    factor = 1 / scale if scale else 1.0
    xs = [int(point[0] * factor) for point in box]
    ys = [int(point[1] * factor) for point in box]

    return Word(
        text=text,
        confidence=min(max(float(confidence), 0.0), 1.0),
        left=min(xs),
        top=min(ys),
        width=max(xs) - min(xs),
        height=max(ys) - min(ys),
    )


def _assign_lines(words: list[Word]) -> list[Word]:
    """EasyOCR no devuelve número de línea: se agrupa por proximidad vertical."""
    if not words:
        return []

    ordered = sorted(words, key=lambda w: (w.top, w.left))
    tolerance = max(1, int(_median_height(ordered) * _LINE_TOLERANCE_RATIO))

    result: list[Word] = []
    line_num = 0
    line_top = ordered[0].top

    for word in ordered:
        if word.top - line_top > tolerance:
            line_num += 1
            line_top = word.top
        result.append(word.model_copy(update={"line_num": line_num}))

    return result


def _median_height(words: list[Word]) -> float:
    heights = sorted(w.height for w in words)
    return heights[len(heights) // 2] or 1.0
