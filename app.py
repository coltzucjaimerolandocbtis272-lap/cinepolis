
from flask import (
    Flask, render_template, request, redirect,
    url_for, abort, jsonify, session
)
from pymongo import MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError
from bson import ObjectId
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os
import uuid
import qrcode
import base64
from io import BytesIO

app = Flask(__name__)
def generar_qr_reserva(reserva_id):
    base_url = os.environ.get(
        "PUBLIC_BASE_URL",
        "https://cinepolis-imuz.onrender.com"
    ).rstrip("/")

    enlace = f"{base_url}/comprobante/{reserva_id}"

    imagen = qrcode.make(enlace)

    buffer = BytesIO()
    imagen.save(buffer, format="PNG")

    qr_base64 = base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")

    return qr_base64

app.secret_key = os.environ.get("FLASK_SECRET_KEY")

if not app.secret_key:
    if os.environ.get("RENDER"):
        raise RuntimeError("Falta configurar FLASK_SECRET_KEY en Render.")
    app.secret_key = "clave-local-cinepolis-desarrollo"

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
compras_alimentos = base_datos["compras_alimentos"]
reservas = base_datos["reservas"]

# =========================
# CONFIGURACIÓN
# =========================

ZONA_HORARIA = ZoneInfo("America/Cancun")
PRECIO_BOLETO = 80
DURACION_RESERVA_MINUTOS = 5
MAXIMO_PELICULAS = 15

DURACION_MINIMA = 1
DURACION_MAXIMA = 600

HORARIOS_VALIDOS = ["12:00", "15:00", "18:00", "21:00"]
ASIENTOS_VALIDOS = list(range(1, 49))
MAXIMO_ASIENTOS = len(ASIENTOS_VALIDOS)

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


def obtener_reserva_id():
    if "reserva_id" not in session:
        session["reserva_id"] = str(uuid.uuid4())

    return session["reserva_id"]


def ahora_utc():
    return datetime.now(timezone.utc)


def liberar_reservas_vencidas():
    ahora = ahora_utc()

    reservas.update_many(
        {
            "estado": "Activa",
            "vence_en": {"$lte": ahora}
        },
        {
            "$set": {"estado": "Vencida"}
        }
    )

    asientos.delete_many({
        "estado": "Reservado",
        "vence_en": {"$lte": ahora}
    })


def reservar_asientos_temporalmente(
    pelicula, fecha, horario, seleccionados
):
    liberar_reservas_vencidas()

    reserva_id = str(uuid.uuid4())
    visitante_id = obtener_reserva_id()
    ahora = ahora_utc()
    vence_en = ahora + timedelta(
        minutes=DURACION_RESERVA_MINUTOS
    )

    documentos_insertados = []

    try:
        for numero in seleccionados:
            resultado = asientos.insert_one({
                "pelicula_id": str(pelicula["_id"]),
                "titulo_pelicula": pelicula.get(
                    "titulo", pelicula.get("nombre", "")
                ),
                "fecha": fecha,
                "horario": horario,
                "asiento": numero,
                "estado": "Reservado",
                "reserva_id": reserva_id,
                "visitante_id": visitante_id,
                "fecha_registro": ahora,
                "vence_en": vence_en
            })

            documentos_insertados.append(resultado.inserted_id)

        reservas.insert_one({
            "reserva_id": reserva_id,
            "visitante_id": visitante_id,
            "pelicula_id": str(pelicula["_id"]),
            "fecha": fecha,
            "horario": horario,
            "asientos": seleccionados,
            "estado": "Activa",
            "creada_en": ahora,
            "vence_en": vence_en
        })

        session["reserva_activa_id"] = reserva_id

        return True, vence_en

    except DuplicateKeyError:
        if documentos_insertados:
            asientos.delete_many({
                "_id": {"$in": documentos_insertados}
            })

        return False, (
            "Uno o más asientos acaban de ser reservados "
            "por otra persona. Consulta nuevamente."
        )

    except PyMongoError:
        if documentos_insertados:
            asientos.delete_many({
                "_id": {"$in": documentos_insertados}
            })

        raise


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

    poster_actual = (
        pelicula.get("poster")
        or pelicula.get("poster_url")
        or ""
    ).strip()

    if poster_actual:
        return pelicula

    titulo = pelicula.get(
        "titulo", pelicula.get("nombre", "")
    ).lower().strip()

    posters = {
        "cars": "Cars.webp",
        "coco": "Coco.jpg",
        "intensamente 2": "Intensamente 2.jpg",
        "jurassic world": "Jurassic World.jpg",
        "spider-man": "spiderman-brand-new-day.jpg",
        "spiderman": "spiderman-brand-new-day.jpg",
        "super mario bros": "Super Mario Bros.jpg",
    }

    for nombre, archivo in posters.items():
        if nombre in titulo:
            pelicula["poster"] = url_for(
                "static",
                filename=f"posters/{archivo}"
            )
            break

    return pelicula


def leer_formulario():
    nombre = request.form.get(
        "nombre", request.form.get("titulo", "")
    ).strip()

    categoria = request.form.get(
        "categoria", request.form.get("genero", "")
    ).strip()

    duracion_texto = request.form.get(
        "duracion", ""
    ).strip()

    try:
        duracion = int(duracion_texto)
    except (ValueError, TypeError):
        duracion = None

    return {
        "nombre": nombre,
        "titulo": nombre,
        "categoria": categoria,
        "duracion": duracion,
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


def consultar_asientos_ocupados(pelicula_id, fecha, horario):
    liberar_reservas_vencidas()

    documentos = asientos.find({
        "pelicula_id": str(pelicula_id),
        "fecha": fecha,
        "horario": horario,
        "estado": {"$in": ["Ocupado", "Reservado"]}
    })

    ocupados = set()

    for documento in documentos:
        valor = documento.get("asiento")

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
        return None, (
            f"Solo puedes seleccionar hasta "
            f"{MAXIMO_ASIENTOS} asientos."
        )

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

    if not 1 <= cantidad <= len(ASIENTOS_VALIDOS):
        return None

    return cantidad


def mostrar_mapa(
    pelicula,
    fecha,
    horario,
    mensaje_error=None,
    cantidad=1
):
    todos_ocupados = consultar_asientos_ocupados(
        pelicula["_id"], fecha, horario
    )

    documentos_reservados = asientos.find({
        "pelicula_id": str(pelicula["_id"]),
        "fecha": fecha,
        "horario": horario,
        "estado": "Reservado"
    })

    reservados = set()

    for documento in documentos_reservados:
        valor = documento.get("asiento")

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
            reservados.add(numero)

    ocupados = sorted(set(todos_ocupados) - reservados)

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
        asientos_reservados=sorted(reservados),
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
# ALIMENTOS
# =========================

PRECIOS_ALIMENTOS = {
    # NUEVOS LANZAMIENTOS
    "Hot Dog Doritos": 145,
    "Hot Dog Chips Jalapeño": 145,
    "M&M Mega Peanut Butter": 86,
    "Solero Paradise®": 65,

    # COMBOS
    "Combo Clásico": 278,
    "Combo Nachos en Pareja": 367,
    "Combo Junior": 264,
    "Combo Ciel®": 187,
    "Combo Cuates": 298,
    "Combo Nachos": 282,
    "Combo Cornetto®": 257,
    "Combo Magnum®": 270,
    "Combo Snickers® con Hot Dog": 350,
    "Combo Lifesavers®": 377,
    "Combo ICEE® con Skwinkles®": 350,
    "Combo M&M's® con Nachos": 350,
    "Combo Skittles®": 372,
    "Combo Micha": 382,

    # PARA COMPARTIR
    "Maxicombo Personalizado Jumbo": 550,
    "Maxicombo Personalizado P/Llevar": 480,
    "Maxicombo Familiar Jumbo": 534,
    "Maxicombo Familiar": 490,
    "Maxicombo Micha Mix": 492,
    "Maxicombo Mix": 440,
    "Maxicombo M&M's® Para Lllevar": 480,
    "Maxicombo M&M's® Jumbo": 520,
    "Maxicombo Nachos Grandes": 460,
    "Maxicombo Nachos": 442,
    "Maxicombo Hot Dog": 432,

    # CLÁSICOS
    "Refresco": 109,
    "Nachos": 105,
    "Palomitas": 107,
    "Hot Dog Individual": 127,
    "Agua Embotellada": 42,
    "ICEE®": 115,

    # SNACKS
    "Hot Dog Takis": 145,
    "Papas Fritas": 75,
    "Extra Queso": 27,
    "Extra Guacamole": 30,

    # HELADOS
    "Cornetto®.": 53,
    "Magnum®.": 65,
    "Mordisko® Oreo®": 55,
    "Helado Micha": 60,

    # DULCES Y CHOCOLATES
    "Milky Way®": 45,
    "Hershey's® Cookies And Cream": 51,
    "Skittles® Pouch": 79,
    "Hershey's® Cookies And Cream King Size": 75,
    "Pon Pons®": 50,
    "Lifesavers®": 85,
    "Skwinkles® Chunks sandia": 78,
    "Snickers®": 45,
    "Skwinkles® Salsagheti": 45,
    "Pelón Pelonazo®": 45,
    "Skittles®": 79,
    "Skwinkles® Rellenos": 45,
    "M&M's®": 55,
    "M&M's® Mega": 86,
    "Vaso Granel": 89,
    "Ositos Enchilados Cinépolis": 89,
    "Aritos Enchilados Cinépolis": 89,
    "Aritos Ácidos Cinépolis": 89,
    "Skittles gomitas": 79,
    "Hershey's": 51,

    # PRODUCTOS ANTERIORES QUE CONSERVAMOS
    "Hot dogs": 127,
    "Papas fritas": 75
}


@app.route("/alimentos")
def alimentos():
    return render_template(
        "alimentos.html",
        precios=PRECIOS_ALIMENTOS,
        compra_confirmada=False,
        total=0,
        productos_seleccionados=[]
    )


@app.route("/comprar-alimentos", methods=["GET", "POST"])
def comprar_alimentos():
    if request.method == "GET":
        return redirect(url_for("alimentos"))

    productos_seleccionados = []
    total = 0

    for producto, precio in PRECIOS_ALIMENTOS.items():
        try:
            cantidad = int(request.form.get(producto, "0"))
        except (ValueError, TypeError):
            cantidad = 0

        if cantidad < 0 or cantidad > 50:
            return render_template(
                "alimentos.html",
                precios=PRECIOS_ALIMENTOS,
                compra_confirmada=False,
                total=0,
                productos_seleccionados=[],
                mensaje_error="Selecciona cantidades entre 0 y 50."
            )

        if cantidad == 0:
            continue

        detalle = {
            "producto": producto,
            "precio": precio,
            "cantidad": cantidad,
            "subtotal": cantidad * precio
        }

        if producto == "ICEE®":
            detalle["sabor"] = request.form.get(
                "sabor_ICE", "Mora roja"
            )

            if detalle["sabor"] not in ["Mora roja", "Mora azul"]:
                detalle["sabor"] = "Mora roja"

        if producto == "Papas Fritas":
            detalle["preparacion"] = request.form.get(
                "tipo_papas", "Naturales"
            )

            if detalle["preparacion"] not in [
                "Naturales", "Con chile"
            ]:
                detalle["preparacion"] = "Naturales"

        productos_seleccionados.append(detalle)
        total += detalle["subtotal"]

    if not productos_seleccionados:
        return render_template(
            "alimentos.html",
            precios=PRECIOS_ALIMENTOS,
            compra_confirmada=False,
            total=0,
            productos_seleccionados=[],
            mensaje_error="Selecciona al menos un alimento."
        )

    compra = {
        "productos": productos_seleccionados,
        "total": total,
        "fecha_compra": ahora_local(),
        "tipo": "alimentos"
    }

    try:
        resultado = compras_alimentos.insert_one(compra)

        return render_template(
            "alimentos.html",
            precios=PRECIOS_ALIMENTOS,
            compra_confirmada=True,
            total=total,
            productos_seleccionados=productos_seleccionados,
            folio=str(resultado.inserted_id)
        )

    except PyMongoError:
        abort(503)


# =========================
# PELÍCULAS REGISTRADAS
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
    if request.method == "GET":
        total_peliculas = alumnos.count_documents({})

        return render_template(
            "agregar.html",
            total_peliculas=total_peliculas,
            error=request.args.get("error")
        )

    nombre = request.form.get("nombre", "").strip()
    categoria = request.form.get("categoria", "").strip()
    estado = request.form.get("estado", "").strip()
    duracion_texto = request.form.get("duracion", "").strip()

    try:
        duracion = int(duracion_texto)
    except (ValueError, TypeError):
        duracion = None

    if (
        not nombre
        or not categoria
        or duracion is None
        or not DURACION_MINIMA <= duracion <= DURACION_MAXIMA
        or estado not in ["Disponible", "Agotado"]
    ):
        return redirect(url_for("agregar") + "?error=datos")

    try:
        if alumnos.count_documents({}) >= MAXIMO_PELICULAS:
            return redirect(url_for("agregar") + "?error=limite")

        alumnos.insert_one({
            "nombre": nombre,
            "titulo": nombre,
            "categoria": categoria,
            "duracion": duracion,
            "estado": estado
        })

        return redirect(
            url_for("peliculas_registradas") + "?agregada=1"
        )

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

        if not datos["nombre"]:
            return render_template(
                "editar.html",
                pelicula=pelicula,
                mensaje_error="Escribe el nombre de la película."
            )

        if not datos["categoria"]:
            return render_template(
                "editar.html",
                pelicula=pelicula,
                mensaje_error="Escribe la categoría de la película."
            )

        if (
            datos["duracion"] is None
            or not DURACION_MINIMA <= datos["duracion"] <= DURACION_MAXIMA
        ):
            return render_template(
                "editar.html",
                pelicula=pelicula,
                mensaje_error=(
                    "La duración debe ser un número "
                    "entre 1 y 600 minutos."
                )
            )

        if datos["estado"] not in ["Disponible", "Agotado"]:
            return render_template(
                "editar.html",
                pelicula=pelicula,
                mensaje_error="Selecciona un estado válido."
            )

        try:
            alumnos.update_one(
                {"_id": pelicula["_id"]},
                {"$set": datos}
            )

            return redirect(url_for("peliculas_registradas"))

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
            return redirect(
                url_for("peliculas_registradas") + "?eliminada=1"
            )
        except PyMongoError:
            abort(503)

    aplicar_poster(pelicula)
    return render_template("eliminar.html", pelicula=pelicula)


@app.route("/comprobante/<reserva_id>")
def comprobante_reserva(reserva_id):
    try:
        liberar_reservas_vencidas()

        reserva = reservas.find_one({
            "reserva_id": reserva_id
        })

        if not reserva:
            abort(404)

        pelicula = buscar_alumno(
            reserva.get("pelicula_id", "")
        )

        if pelicula:
            aplicar_poster(pelicula)

        return render_template(
            "comprobante.html",
            reserva=reserva,
            pelicula=pelicula
        )

    except PyMongoError:
        abort(503)

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
        mensaje_cantidad = (
            f"Selecciona entre 1 y {MAXIMO_ASIENTOS} boletos."
        )

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

    if accion not in ["consultar", "continuar", "confirmar", "cancelar"]:
        abort(400)

    if accion == "cancelar":
        reserva_id = session.get("reserva_activa_id")

        if reserva_id:
            try:
                reservas.update_one(
                    {
                        "reserva_id": reserva_id,
                        "visitante_id": obtener_reserva_id(),
                        "estado": "Activa"
                    },
                    {
                        "$set": {"estado": "Cancelada"}
                    }
                )

                asientos.delete_many({
                    "reserva_id": reserva_id,
                    "estado": "Reservado"
                })

                session.pop("reserva_activa_id", None)

            except PyMongoError:
                abort(503)

        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error="La reserva fue cancelada. Puedes seleccionar otros asientos.",
            cantidad=cantidad
        )

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

    reserva_id = session.get("reserva_activa_id")
    asientos_propios = set()

    if accion == "confirmar":
        reserva = reservas.find_one({
            "reserva_id": reserva_id,
            "visitante_id": obtener_reserva_id(),
            "estado": "Activa",
            "vence_en": {"$gt": ahora_utc()},
            "pelicula_id": str(pelicula["_id"]),
            "fecha": fecha,
            "horario": horario
        }) if reserva_id else None

        if not reserva:
            liberar_reservas_vencidas()
            session.pop("reserva_activa_id", None)

            return mostrar_mapa(
                pelicula,
                fecha,
                horario,
                mensaje_error=(
                    "Tu reserva venció o ya no está activa. "
                    "Selecciona los asientos nuevamente."
                ),
                cantidad=cantidad
            )

        asientos_propios = set(reserva.get("asientos", []))

        if asientos_propios != set(seleccionados):
            return mostrar_mapa(
                pelicula,
                fecha,
                horario,
                mensaje_error=(
                    "Los asientos de la reserva no coinciden. "
                    "Selecciona nuevamente."
                ),
                cantidad=cantidad
            )

    ocupados_otros = [
        numero for numero in ocupados
        if numero not in asientos_propios
    ]

    disponibles = len(ASIENTOS_VALIDOS) - len(ocupados_otros)

    if cantidad > disponibles:
        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error=(
                f"Solo quedan {disponibles} asientos disponibles "
                "para esta función."
            ),
            cantidad=max(1, min(cantidad, disponibles))
        )

    repetidos = [
        numero for numero in seleccionados
        if numero in ocupados_otros
    ]

    if repetidos:
        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error=(
                "Estos asientos ya están ocupados o reservados: "
                + ", ".join(map(str, repetidos))
                + ". Consulta de nuevo la disponibilidad."
            ),
            cantidad=cantidad
        )

    total = cantidad * PRECIO_BOLETO

    if accion == "continuar":
        try:
            reservada, vence_en = reservar_asientos_temporalmente(
                pelicula, fecha, horario, seleccionados
            )
        except PyMongoError:
            abort(503)

        if not reservada:
            return mostrar_mapa(
                pelicula,
                fecha,
                horario,
                mensaje_error=vence_en,
                cantidad=cantidad
            )

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
            vence_en=vence_en,
            mensaje_error=None
        )

    reserva_id = session.get("reserva_activa_id")

    if not reserva_id:
        return mostrar_mapa(
            pelicula,
            fecha,
            horario,
            mensaje_error="Tu reserva no está activa. Selecciona los asientos nuevamente.",
            cantidad=cantidad
        )

    try:
        reserva = reservas.find_one({
            "reserva_id": reserva_id,
            "visitante_id": obtener_reserva_id(),
            "estado": "Activa",
            "vence_en": {"$gt": ahora_utc()},
            "pelicula_id": str(pelicula["_id"]),
            "fecha": fecha,
            "horario": horario
        })

        if not reserva or set(reserva.get("asientos", [])) != set(seleccionados):
            session.pop("reserva_activa_id", None)
            liberar_reservas_vencidas()
            return mostrar_mapa(
                pelicula,
                fecha,
                horario,
                mensaje_error="Tu reserva venció o ya no está disponible. Selecciona los asientos nuevamente.",
                cantidad=cantidad
            )

        resultado_actualizacion = asientos.update_many(
            {
                "reserva_id": reserva_id,
                "estado": "Reservado",
                "vence_en": {"$gt": ahora_utc()},
                "asiento": {"$in": seleccionados}
            },
            {
                "$set": {"estado": "Ocupado"}
            }
        )

        if resultado_actualizacion.modified_count != len(seleccionados):
            asientos.update_many(
                {
                    "reserva_id": reserva_id,
                    "estado": "Ocupado",
                    "asiento": {"$in": seleccionados}
                },
                {
                    "$set": {"estado": "Reservado"}
                }
            )

            return mostrar_mapa(
                pelicula,
                fecha,
                horario,
                mensaje_error=(
                    "No se pudieron confirmar todos los asientos. "
                    "Tu reserva sigue activa; intenta nuevamente."
                ),
                cantidad=cantidad
            )

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

        reservas.update_one(
            {"reserva_id": reserva_id},
            {"$set": {"estado": "Confirmada"}}
        )

        session.pop("reserva_activa_id", None)

        return render_template(
            "comprar.html",
            pelicula=pelicula,
            compra_confirmada=True,
            confirmar=False,
            folio=str(resultado_compra.inserted_id),
            qr_reserva=generar_qr_reserva(reserva_id),
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

    except PyMongoError:
        if "resultado_compra" not in locals():
            try:
                asientos.update_many(
                    {
                        "reserva_id": reserva_id,
                        "estado": "Ocupado",
                        "asiento": {"$in": seleccionados}
                    },
                    {
                        "$set": {"estado": "Reservado"}
                    }
                )
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

    if "duracion" in datos:
        try:
            duracion = int(datos["duracion"])
        except (ValueError, TypeError):
            return jsonify({
                "error": "La duración debe ser un número entero"
            }), 400

        if not DURACION_MINIMA <= duracion <= DURACION_MAXIMA:
            return jsonify({
                "error": "La duración debe estar entre 1 y 600 minutos"
            }), 400

        datos["duracion"] = duracion

    if "categoria" not in datos and "genero" in datos:
        datos["categoria"] = datos["genero"]

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

        if "duracion" in datos:
            try:
                duracion = int(datos["duracion"])
            except (ValueError, TypeError):
                return jsonify({
                    "error": "La duración debe ser un número entero"
                }), 400

            if not DURACION_MINIMA <= duracion <= DURACION_MAXIMA:
                return jsonify({
                    "error": "La duración debe estar entre 1 y 600 minutos"
                }), 400

            datos["duracion"] = duracion

        if "categoria" not in datos and "genero" in datos:
            datos["categoria"] = datos["genero"]

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
