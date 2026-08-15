"""Branded error pages. Single place that maps an HTTP status code to a
Spanish title/message pair and renders `templates/errors/generic.html`,
so every `abort()` in the app - plus the global Flask error handlers
registered in `main.py` - shows instance branding instead of Werkzeug's
raw English "Not Found"/"Bad Request" pages.

`from_http_exception` only trusts `error.description` when a call site
explicitly customized it (e.g. `abort(403, "Este archivo fue marcado...")`,
already used throughout `drive/`) - a bare `abort(404)` leaves
`description` pointing at Werkzeug's own class-level default text, which
must never leak to the user.
"""

from __future__ import annotations

from flask import render_template, request
from flask_wtf.csrf import CSRFError

_DEFAULT_COPY: dict[int, tuple[str, str]] = {
    400: ("Solicitud inválida", "La solicitud no se pudo procesar. Verifica los datos e intenta de nuevo."),
    403: ("Acceso denegado", "No tienes permiso para acceder a este contenido."),
    404: ("Página no encontrada", "La página que buscas no existe o fue movida."),
    409: ("Conflicto", "Esta operación ya está en curso o entra en conflicto con el estado actual."),
    413: ("Archivo demasiado grande", "El archivo supera el límite de tamaño permitido en esta instancia."),
    429: ("Demasiadas solicitudes", "Estás realizando demasiadas solicitudes. Intenta de nuevo en unos minutos."),
    500: ("Error del servidor", "Algo salió mal de nuestro lado. Ya lo estamos revisando."),
}

# Every 404 raised inside the public share viewer (`blueprints/public`)
# means the same thing to a visitor: token unknown, share revoked/
# expired, or a node it used to point at is gone - there is no other
# reason that blueprint returns a 404.
_SHARE_LINK_BROKEN_TITLE = "Hubo un error por nuestra parte"
_SHARE_LINK_BROKEN_MESSAGE = (
    "La dirección que estás solicitando no existe o el usuario que te la "
    "compartió la revocó o expiró. Por favor contacta con el usuario y "
    "solicítale un nuevo link."
)


def error_response(status_code: int, *, title: str | None = None, message: str | None = None):
    default_title, default_message = _DEFAULT_COPY.get(status_code, ("Error", "Ocurrio un error inesperado."))
    return (
        render_template(
            "errors/generic.html",
            status_code=status_code,
            title=title or default_title,
            message=message or default_message,
        ),
        status_code,
    )


def from_http_exception(error):
    status_code = error.code or 500

    if status_code == 404 and request.blueprint == "public":
        return error_response(404, title=_SHARE_LINK_BROKEN_TITLE, message=_SHARE_LINK_BROKEN_MESSAGE)

    if isinstance(error, CSRFError):
        # flask-wtf's own `description` is the (English) validation
        # failure reason - fine for logs, not for a branded user-facing
        # page - so this falls through to the generic Spanish 400 copy.
        return error_response(400)

    description = getattr(error, "description", None)
    default_description = getattr(type(error), "description", None)
    custom_message = description if description and description != default_description else None
    return error_response(status_code, message=custom_message)
