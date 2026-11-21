"""Inicio de sesión de clientes y modo administrador.

Uso en app.py (después de crear la app y la conexión a MongoDB):

    from auth import registrar_auth
    registrar_auth(app, base_datos["usuarios"])
"""
import os
import re
import time
from hmac import compare_digest

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

# Contraseña del modo administrador.
# Si existe la variable de entorno ADMIN_PASSWORD se usa esa; si no, esta.
CLAVE_ADMIN = os.environ.get("ADMIN_PASSWORD", "takis2009")

# Pantallas que puede usar un cliente. Todo lo demás (agregar, editar,
# eliminar y películas registradas) es solo para el administrador.
PANTALLAS_CLIENTE = {
    "inicio", "comprar", "alimentos", "comprar_alimentos", "ayuda",
    "ajustes", "entrar_admin", "salir_admin", "cerrar_sesion",
}

# Pantallas que se pueden abrir sin iniciar sesión.
# Los comprobantes son públicos porque el código QR apunta a ellos.
PANTALLAS_PUBLICAS = {
    "login", "registro", "static",
    "comprobante_reserva", "comprobante_alimentos",
}

# API de películas: se puede consultar (GET), pero para agregar,
# editar o borrar hay que estar en modo administrador.
PANTALLAS_API = {"api_productos", "api_producto"}

INTENTOS_MAXIMOS = 5
SEGUNDOS_BLOQUEO = 60

PATRON_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _destino_seguro(ruta):
    """Solo permite volver a rutas internas del sitio."""
    if ruta and ruta.startswith("/") and not ruta.startswith("//"):
        return ruta
    return None


def registrar_auth(app, usuarios):
    """Agrega login, registro, ajustes y la revisión de permisos a la app."""

    try:
        usuarios.create_index("correo", unique=True)
    except Exception:
        # si no se puede crear el índice, el correo se revisa a mano al registrar
        pass

    @app.before_request
    def revisar_acceso():
        endpoint = request.endpoint

        if endpoint is None or endpoint in PANTALLAS_PUBLICAS:
            return None

        if endpoint in PANTALLAS_API:
            if request.method == "GET" or session.get("admin"):
                return None
            return jsonify({"error": "Solo el administrador puede modificar películas"}), 403

        if "usuario" not in session:
            return redirect(url_for("login", siguiente=request.path))

        if session.get("admin") or endpoint in PANTALLAS_CLIENTE:
            return None

        flash("Esa sección es solo para el administrador. Actívalo en Ajustes.", "warning")
        return redirect(url_for("inicio"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if "usuario" in session:
            return redirect(url_for("inicio"))

        if request.method == "POST":
            correo = request.form.get("correo", "").strip().lower()
            clave = request.form.get("clave", "")

            usuario = usuarios.find_one({"correo": correo})

            if usuario and check_password_hash(usuario["clave"], clave):
                session.clear()
                session["usuario"] = correo
                session["nombre"] = usuario.get("nombre") or correo
                destino = _destino_seguro(request.args.get("siguiente"))
                return redirect(destino or url_for("inicio"))

            return render_template(
                "login.html",
                error="Correo o contraseña incorrectos.",
                correo=correo,
            )

        return render_template("login.html")

    @app.route("/registro", methods=["GET", "POST"])
    def registro():
        if "usuario" in session:
            return redirect(url_for("inicio"))

        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            correo = request.form.get("correo", "").strip().lower()
            clave = request.form.get("clave", "")
            clave2 = request.form.get("clave2", "")

            error = None
            if len(nombre) < 2:
                error = "Escribe tu nombre."
            elif not PATRON_CORREO.match(correo):
                error = "Escribe un correo electrónico válido."
            elif len(clave) < 6:
                error = "La contraseña debe tener al menos 6 caracteres."
            elif clave != clave2:
                error = "Las contraseñas no coinciden."
            elif usuarios.find_one({"correo": correo}):
                error = "Ya existe una cuenta con ese correo."

            if error:
                return render_template(
                    "registro.html", error=error, nombre=nombre, correo=correo
                )

            usuarios.insert_one({
                "nombre": nombre,
                "correo": correo,
                "clave": generate_password_hash(clave),
            })

            session.clear()
            session["usuario"] = correo
            session["nombre"] = nombre
            flash("Tu cuenta se creó correctamente.", "success")
            return redirect(url_for("inicio"))

        return render_template("registro.html")

    @app.route("/ajustes")
    def ajustes():
        return render_template("ajustes.html")

    @app.route("/ajustes/admin", methods=["POST"])
    def entrar_admin():
        ahora = time.time()

        if session.get("bloqueado_hasta", 0) > ahora:
            falta = int(session["bloqueado_hasta"] - ahora) + 1
            flash(f"Demasiados intentos. Espera {falta} segundos.", "danger")
            return redirect(url_for("ajustes", admin=1))

        intento = request.form.get("clave_admin", "")

        if compare_digest(intento.encode(), CLAVE_ADMIN.encode()):
            session["admin"] = True
            session.pop("intentos_admin", None)
            flash("Modo administrador activado.", "success")
            return redirect(url_for("ajustes"))

        session["intentos_admin"] = session.get("intentos_admin", 0) + 1
        if session["intentos_admin"] >= INTENTOS_MAXIMOS:
            session["bloqueado_hasta"] = ahora + SEGUNDOS_BLOQUEO
            session["intentos_admin"] = 0

        flash("Contraseña incorrecta.", "danger")
        return redirect(url_for("ajustes", admin=1))

    @app.route("/ajustes/admin/salir", methods=["POST"])
    def salir_admin():
        session.pop("admin", None)
        flash("Saliste del modo administrador.", "success")
        return redirect(url_for("ajustes"))

    @app.route("/cerrar-sesion", methods=["POST"])
    def cerrar_sesion():
        session.clear()
        flash("Cerraste sesión.", "success")
        return redirect(url_for("login"))