from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Servidor
    HOST: str = "0.0.0.0"
    PORT: int = 8006
    DEBUG: bool = False

    DEFAULT_LANG: str = "spa"

    # Techo duro de ancho de entrada. El modelo de detección crece en memoria con
    # la resolución, así que este valor no es una preferencia de calidad sino un
    # límite de seguridad: por encima, el proceso muere por OOM y se lleva
    # puesto el contenedor.
    #
    # Qué resolución conviene para cada documento lo decide el coordinador y lo
    # pide en `transform.max_width`; acá sólo se le impone este techo.
    MAX_WIDTH: int = 1600

    # Cargar el modelo al arrancar evita que la primera petición pague los ~6 s de
    # inicialización. Se puede apagar para que el contenedor levante liviano.
    PRELOAD_MODEL: bool = True

    # Clave compartida con el coordinador. Vacía = sin control de acceso.
    ENGINE_API_KEY: str = ""

    MAX_UPLOAD_BYTES: int = 15 * 1024 * 1024


settings = Settings()
