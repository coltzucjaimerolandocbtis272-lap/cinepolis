
from flask import (
    Flask, render_template, request, redirect,
    url_for, abort, jsonify
)
from pymongo import MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError
from bson import ObjectId
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)

# =========================
# CONEXIÓN A MONGODB ATLAS
# =========================

mongo_uri = os.environ.get("MONGO_URI")

if not mongo_uri:
    if os.environ.get("RENDER"):
        raise RuntimeError("Falta configurar MONGO_URI en Render.")
    mongo_uri = "mongodb://127.0.0.1:27017/"

cliente = MongoClient(
    mongo_uri,
    serverSelectionTimeoutMS=10000
)

base_datos = cliente["cinepolis"]
alumnos = base_datos["peliculas"]
compras = base_datos["compras"]
asientos = base_datos["asientos"]

# =========================
# CONFIGURACIÓN
# =========================

ZONA_HORARIA = ZoneInfo("America/Cancun")
PRECIO_BOLETO = 80
MAXIMO_PELICULAS = 15
MAXIMO_ASIENTOS = 6

HORARIOS_VALIDOS = ["12:00", "15:00", "18:00", "21:00"]
ASIENTOS_VALIDOS = list(range(1, 49))

# Evita vender el mismo asiento dos veces.
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

def ahora_local():
    return datetime.now(ZONA_HORARIA)


def siguiente_funcion():
    ahora = ahora_local()

    for horario in HORARIOS_VALIDOS:
        hora = datetime.strptime(horario, "%H:%M").time()

        funcion = datetime.combine(
            ahora.date(), hora
        ).replace(tzinfo=ZONA_HORARIA)

        if funcion > ahora:
            return ahora.strftime("%Y-%m-%d"), horario

    manana = ahora.date() + timedelta(days=1)
    return manana.strftime("%Y-%m-%d"), HORARIOS_VALIDOS[0]


def validar_fecha_horario(fecha, horario):
    if horario not in HORARIOS_VALIDOS:
        return "Selecciona un horario válido."

    try:
        fecha_objeto = datetime.strptime(
            fecha, "%Y-%m-%d"
        ).date()
    except (ValueError, TypeError):
        return "Selecciona una fecha válida."

    ahora = ahora_local()

    if fecha_objeto < ahora.date():
        return "La fecha seleccionada ya pasó."

    hora = datetime.strptime(horario, "%H:%M").time()

    funcion = datetime.combine(
        fecha_objeto, hora
    ).replace(tzinfo=ZONA_HORARIA)

    if funcion <= ahora:
        return "Ese horario ya pasó. Selecciona uno posterior."

    return None


def buscar_alumno(id):
    try:
        return alumnos.find_one({"_id": ObjectId(id)})
    except Exception:
        return None


def aplicar_poster(pelicula):
    if not pelicula:
        return pelicula

    if not pelicula.get("poster") and not pelicula.get("poster_url"):
        titulo = pelicula.get(
            "titulo", pelicula.get("nombre", "")
        ).lower()

        if "spider-man" in titulo or "spiderman" in titulo:
            pelicula["poster"] = (
                "https://image.tmdb.org/t/p/w500/"
                "8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg"
            )

    return pelicula


def leer_formulario():
    datos = {
        "titulo": request.form.get(
            "titulo", request.form.get("nombre", "")
        ).strip(),
        "genero": request.form.get(
            "genero", request.form.get("categoria", "")
        ).strip(),
        "duracion": request.form.get("duracion", "").strip(),
        "clasificacion": request.form.get(
            "clasificacion", ""
        ).strip(),
        "descripcion": request.form.get(
            "descripcion", ""
        ).strip(),
        "poster": request.form.get(
            "poster", ""
        ).strip(),
        "estado": request.form.get(
            "estado", "Disponible"
        ).strip()
    }
    return datos


def consultar_asientos_ocupados(pelicula_id, fecha, horario):
    documentos = asientos.find({
        "pelicula_id": str(pelicula_id),
        "fecha": fecha,
        "horario": horario,
        "estado": "Ocupado"
    })

    ocupados = set()

    for documento in documentos:
        valor = documento.get("asiento")

        # Compatibilidad con registros antiguos: A1, A2 ... F8.
        if isinstance(valor, str):
            valor = valor.strip().upper()

            if len(valor) >= 2 and valor[0] in "ABCDEF":
                try:
                    columna = int(valor[1:])
                    fila = "ABCDEF".index(valor[0])

                    if 1 <= columna <= 8:
                        valor = fila * 8 + columna
                except ValueError:
                    continue
            else:
                try:
                    valor = int(valor)
                except ValueError:
                    continue

        try:
            numero = int(valor)
        except (ValueError, TypeError):
            continue

        if numero in ASIENTOS_VALIDOS:
            ocupados.add(numero)

    return sorted(ocupados)


def leer_asientos_seleccionados(cantidad_esperada=None):
    valores = request.form.getlist("asientos")

    if not valores:
        return None, "Selecciona los asientos de tus boletos."

    if len(valores) > MAXIMO_ASIENTOS:
        return None, "Solo puedes comprar hasta 6 boletos."

    try:
        seleccionados = [int(valor) for valor in valores]
    except (ValueError, TypeError):
        return None, "La selección contiene asientos no válidos."

    if len(seleccionados) != len(set(seleccionados)):
        return None, "No puedes seleccionar asientos repetidos."

    if any(numero not in ASIENTOS_VALIDOS for numero in seleccionados):
        return None, "La selección contiene asientos no válidos."

    if (
        cantidad_esperada is not None
        and len(seleccionados) != cantidad_esperada
    ):
        return None, (
            f"Elegiste {cantidad_esperada} boleto(s). "
            f"Debes seleccionar exactamente "
            f"{cantidad_esperada} asiento(s)."
        )

    return sorted(seleccionados), None


def leer_cantidad():
    try:
        cantidad = int(request.values.get("cantidad", "1"))
    except (ValueError, TypeError):
        return None

    if not 1 <= cantidad <= MAXIMO_ASIENTOS:
        return None

    return cantidad


def mostrar_mapa(
    pelicula,
    fecha,
    horario,
    mensaje_error=None,
    cantidad=1
):
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
        cantidad=cantidad,
        total=cantidad * PRECIO_BOLETO,
        precio_boleto=PRECIO_BOLETO,
        maximo_asientos=MAXIMO_ASIENTOS,
        asientos_validos=ASIENTOS_VALIDOS,
        hoy=ahora_local().strftime("%Y-%m-%d"),
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
    peliculas = list(
        alumnos.find().sort("_id", 1).limit(MAXIMO_PELICULAS)
    )

    for pelicula in peliculas:
        aplicar_poster(pelicula)

    return render_template(
        "index.html",
        alumnos=peliculas,
        peliculas=peliculas,
        error=request.args.get("error"),
        agregada=request.args.get("agregada")
    )


# =========================
# PÁGINA DE PELÍCULAS REGISTRADAS
# =========================

@app.route("/peliculas")
def peliculas_registradas():
    peliculas = list(
        alumnos.find().sort("_id", 1).limit(MAXIMO_PELICULAS)
    )

    for pelicula in peliculas:
        aplicar_poster(pelicula)

    return render_template(
        "peliculas.html",
        alumnos=peliculas,
        peliculas=peliculas
    )


# =========================
# AGREGAR PELÍCULA
# =========================

@app.route("/agregar", methods=["GET", "POST"])
def agregar():
    # GET: muestra la página del formulario.
    if request.method == "GET":
        total_peliculas = alumnos.count_documents({})

        return render_template(
            "agregar.html",
            total_peliculas=total_peliculas,
            error=request.args.get("error")
        )

    # POST: procesa y guarda la película.
    nombre = request.form.get("nombre", "").strip()
    categoria = request.form.get("categoria", "").strip()
    estado = request.form.get("estado", "").strip()

    if not nombre or not categoria:
        return redirect(url_for("agregar") + "?error=datos")

    if estado not in ["Disponible", "Agotado"]:
        return redirect(url_for("agregar") + "?error=datos")

    try:
        if alumnos.count_documents({}) >= MAXIMO_PELICULAS:
            return redirect(url_for("agregar") + "?error=limite")

        alumnos.insert_one({
            "nombre": nombre,
            "categoria": categoria,
            "estado": estado
        })

        return redirect(url_for("inicio") + "?agregada=1")

    except PyMongoError:
        abort(503)


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

            datos["nombre"] = datos["titulo"]
            datos["categoria"] = datos["genero"]

            alumnos.update_one(
                {"_id": pelicula["_id"]},
                {"$set": datos}
            )

            return redirect(url_for("peliculas_registradas"))

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
    return render_template("editar.html", pelicula=pelicula)


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
            return redirect(
                url_for("peliculas_registradas") + "?eliminada=1"
            )
        except PyMongoError:
            abort(503)

    aplicar_poster(pelicula)
    return render_template("eliminar.html", pelicula=pelicula)


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

    fecha = request.values.get("fecha", "").strip()
    horario = request.values.get("horario", "").strip()

    cantidad = leer_cantidad()
    mensaje_cantidad = None

    if cantidad is None:
        cantidad = 1
        mensaje_cantidad = "Selecciona entre 1 y 6 boletos."

    if request.method == "GET":
        if not fecha or not horario:
            fecha, horario = siguiente_funcion()
        else:
            error = validar_fecha_horario(fecha, horario)
            if error:
                fecha, horario = siguiente_funcion()

        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error=mensaje_cantidad,
            cantidad=cantidad
        )

    accion = request.form.get("accion", "continuar").strip()

    if accion not in ["consultar", "continuar", "confirmar"]:
        abort(400)

    # Si cambia la fecha o la función, consulta disponibilidad.
    if accion == "consultar":
        error = validar_fecha_horario(fecha, horario)

        if error:
            fecha_nueva, horario_nuevo = siguiente_funcion()
            return mostrar_mapa(
                pelicula,
                fecha_nueva,
                horario_nuevo,
                mensaje_error=error,
                cantidad=cantidad
            )

        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error=mensaje_cantidad,
            cantidad=cantidad
        )

    error = validar_fecha_horario(fecha, horario)

    if error:
        fecha_nueva, horario_nuevo = siguiente_funcion()
        return mostrar_mapa(
            pelicula,
            fecha_nueva,
            horario_nuevo,
            mensaje_error=error,
            cantidad=cantidad
        )

    if mensaje_cantidad:
        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error=mensaje_cantidad,
            cantidad=1
        )

    seleccionados, error = leer_asientos_seleccionados(
        cantidad_esperada=cantidad
    )

    if error:
        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error=error,
            cantidad=cantidad
        )

    ocupados = consultar_asientos_ocupados(
        pelicula["_id"], fecha, horario
    )

    repetidos = [
        numero for numero in seleccionados
        if numero in ocupados
    ]

    if repetidos:
        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error=(
                "Estos asientos ya están ocupados: "
                + ", ".join(map(str, repetidos))
                + ". Consulta de nuevo la disponibilidad."
            ),
            cantidad=cantidad
        )

    total = cantidad * PRECIO_BOLETO

    # Mostrar el resumen antes de confirmar la compra.
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
            precio_boleto=PRECIO_BOLETO,
            maximo_asientos=MAXIMO_ASIENTOS,
            hoy=ahora_local().strftime("%Y-%m-%d"),
            fecha_seleccionada=fecha,
            horario_seleccionado=horario,
            asientos_ocupados=ocupados,
            mensaje_error=None
        )

    documentos_insertados = []

    try:
        # Registrar los asientos seleccionados.
        for numero in seleccionados:
            resultado = asientos.insert_one({
                "pelicula_id": str(pelicula["_id"]),
                "titulo_pelicula": pelicula.get(
                    "titulo", pelicula.get("nombre", "")
                ),
                "fecha": fecha,
                "horario": horario,
                "asiento": numero,
                "estado": "Ocupado",
                "fecha_registro": ahora_local()
            })

            documentos_insertados.append(resultado.inserted_id)

        # Registrar la compra.
        compra = {
            "pelicula_id": str(pelicula["_id"]),
            "titulo_pelicula": pelicula.get(
                "titulo", pelicula.get("nombre", "")
            ),
            "fecha": fecha,
            "horario": horario,
            "asientos": seleccionados,
            "cantidad": cantidad,
            "precio_por_boleto": PRECIO_BOLETO,
            "total": total,
            "fecha_compra": ahora_local()
        }

        resultado_compra = compras.insert_one(compra)

        return render_template(
            "comprar.html",
            pelicula=pelicula,
            compra_confirmada=True,
            confirmar=False,
            folio=str(resultado_compra.inserted_id),
            fecha=fecha,
            horario=horario,
            seleccionados=seleccionados,
            cantidad=cantidad,
            total=total,
            precio_boleto=PRECIO_BOLETO,
            hoy=ahora_local().strftime("%Y-%m-%d"),
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
            mensaje_error=(
                "Uno de los asientos acaba de ser ocupado. "
                "Consulta nuevamente la disponibilidad."
            ),
            cantidad=cantidad
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
    return datos if isinstance(datos, dict) else None


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
            return jsonify({
                "error": "Error al consultar películas"
            }), 503

    datos = leer_json()

    if datos is None:
        return jsonify({
            "error": "Envía un objeto JSON válido"
        }), 400

    datos.pop("_id", None)

    if not datos.get("titulo") and not datos.get("nombre"):
        return jsonify({
            "error": "El título es obligatorio"
        }), 400

    try:
        if alumnos.count_documents({}) >= MAXIMO_PELICULAS:
            return jsonify({
                "error": "El catálogo admite máximo 15 películas"
            }), 400

        resultado = alumnos.insert_one(datos)

        return jsonify({
            "mensaje": "Película agregada",
            "id": str(resultado.inserted_id)
        }), 201

    except PyMongoError:
        return jsonify({
            "error": "No se pudo guardar la película"
        }), 503


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
                return jsonify({
                    "error": "Película no encontrada"
                }), 404

            pelicula["_id"] = str(pelicula["_id"])
            return jsonify(pelicula), 200

        except PyMongoError:
            return jsonify({"error": "Error al consultar"}), 503

    if request.method == "PUT":
        datos = leer_json()

        if datos is None:
            return jsonify({
                "error": "Envía un objeto JSON válido"
            }), 400

        datos.pop("_id", None)

        try:
            resultado = alumnos.update_one(
                {"_id": object_id},
                {"$set": datos}
            )

            if resultado.matched_count == 0:
                return jsonify({
                    "error": "Película no encontrada"
                }), 404

            return jsonify({
                "mensaje": "Película actualizada"
            }), 200

        except PyMongoError:
            return jsonify({
                "error": "No se pudo actualizar"
            }), 503

    try:
        resultado = alumnos.delete_one({"_id": object_id})

        if resultado.deleted_count == 0:
            return jsonify({
                "error": "Película no encontrada"
            }), 404

        return jsonify({
            "mensaje": "Película eliminada"
        }), 200

    except PyMongoError:
        return jsonify({
            "error": "No se pudo eliminar"
        }), 503


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
        "Verifica MongoDB Atlas y MONGO_URI.",
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
