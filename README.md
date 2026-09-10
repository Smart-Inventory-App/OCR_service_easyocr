# Motor OCR — EasyOCR

> ## ⚠️ Fuera del Módulo Desde Septiembre de 2026
>
> **Este servicio ya no forma parte del módulo de OCR y no se levanta con él.** El
> coordinador no lo conoce: `ocr_service` habla con Tesseract y con PaddleOCR, y
> ninguno de los dos ni los backends lo mencionan.
>
> **Por qué.** El modo híbrido en producción es `tesseract` → `paddleocr`, así que
> EasyOCR no participaba de ningún camino: medido con `docker stats` durante una
> tanda de carga, se quedaba en **0,1 % de CPU sosteniendo 561 MB de memoria**.
> Ese lugar lo ocupa hoy una segunda réplica de PaddleOCR, que sí es el cuello de
> botella del sistema y con la que el módulo pasó de 1,8 a 3,2 documentos pesados
> por minuto.
>
> **El repositorio queda.** El contrato del motor no cambió, así que sigue siendo
> una implementación válida y comparable: para volver a medirlo alcanza con
> levantarlo y agregarlo a `CONCRETE_ENGINES` y a la configuración del
> coordinador. Los resultados de la comparativa que motivó la decisión están en
> `ocr_service/bench/results/`.

Microservicio que hace **una sola cosa**: correr EasyOCR sobre una imagen y devolver las palabras reconocidas con su caja y su confianza.

Habla **el mismo contrato** que [`ocr_service_tesseract`](../ocr_service_tesseract): es lo que le permite a [`ocr_service`](../ocr_service) tratar a los dos motores igual, compararlos sobre la misma foto y combinarlos en el modo híbrido.

```
ocr_service  ──POST /engine/run──►  este servicio
             ◄── palabras + confianza ──┘
```

---

## Motivo de la Separación

EasyOCR arrastra **PyTorch**: ~2,5 GB de imagen y ~1,3 GB de memoria en ejecución. Mientras vivía dentro del coordinador, ese costo lo pagaba todo el mundo —la API, el worker, los tests, cada redespliegue— aunque la petición terminara resolviéndose con Tesseract en medio segundo.

Separado, el motor caro se enciende sólo cuando se lo quiere usar o comparar, y el resto del sistema no se entera de que existe: si este servicio está apagado, `ocr_service` lo reporta como no disponible y el modo híbrido degrada a su motor principal en lugar de fallar.

---

## Qué Recibe y Qué Devuelve

### `POST /engine/run`

**Body:** `multipart/form-data` — idéntico al del servicio de Tesseract.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `file` | archivo (`jpeg`/`png`/`webp`) | la imagen **original**, en color |
| `lang` | string | idioma (`spa` por defecto; se traduce a `es`) |
| `layout` | string | se acepta por contrato, pero **se ignora** |
| `transform` | JSON | de la cadena, sólo se aplican `rotate` y el tope de ancho |

**Qué se ignora y por qué.** Está medido: la cadena de filtros que hace rendir a Tesseract —grises, inversión, CLAHE, binarización— *degrada* a EasyOCR, porque sus modelos esperan la imagen en color y hacen su propio preprocesamiento interno. Aplicarlos sería empeorar la lectura a pedido. Lo que sí se aplica es lo puramente geométrico: el giro y la resolución, que son decisiones del coordinador sobre el documento, no sobre el motor.

`layout` se ignora porque EasyOCR detecta las regiones de texto por su cuenta y no expone nada equivalente al *page segmentation mode* de Tesseract.

**Respuesta `200`:** el mismo esquema que el otro motor.

```jsonc
{
  "engine": "easyocr",
  "text": "Leche Entera\n1 litro",
  "words": [
    { "text": "Leche", "confidence": 1.0,
      "left": 62, "top": 40, "width": 180, "height": 52, "line_num": 0 }
  ],
  "elapsed_ms": 3820,
  "image_width": 800,
  "image_height": 1422,
  "lang": "es"
}
```

Las cajas se devuelven en **coordenadas de la imagen recibida**, no de la imagen recortada internamente: el coordinador no tiene por qué saber de ese recorte.

Como EasyOCR no numera las líneas, se agrupan por proximidad vertical antes de devolverlas, para que el texto reconstruido tenga la misma forma que el del otro motor.

**Errores:** `400` formato no soportado, archivo vacío, imagen ilegible o `transform` mal formado · `401` clave compartida inválida · `413` imagen demasiado grande · `503` el paquete `easyocr` no está instalado · `500` el modelo falló.

### `GET /engine/info`

```json
{ "engine": "easyocr", "version": "1.7.2",
  "languages": ["eng", "spa"], "supports_preprocessing": false }
```

`supports_preprocessing: false` le dice a `ocr_service` que no gaste reintentos variando filtros que este motor va a ignorar: cada corrida cuesta segundos y no cambiaría nada.

### `GET /engine/livez` · `GET /engine/readyz`

- `livez` → `{ "status": "ok" }`. Sin dependencias.
- `readyz` → verifica que la dependencia esté instalada **y que el modelo cargue**.

---

## Manejo de Memoria

El modelo de detección crece en memoria con la resolución de entrada. Medido:

| Ancho de entrada | Memoria | Latencia por documento |
|---|---|---|
| 640 px | ~0,9 GB | ~3 s |
| 800 px | ~1,3 GB | ~4 s |
| 1280 px | ~1,8 GB | ~6 s |

`MAX_WIDTH` es un **techo de seguridad**, no una preferencia de calidad: por encima, el proceso muere por OOM y se lleva puesto el contenedor. Qué resolución conviene para cada documento lo decide el coordinador y lo pide en `transform.max_width`; acá se le impone este techo.

> **Docker Desktop** reparte por defecto ~2 GB entre *todos* los contenedores. Con este servicio arriba conviene subirlo (Settings → Resources → Memory, recomendado 4 GB) o bajar `MAX_WIDTH`.

---

## Ejecución

```bash
docker network create tpp-net
```

```bash
cp .env.example .env
```

```bash
docker-compose up -d --build
```

La primera build descarga PyTorch (desde el índice **CPU**, para no arrastrar los ~2 GB de CUDA en un despliegue sin GPU) y los modelos de EasyOCR. Tarda varios minutos; después el contenedor arranca sin depender de la red.

```bash
curl http://localhost:8006/engine/readyz
```

Con `PRELOAD_MODEL=true` el modelo se carga al arrancar: son ~6 s que, si no, los paga el primer usuario. Por eso el healthcheck del compose tiene `start_period`.

### Local

```bash
pip install -r requirements.txt
```

```bash
uvicorn app.main:app --reload --port 8006
```

---

## Configuración

| Variable | Default | Para qué |
|----------|---------|----------|
| `PORT` | `8006` | puerto del servicio |
| `DEFAULT_LANG` | `spa` | idioma cuando la petición no lo especifica |
| `MAX_WIDTH` | `1600` | **techo** de ancho de entrada (límite de memoria) |
| `PRELOAD_MODEL` | `true` | cargar el modelo al arrancar |
| `ENGINE_API_KEY` | *(vacía)* | clave compartida con el coordinador |
| `MAX_UPLOAD_BYTES` | `15728640` | tope del binario recibido |

---

## Tests

```bash
pytest
```

**42 tests, 92 % de cobertura.** No cargan el modelo —son ~6 s y 1,3 GB—: se dobla el `Reader`. Lo que sí se ejercita es el giro, el acotado de ancho, la reexpansión de las cajas a las coordenadas originales y el agrupamiento por líneas, que es todo lo que este servicio aporta además de invocar al modelo.

Además, `test_bandas_reales.py` ejercita la detección de bandas de texto sobre **una foto de envase real** —un sello de vencimiento fotografiado a pulso, la única imagen versionada del repositorio, 103 KB a 1400 px— y sin cargar el modelo, así que corre en el CI como cualquier otro test. Es la función que el coordinador usa para aislar el sello, y no se puede probar con un rectángulo dibujado: lo que hay que verificar es que encuentre un renglón entre la iluminación despareja, el envase curvo y el fondo de la mesada. Las afirmaciones son geométricas y no de contenido, porque **cuál** de las bandas es el sello no lo decide este servicio: las ordena y el coordinador prueba las primeras.

| Archivo | Qué cubre |
|---------|-----------|
| `test_engine.py` | preparación geométrica y traducción de las detecciones |
| `test_routes.py` | el contrato HTTP, validaciones, salud y clave compartida |
