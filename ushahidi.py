"""Cliente mínimo de la API de Ushahidi (v3 para auth/media, v5 para posts)."""
import time
import logging
import httpx

import config

log = logging.getLogger(__name__)


class UshahidiError(Exception):
    pass


class UshahidiClient:
    def __init__(self, email: str | None = None, password: str | None = None):
        """Sin argumentos usa la cuenta por defecto (variables de entorno);
        con email/password sube las aportaciones como ese usuario."""
        self.email = email or config.USHAHIDI_EMAIL
        self.password = password or config.USHAHIDI_PASSWORD
        self._token: str | None = None
        self._token_expires: float = 0.0
        # El despliegue (capa gratuita) a veces tarda mucho en procesar la
        # subida de fotos: damos hasta 120s a la respuesta antes de rendirnos
        self._http = httpx.AsyncClient(
            base_url=config.USHAHIDI_BASE,
            timeout=httpx.Timeout(30, read=120),
        )

    async def _post(self, *args, **kwargs) -> httpx.Response:
        """POST que convierte los errores de red (timeout, DNS, conexión...)
        en UshahidiError para que el bot pueda avisar al usuario."""
        try:
            return await self._http.post(*args, **kwargs)
        except httpx.HTTPError as e:
            raise UshahidiError(
                f"Sin respuesta del servidor ({type(e).__name__}): {e}"
            ) from e

    # ------------------------------------------------------------------ auth
    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        resp = await self._post(
            "/oauth/token",
            json={
                "grant_type": "password",
                "username": self.email,
                "password": self.password,
                "client_id": config.USHAHIDI_CLIENT_ID,
                "client_secret": config.USHAHIDI_CLIENT_SECRET,
                "scope": "posts media forms api",
            },
        )
        if resp.status_code != 200:
            raise UshahidiError(f"Error de autenticación ({resp.status_code}): {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 3600)
        return self._token

    async def check_login(self) -> None:
        """Valida las credenciales pidiendo un token; lanza UshahidiError si fallan."""
        await self._get_token()

    async def _headers(self) -> dict:
        return {"Authorization": f"Bearer {await self._get_token()}"}

    # ----------------------------------------------------------------- media
    async def upload_media(self, image_bytes: bytes, filename: str = "foto.jpg",
                           caption: str = "") -> int:
        """Sube una imagen al endpoint de media (v3) y devuelve su id."""
        resp = await self._post(
            "/api/v3/media",
            headers=await self._headers(),
            files={"file": (filename, image_bytes, "image/jpeg")},
            data={"caption": caption},
        )
        if resp.status_code not in (200, 201):
            raise UshahidiError(f"Error subiendo la foto ({resp.status_code}): {resp.text}")
        return resp.json()["id"]

    # ----------------------------------------------------------------- posts
    def _field_entry(self, field_def: dict, value) -> dict:
        """Construye la entrada de un campo dentro de post_content."""
        return {
            "id": field_def["id"],
            "key": field_def["key"],
            "type": field_def["type"],
            "input": field_def["input"],
            "form_stage_id": config.TASK_ID,
            "value": {"value": value},
        }

    async def create_post(self, *, title: str, description: str,
                          lat: float, lon: float, media_id: int,
                          letrero: list[str], discurso: list[str]) -> dict:
        """Crea el post en la encuesta Corpus. Devuelve el JSON del post creado."""
        fields = [
            self._field_entry(config.FIELD_LOCATION, {"lat": lat, "lon": lon}),
            # La API valida que value.value de un campo media sea una lista de ids
            self._field_entry(config.FIELD_PHOTO, [media_id]),
        ]
        # Los checkbox admiten varias opciones; Ushahidi espera lista de strings
        if letrero:
            fields.append(self._field_entry(config.FIELD_LETRERO, letrero))
        if discurso:
            fields.append(self._field_entry(config.FIELD_DISCURSO, discurso))

        payload = {
            "title": title[: config.MAX_TITLE_LEN],
            "content": description,
            "type": "report",
            "form_id": config.FORM_ID,
            "locale": "es_ES",
            "completed_stages": [],
            "published_to": [],
            "post_content": [
                {
                    "id": config.TASK_ID,
                    "form_id": config.FORM_ID,
                    "type": "post",
                    "fields": fields,
                }
            ],
        }
        resp = await self._post(
            "/api/v5/posts", headers=await self._headers(), json=payload
        )
        if resp.status_code not in (200, 201):
            # Los 422 de Ushahidi traen detalle campo a campo: útil para depurar
            raise UshahidiError(f"Error creando el post ({resp.status_code}): {resp.text}")
        return resp.json()

    async def close(self):
        await self._http.aclose()


async def register_user(email: str, password: str, realname: str = "") -> None:
    """Crea una cuenta nueva en el despliegue (POST /api/v3/register).

    ⚠️ Requiere que el registro esté habilitado en los ajustes de Ushahidi:
    a día de hoy andaluh.ushahidi.io tiene 'disable_registration' activado,
    así que este endpoint devuelve 500 hasta que se active desde el panel.
    """
    try:
        async with httpx.AsyncClient(base_url=config.USHAHIDI_BASE, timeout=30) as http:
            resp = await http.post(
                "/api/v3/register",
                json={
                    "email": email,
                    "password": password,
                    "realname": realname or email.split("@")[0],
                },
            )
    except httpx.HTTPError as e:
        raise UshahidiError(f"Sin respuesta del servidor ({type(e).__name__}): {e}") from e
    if resp.status_code not in (200, 201):
        raise UshahidiError(f"Error creando la cuenta ({resp.status_code}): {resp.text}")
