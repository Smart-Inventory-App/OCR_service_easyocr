"""Preparación geométrica y traducción de la salida de EasyOCR."""

import numpy as np
import pytest

from app import engine, prepare
from app.core.config import settings
from app.schemas import Binarize, Transform
from tests.conftest import box

IMAGE = np.full((200, 600, 3), 240, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Preparación
# ---------------------------------------------------------------------------

def test_decode_returns_colour(image_bytes):
    """EasyOCR trabaja en color: convertir a grises acá lo degradaría."""
    image = prepare.decode(image_bytes)

    assert image.ndim == 3
    assert image.shape[2] == 3


def test_decode_rejects_something_that_is_not_an_image():
    with pytest.raises(prepare.DecodeError):
        prepare.decode(b"esto no es una imagen")


@pytest.mark.parametrize("degrees", [90, 270])
def test_rotate_a_quarter_turn_swaps_the_axes(degrees):
    assert prepare.rotate(IMAGE, degrees).shape[:2] == IMAGE.shape[:2][::-1]


def test_rotate_zero_is_a_no_op():
    assert np.array_equal(prepare.rotate(IMAGE, 0), IMAGE)


def test_bound_width_shrinks_and_reports_the_scale():
    wide = np.full((400, 2000, 3), 240, dtype=np.uint8)

    result, scale = prepare.bound_width(wide, 800)

    assert result.shape[1] == 800
    assert scale == pytest.approx(0.4)


def test_bound_width_leaves_a_small_image_untouched():
    result, scale = prepare.bound_width(IMAGE, 800)

    assert result is IMAGE
    assert scale == 1.0


def test_the_service_ceiling_wins_over_the_requested_width(monkeypatch):
    """El coordinador pide resolución; el techo de memoria del motor manda."""
    monkeypatch.setattr(settings, "MAX_WIDTH", 400)
    wide = np.full((400, 2000, 3), 240, dtype=np.uint8)

    result, _ = prepare.run(wide, Transform(max_width=1600))

    assert result.shape[1] == 400


def test_the_requested_width_wins_when_it_is_smaller(monkeypatch):
    monkeypatch.setattr(settings, "MAX_WIDTH", 1600)
    wide = np.full((400, 2000, 3), 240, dtype=np.uint8)

    result, _ = prepare.run(wide, Transform(max_width=800))

    assert result.shape[1] == 800


def test_the_filters_of_the_contract_are_ignored():
    """Se aceptan por contrato, pero degradan a este motor: no se aplican."""
    spec = Transform(grayscale=True, invert=True, contrast=True, binarize=Binarize.OTSU)

    result, _ = prepare.run(IMAGE, spec)

    assert result.ndim == 3  # sigue en color


# ---------------------------------------------------------------------------
# Traducción de detecciones
# ---------------------------------------------------------------------------

def run(detections, fake_reader, transform: Transform | None = None):
    fake_reader(detections)
    return engine.run(IMAGE, "spa", "block", transform or Transform())


def test_words_carry_text_box_and_confidence(fake_reader):
    result = run([(box(10, 10, 100, 30), "LECHE", 0.93)], fake_reader)

    word = result.words[0]

    assert word.text == "LECHE"
    assert word.confidence == pytest.approx(0.93)
    assert (word.left, word.top, word.width, word.height) == (10, 10, 100, 30)


def test_empty_detections_are_dropped(fake_reader):
    result = run(
        [(box(10, 10, 100, 30), "LECHE", 0.9), (box(0, 0, 5, 5), "   ", 0.4)], fake_reader
    )

    assert len(result.words) == 1


def test_words_on_the_same_height_share_a_line(fake_reader):
    """EasyOCR no numera líneas: se agrupan por proximidad vertical."""
    result = run(
        [
            (box(10, 10, 100, 30), "LECHE", 0.9),
            (box(130, 12, 110, 30), "ENTERA", 0.9),
            (box(10, 90, 60, 28), "1L", 0.9),
        ],
        fake_reader,
    )

    assert result.text == "LECHE ENTERA\n1L"


def test_boxes_come_back_in_the_original_coordinates(fake_reader, monkeypatch):
    """El recorte interno no debe filtrarse al coordinador."""
    monkeypatch.setattr(settings, "MAX_WIDTH", 300)
    wide = np.full((400, 600, 3), 240, dtype=np.uint8)

    fake_reader([(box(50, 50, 100, 20), "LECHE", 0.9)])
    result = engine.run(wide, "spa", "block", Transform(max_width=300))

    # La imagen se redujo a la mitad: la caja se reexpande al doble.
    assert result.words[0].left == 100


def test_confidence_is_clamped(fake_reader):
    result = run([(box(0, 0, 10, 10), "X", 1.4)], fake_reader)

    assert result.words[0].confidence == 1.0


def test_the_response_reports_the_engine_and_the_elapsed_time(fake_reader):
    result = run([(box(0, 0, 10, 10), "X", 0.9)], fake_reader)

    assert result.engine == "easyocr"
    assert result.elapsed_ms >= 0


def test_an_empty_reading_returns_no_words(fake_reader):
    result = run([], fake_reader)

    assert result.words == []
    assert result.text == ""


def test_the_rotation_reaches_the_model(fake_reader):
    reader = fake_reader([(box(0, 0, 10, 10), "X", 0.9)])

    engine.run(IMAGE, "spa", "block", Transform(rotate=90))

    assert reader.calls[0].shape[:2] == IMAGE.shape[:2][::-1]


# ---------------------------------------------------------------------------
# Disponibilidad
# ---------------------------------------------------------------------------

def test_languages_are_reported_with_tesseract_codes():
    """El resto del sistema habla en `spa`/`eng`; la traducción es interna."""
    assert engine.languages() == ["eng", "spa"]
