# Cinepolis

# Descripción del proyecto
Este proyecto es una aplicación web inspirada en Cinépolis, desarrollada para administrar la cartelera de películas, seleccionar asientos y realizar compras de boletos de demostración.
Como parte del proyecto final de Aplicaciones Web, se integró un sistema de reservas temporales y códigos QR para consultar los comprobantes de compra.

# Integrantes
Col Tzuc Jaime Rolando y
Martinez Merlin Alexander

# Problema que resuelve
Permite a los usuarios consultar películas, seleccionar funciones y asientos, y reservar temporalmente sus lugares para evitar que dos usuarios seleccionen el mismo asiento.

# Funciones principales

- Cartelera de películas.
- Selección de fecha y horario.
- Selección de asientos.
- Reserva temporal de 5 minutos.
- Contador de tiempo restante.
- Bloqueo de asientos reservados.
- Cancelación de reservas.
- Liberación automática de reservas vencidas.
- Confirmación de compra.
- Generación de código QR.
- Consulta del comprobante y estado actualizado de la reserva.

# Recurso que se reserva
El recurso principal son los asientos disponibles de una función de cine.
Cada reserva queda relacionada con una película, fecha, horario y asientos seleccionados.

# Duración de la reserva
La reserva temporal tiene una duración de 5 minutos. Si el usuario no confirma la compra dentro de ese tiempo, la reserva vence y los asientos vuelven a estar disponibles.

# Función del código QR
El código QR contiene un enlace público al comprobante de la reserva.
Al escanearlo desde un celular, se pueden consultar los datos de la función y el estado actual de la reserva.

# Tecnologías utilizadas

- Python
- Flask
- HTML
- CSS
- Bootstrap
- JavaScript
- MongoDB Atlas
- PyMongo
- Gunicorn
- qrcode

# Base de datos
Se utiliza MongoDB Atlas para almacenar la información del proyecto.

Base de datos: `cinepolis`

Colecciones principales:
- `reservas`
- `compras`

## Instalación y ejecución local

1. Clonar el repositorio:

```bash
git clone https://github.com/coltzucjaimerolandocbtis272-lap/cinepolis.git
```

2. Entrar a la carpeta:

```bash
cd cinepolis
```

3. Crear un entorno virtual:

```bash
python -m venv .venv
```

4. Activar el entorno virtual en Windows:

```powershell
.venv\Scripts\Activate
```

5. Instalar las dependencias:

```bash
pip install -r requirements.txt
```

6. Configurar las variables de entorno necesarias.

7. Ejecutar la aplicación:

```bash
python app.py
```

# Variables de entorno

Configurar en el entorno de ejecución:

- `MONGO_URI`: cadena de conexión de MongoDB Atlas.
- `FLASK_SECRET_KEY`: clave secreta de Flask.

No compartir ni publicar estas credenciales.

# Publicación

Aplicación publicada en Render:
https://cinepolis-imuz.onrender.com/

Repositorio de GitHub:
https://github.com/coltzucjaimerolandocbtis272-lap/cinepolis

# Pruebas realizadas

- Reserva temporal de asientos.
- Bloqueo de asientos para un segundo usuario.
- Cancelación de reservas.
- Vencimiento de reservas.
- Confirmación de compra.
- Persistencia de información en MongoDB Atlas.
- Escaneo del código QR desde un celular.
- Actualización del estado y consulta con el mismo QR.
- Consulta de un comprobante inexistente.

# Conclusión

En conclusión en mi proyecto llamado cinepolis agregamos un generador de código qr y una reserva para los clientes no tengan problemas y sea mas fácil usar nuestra pagina web.
El código qr funciona que cuando confimas tus boletos te da un comprobante y en ese comprobante te da los datos de tu compra y un código qr que ese código sirve para ver tu comprobante desde otro dispositivo y cuando lo escanes te llevará directo a tu comprobante de tu compra dónde te mostrará tus datos que pusiste y se esa manera mostrando tu comprobante podrás entrar a las salas de nuestro cinepolis.
La reserva funciona de esta manera elijes tus boletos,la hora,fecha,dia y el horario de la función  y luego le das en continuar compra te llevará saldra un contador que le da un tiempo estimado de 5 minutos a cada cliente para que tome una decisión de cancelar,editar sus asientos o confirmar su compra y cuando le da en confirmar le saldrá sus datos y un código qr que sirve para ver su comprobante y asi ingresar a las salas.
