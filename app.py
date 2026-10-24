from flask import (
    Flask, render_template, request, redirect,
    url_for, abort, jsonify
)
from pymongo import MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError
from bson import ObjectId
from datetime import datetime
import os

app = Flask(__name__)

# =========================
# CONEXIÓN A MONGODB ATLAS
# =========================

mongo_uri = os.environ.get("MONGO_URI")

if not mongo_uri:
    if os.environ.get("RENDER"):
        raise RuntimeError("Falta configurar la variable MONGO_URI en Render.")
    mongo_uri = "mongodb://127.0.0.1:27017/"

cliente = MongoClient(
    mongo_uri,
    serverSelectionTimeoutMS=10000
)

base_datos = cliente["cinepolis"]

alumnos = base_datos["peliculas"]
compras = base_datos["compras"]
asientos = base_datos["asientos"]

PRECIO_BOLETO = 80

HORARIOS_VALIDOS = ["12:00", "15:00", "18:00", "21:00"]

ASIENTOS_VALIDOS = [
    f"{fila}{numero}"
    for fila in "ABCDEF"
    for numero in range(1, 9)
]

# Evita que el mismo asiento se ocupe dos veces
# para la misma película, fecha y horario.
asientos.create_index(
    [
        ("pelicula_id", 1),
        ("fecha", 1),
        ("horario", 1),
        ("asiento", 1)
    ],
    unique=True,
    name="asiento_unico_por_funcion"
)


# =========================
# FUNCIONES AUXILIARES
# =========================

def leer_formulario():
    return {
        "titulo": request.form.get("titulo", "").strip(),
        "genero": request.form.get("genero", "").strip(),
        "duracion": request.form.get("duracion", "").strip(),
        "clasificacion": request.form.get("clasificacion", "").strip(),
        "descripcion": request.form.get("descripcion", "").strip(),
        "poster": request.form.get("poster", "").strip()
    }


def aplicar_poster(pelicula):
    if not pelicula:
        return pelicula

    if not pelicula.get("poster"):
        titulo = pelicula.get("titulo", "").lower()

        if "spider-man" in titulo or "spiderman" in titulo:
            pelicula["poster"] = (
                "https://image.tmdb.org/t/p/w500/"
                "8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg"
            )

    return pelicula


def buscar_alumno(id):
    try:
        return alumnos.find_one({"_id": ObjectId(id)})
    except Exception:
        return None


def consultar_asientos_ocupados(pelicula_id, fecha, horario):
    documentos = asientos.find({
        "pelicula_id": str(pelicula_id),
        "fecha": fecha,
        "horario": horario,
        "estado": "Ocupado"
    })

    return [documento["asiento"] for documento in documentos]


def leer_asientos_seleccionados():
    seleccionados = request.form.getlist("asientos")

    if not seleccionados:
        return None, "Selecciona al menos un asiento."

    if len(seleccionados) > 6:
        return None, "Solo puedes seleccionar hasta 6 asientos."

    if len(seleccionados) != len(set(seleccionados)):
        return None, "Hay asientos repetidos en la selección."

    if any(asiento not in ASIENTOS_VALIDOS for asiento in seleccionados):
        return None, "La selección contiene asientos no válidos."

    return seleccionados, None


def validar_fecha_horario(fecha, horario):
    try:
        fecha_objeto = datetime.strptime(fecha, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "Selecciona una fecha válida."

    hoy = datetime.now().date()

    if fecha_objeto < hoy:
        return "No puedes comprar boletos para una fecha pasada."

    if horario not in HORARIOS_VALIDOS:
        return "Selecciona un horario válido."

    if fecha_objeto == hoy:
        hora_actual = datetime.now().strftime("%H:%M")

        if horario <= hora_actual:
            return "Ese horario ya pasó. Selecciona uno posterior."

    return None


def mostrar_mapa(pelicula, fecha, horario, mensaje_error=None):
    ocupados = consultar_asientos_ocupados(
        pelicula["_id"], fecha, horario
    )

    return render_template(
        "comprar.html",
        pelicula=pelicula,
        compra_confirmada=False,
        confirmar=False,
        folio=None,
        fecha=fecha,
        horario=horario,
        seleccionados=[],
        cantidad=0,
        total=0,
        hoy=datetime.now().strftime("%Y-%m-%d"),
        fecha_seleccionada=fecha,
        horario_seleccionado=horario,
        asientos_ocupados=ocupados,
        mensaje_error=mensaje_error
    )


# =========================
# PÁGINA PRINCIPAL
# =========================

@app.route("/")
def inicio():
    peliculas = list(alumnos.find())

    for pelicula in peliculas:
        aplicar_poster(pelicula)

    return render_template(
        "index.html",
        peliculas=peliculas
    )


# =========================
# AGREGAR PELÍCULA
# =========================

@app.route("/agregar", methods=["GET", "POST"])
def agregar():
    if request.method == "POST":
        pelicula = leer_formulario()

        if not pelicula["titulo"]:
            return render_template(
                "agregar.html",
                mensaje_error="Escribe el título de la película."
            )

        try:
            if pelicula["duracion"]:
                pelicula["duracion"] = int(pelicula["duracion"])

            alumnos.insert_one(pelicula)

            return redirect(url_for("inicio"))

        except ValueError:
            return render_template(
                "agregar.html",
                mensaje_error="La duración debe ser un número."
            )

        except PyMongoError:
            abort(503)

    return render_template("agregar.html")


# =========================
# EDITAR PELÍCULA
# =========================

@app.route("/editar/<id>", methods=["GET", "POST"])
def editar(id):
    pelicula = buscar_alumno(id)

    if not pelicula:
        abort(404)

    if request.method == "POST":
        datos = leer_formulario()

        if not datos["titulo"]:
            aplicar_poster(pelicula)
            return render_template(
                "editar.html",
                pelicula=pelicula,
                mensaje_error="Escribe el título de la película."
            )

        try:
            if datos["duracion"]:
                datos["duracion"] = int(datos["duracion"])

            alumnos.update_one(
                {"_id": pelicula["_id"]},
                {"$set": datos}
            )

            return redirect(url_for("inicio"))

        except ValueError:
            aplicar_poster(pelicula)
            return render_template(
                "editar.html",
                pelicula=pelicula,
                mensaje_error="La duración debe ser un número."
            )

        except PyMongoError:
            abort(503)

    aplicar_poster(pelicula)

    return render_template(
        "editar.html",
        pelicula=pelicula
    )


# =========================
# ELIMINAR PELÍCULA
# =========================

@app.route("/eliminar/<id>", methods=["POST", "GET"])
def eliminar(id):
    pelicula = buscar_alumno(id)

    if not pelicula:
        abort(404)

    if request.method == "POST":
        try:
            alumnos.delete_one({"_id": pelicula["_id"]})

            return redirect(url_for("inicio"))

        except PyMongoError:
            abort(503)

    aplicar_poster(pelicula)

    return render_template(
        "eliminar.html",
        pelicula=pelicula
    )


# =========================
# AYUDA
# =========================

@app.route("/ayuda")
def ayuda():
    return render_template("ayuda.html")


# =========================
# COMPRA DE BOLETOS
# =========================

@app.route("/comprar/<id>", methods=["GET", "POST"])
def comprar(id):
    pelicula = buscar_alumno(id)

    if not pelicula:
        abort(404)

    aplicar_poster(pelicula)

    hoy = datetime.now().strftime("%Y-%m-%d")

    fecha = request.values.get("fecha", hoy).strip()
    horario = request.values.get("horario", "12:00").strip()

    if request.method == "GET":
        error = validar_fecha_horario(fecha, horario)

        if error:
            fecha = hoy
            horario = "12:00"

        return mostrar_mapa(pelicula, fecha, horario, error)

    accion = request.form.get("accion", "continuar").strip()

    error = validar_fecha_horario(fecha, horario)

    if error:
        return mostrar_mapa(pelicula, fecha, horario, error)

    # Consultar disponibilidad sin obligar a seleccionar asientos.
    if accion == "consultar":
        return mostrar_mapa(pelicula, fecha, horario)

    if accion not in ["continuar", "confirmar"]:
        abort(400)

    seleccionados, error = leer_asientos_seleccionados()

    if error:
        return mostrar_mapa(pelicula, fecha, horario, error)

    ocupados = consultar_asientos_ocupados(
        pelicula["_id"], fecha, horario
    )

    repetidos = [
        asiento for asiento in seleccionados
        if asiento in ocupados
    ]

    if repetidos:
        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            "Estos asientos ya están ocupados: "
            + ", ".join(repetidos)
            + ". Selecciona otros."
        )

    cantidad = len(seleccionados)
    total = cantidad * PRECIO_BOLETO

    # Mostrar resumen antes de confirmar la compra.
    if accion == "continuar":
        return render_template(
            "comprar.html",
            pelicula=pelicula,
            compra_confirmada=False,
            confirmar=True,
            folio=None,
            fecha=fecha,
            horario=horario,
            seleccionados=seleccionados,
            cantidad=cantidad,
            total=total,
            hoy=hoy,
            fecha_seleccionada=fecha,
            horario_seleccionado=horario,
            asientos_ocupados=ocupados,
            mensaje_error=None
        )

    # Confirmar compra y reservar asientos.
    documentos_insertados = []

    try:
        for asiento in seleccionados:
            resultado = asientos.insert_one({
                "pelicula_id": str(pelicula["_id"]),
                "titulo_pelicula": pelicula.get("titulo", ""),
                "fecha": fecha,
                "horario": horario,
                "asiento": asiento,
                "estado": "Ocupado",
                "fecha_registro": datetime.now()
            })

            documentos_insertados.append(resultado.inserted_id)

        compra = {
            "pelicula_id": str(pelicula["_id"]),
            "titulo_pelicula": pelicula.get("titulo", ""),
            "fecha": fecha,
            "horario": horario,
            "asientos": seleccionados,
            "cantidad": cantidad,
            "precio_por_boleto": PRECIO_BOLETO,
            "total": total,
            "fecha_compra": datetime.now()
        }

        resultado_compra = compras.insert_one(compra)

        folio = str(resultado_compra.inserted_id)

        return render_template(
            "comprar.html",
            pelicula=pelicula,
            compra_confirmada=True,
            confirmar=False,
            folio=folio,
            fecha=fecha,
            horario=horario,
            seleccionados=seleccionados,
            cantidad=cantidad,
            total=total,
            hoy=hoy,
            fecha_seleccionada=fecha,
            horario_seleccionado=horario,
            asientos_ocupados=seleccionados,
            mensaje_error=None
        )

    except DuplicateKeyError:
        if documentos_insertados:
            asientos.delete_many({
                "_id": {"$in": documentos_insertados}
            })

        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            "Uno de los asientos acaba de ser ocupado. "
            "Actualiza la disponibilidad y selecciona otros."
        )

    except PyMongoError:
        if documentos_insertados:
            try:
                asientos.delete_many({
                    "_id": {"$in": documentos_insertados}
                })
            except PyMongoError:
                pass

        abort(503)


# =========================
# API DE PELÍCULAS
# =========================

def leer_json():
    datos = request.get_json(silent=True)

    if not isinstance(datos, dict):
        return None

    return datos


@app.route("/api/productos", methods=["GET", "POST"])
def api_productos():
    if request.method == "GET":
        try:
            peliculas = []

            for pelicula in alumnos.find():
                pelicula["_id"] = str(pelicula["_id"])
                peliculas.append(pelicula)

            return jsonify(peliculas), 200

        except PyMongoError:
            return jsonify({"error": "Error al consultar películas"}), 503

    datos = leer_json()

    if datos is None:
        return jsonify({"error": "Envía un objeto JSON válido"}), 400

    datos.pop("_id", None)

    if not datos.get("titulo"):
        return jsonify({"error": "El título es obligatorio"}), 400

    try:
        resultado = alumnos.insert_one(datos)

        return jsonify({
            "mensaje": "Película agregada",
            "id": str(resultado.inserted_id)
        }), 201

    except PyMongoError:
        return jsonify({"error": "No se pudo guardar la película"}), 503


@app.route("/api/productos/<id>", methods=["GET", "PUT", "DELETE"])
def api_producto(id):
    try:
        object_id = ObjectId(id)
    except Exception:
        return jsonify({"error": "ID inválido"}), 400

    if request.method == "GET":
        try:
            pelicula = alumnos.find_one({"_id": object_id})

            if not pelicula:
                return jsonify({"error": "Película no encontrada"}), 404

            pelicula["_id"] = str(pelicula["_id"])

            return jsonify(pelicula), 200

        except PyMongoError:
            return jsonify({"error": "Error al consultar"}), 503

    if request.method == "PUT":
        datos = leer_json()

        if datos is None:
            return jsonify({"error": "Envía un objeto JSON válido"}), 400

        datos.pop("_id", None)

        try:
            resultado = alumnos.update_one(
                {"_id": object_id},
                {"$set": datos}
            )

            if resultado.matched_count == 0:
                return jsonify({"error": "Película no encontrada"}), 404

            return jsonify({"mensaje": "Película actualizada"}), 200

        except PyMongoError:
            return jsonify({"error": "No se pudo actualizar"}), 503

    try:
        resultado = alumnos.delete_one({"_id": object_id})

        if resultado.deleted_count == 0:
            return jsonify({"error": "Película no encontrada"}), 404

        return jsonify({"mensaje": "Película eliminada"}), 200

    except PyMongoError:
        return jsonify({"error": "No se pudo eliminar"}), 503


# =========================
# MANEJO DE ERRORES
# =========================

@app.errorhandler(404)
def no_encontrado(error):
    return "Página o película no encontrada.", 404


@app.errorhandler(503)
def servicio_no_disponible(error):
    return (
        "No se pudo conectar con la base de datos. "
        "Verifica MongoDB Atlas y la variable MONGO_URI.",
        503
    )


# =========================
# INICIAR APLICACIÓN
# =========================

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )