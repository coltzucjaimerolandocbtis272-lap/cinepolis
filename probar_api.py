import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = "https://cinepolis-imuz.onrender.com"


def pedir(metodo, ruta, datos=None):
    cuerpo = None if datos is None else json.dumps(
        datos, ensure_ascii=False
    ).encode("utf-8")

    peticion = Request(
        BASE + ruta,
        data=cuerpo,
        method=metodo,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urlopen(peticion, timeout=30) as respuesta:
            texto = respuesta.read().decode("utf-8")
            print(f"{metodo} {ruta} -> {respuesta.status} {texto}")
            return respuesta.status, (
                json.loads(texto) if texto else None
            )

    except HTTPError as error:
        texto = error.read().decode("utf-8")
        print(f"{metodo} {ruta} -> {error.code} {texto}")

        try:
            contenido = json.loads(texto) if texto else None
        except json.JSONDecodeError:
            contenido = texto

        return error.code, contenido

    except URLError as error:
        print("No se pudo conectar con Flask:", error.reason)
        return None, None


def ejecutar_pruebas():
    print("\n--- 1. Registrar una película ---")

    estado, producto = pedir("POST", "/api/productos", {
        "nombre": "Prueba API",
        "categoria": "Animación",
        "estado": "Disponible"
    })

    if estado != 201 or not isinstance(producto, dict):
        print("No se pudo registrar la película. Revisa el error.")
        return

    identificador = producto["id"]
    ruta = "/api/productos/" + identificador

    print("\n--- 2. Consultar la película ---")
    pedir("GET", ruta)

    print("\n--- 3. Editar la película ---")
    pedir("PUT", ruta, {
        "nombre": "Prueba API",
        "categoria": "Animación",
        "estado": "Agotado"
    })

    print("\n--- 4. Consultar todas las películas ---")
    pedir("GET", "/api/productos")

    print("\n--- 5. Rechazar un estado inválido ---")
    pedir("POST", "/api/productos", {
        "nombre": "Prueba inválida",
        "categoria": "Animación",
        "estado": "Inventado"
    })

    print("\n--- 6. Rechazar un identificador inválido ---")
    pedir("GET", "/api/productos/no-es-un-id")

    print("\n--- 7. Eliminar la película de prueba ---")
    pedir("DELETE", ruta)

    print("\n--- 8. Comprobar la lista final ---")
    pedir("GET", "/api/productos")

    print("\nPruebas terminadas.")


if __name__ == "__main__":
    ejecutar_pruebas()