# 🩺🤖 Agenda IA Inteligente

**Asistente conversacional inteligente** para gestionar citas y eventos (médicos, reuniones, exámenes, etc.) utilizando:

- **LLMs** (Ollama local y/o Groq en la nube)
- **Streamlit** como interfaz de chat
- **SQLite** para persistencia de citas y memoria conversacional
- **Google Calendar API** para sincronizar eventos reales
- **Lectura de PDF** para extraer automáticamente datos de citas desde documentos

El usuario puede hablar en **lenguaje natural**:

- `"Quiero una cita con el médico de cabecera mañana a las 10"`
- `"¿Qué citas tengo?"`
- `"Cambia mi cita del 10/12/2025 a las 11:30"`
- `"Cancela mi cita del 10 de diciembre"`
- `"Crea una cita con los datos del PDF"`
- `"¿Qué dice el PDF?"`

Y el sistema:

- ✅ Interpreta fechas y horas (incluyendo expresiones como "mañana", "pasado mañana")
- ✅ Usa el email del usuario logueado como contexto
- ✅ Detecta intención y extrae datos automáticamente del texto
- ✅ Genera JSON de acción cuando tiene todos los datos necesarios
- ✅ Sincroniza automáticamente con Google Calendar
- ✅ Lee PDFs y extrae nombre, email, servicio, fecha y hora para crear citas

---

## 📂 Estructura del proyecto

```text
BOTCHAT/
├── backend/
│   ├── agent_rulebased.py      # Extracción de JSON y reglas auxiliares
│   ├── chat_manager.py         # Motor de conversación + integración LLM
│   ├── db.py                   # Conexión y operaciones SQLite
│   ├── google_calendar.py      # Integración con Google Calendar API
│   └── services.py             # Lógica de negocio de citas
├── models/
│   └── appointment.py          # Modelo de datos de citas
├── tokens/
│   └── *.pkl                   # Tokens de usuario (NO SUBIR AL REPO)
├── .gitignore
├── app.py                      # Interfaz de chat con Streamlit
├── botcitas.db                 # Base de datos SQLite
├── credentials.json            # Credenciales OAuth de Google (NO SUBIR)
├── README.md                   # Este archivo
├── requirements.txt            # Dependencias de Python
├── token.json                  # Token de usuario generado al autorizar (NO SUBIR)
└── token.pkl                   # Token alternativo (NO SUBIR)
```

> ⚠️ **Importante**: Los archivos `credentials.json`, `token.json`, `token.pkl` y la carpeta `tokens/` **NO deben subirse al repositorio**. Añádelos a `.gitignore`.

---

## 🛠️ Requisitos

### Software necesario

- **Python 3.9+** (recomendado 3.10 o superior)
- **Ollama** instalado y corriendo (si usas modelo local):
  - Descarga: [https://ollama.com](https://ollama.com)
  - Modelo usado por defecto: `llama3.2:1b` (puedes cambiarlo)
  - Comando para descargar el modelo:
    ```bash
    ollama pull llama3.2:1b
    ```
- **(Opcional)** **Groq API key** si quieres usar un modelo en la nube:
  - Regístrate en: [https://console.groq.com/](https://console.groq.com/)

### Dependencias de Python

Instala las dependencias con:

```bash
pip install -r requirements.txt
```

**Contenido típico de `requirements.txt`:**

```txt
streamlit
langchain-core
langchain-ollama
google-api-python-client
google-auth
google-auth-oauthlib
google-auth-httplib2
dateparser
PyPDF2
python-dotenv
groq
python-dateutil
pytz
```

---

## 🔐 Configuración de Google Calendar API

Para que la app pueda crear, modificar y cancelar eventos en tu Google Calendar, necesitas configurar OAuth 2.0.

### Paso 1: Crear proyecto en Google Cloud Console

1. Ve a [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Crea un nuevo proyecto (por ejemplo, `agenda-ia-medica`)
3. Selecciona el proyecto recién creado

### Paso 2: Activar Google Calendar API

1. En el menú lateral, ve a **"APIs & Services"** → **"Library"**
2. Busca **"Google Calendar API"**
3. Haz clic en **"Enable"** (Habilitar)

### Paso 3: Configurar pantalla de consentimiento OAuth

1. Ve a **"APIs & Services"** → **"OAuth consent screen"**
2. Elige tipo:
   - **"External"** (para pruebas personales)
   - **"Internal"** (si tienes Google Workspace)
3. Rellena la información básica:
   - Nombre de la aplicación: `Agenda IA Médica`
   - Email de soporte: tu email
   - Dominios autorizados: (puedes dejarlo vacío para pruebas locales)
4. En **"Scopes"**, añade:
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
   - `openid`
5. En **"Test users"**, añade tu email (si es External)
6. Guarda y continúa

### Paso 4: Crear credenciales OAuth 2.0

1. Ve a **"APIs & Services"** → **"Credentials"**
2. Haz clic en **"Create Credentials"** → **"OAuth client ID"**
3. Elige tipo de aplicación:
   - **"Desktop app"** (recomendado para pruebas locales)
4. Dale un nombre (por ejemplo, `Agenda IA Desktop`)
5. Haz clic en **"Create"**
6. **Descarga el archivo JSON** de credenciales

### Paso 5: Configurar `credentials.json`

1. Renombra el archivo descargado a:
   ```text
   credentials.json
   ```
2. Colócalo en la **raíz del proyecto** (mismo nivel que `app.py`)

### Paso 6: Generar `token.json` (primera ejecución)

La primera vez que ejecutes la app y hagas clic en **"Iniciar sesión con Google"**:

1. Se abrirá automáticamente una ventana del navegador
2. Inicia sesión con tu cuenta de Google
3. Acepta los permisos solicitados
4. Google generará un `token.json` y un `token.pkl` que se guardarán automáticamente en la carpeta `tokens/`

Estos tokens se reutilizarán en futuras ejecuciones.

> ⚠️ **Si `token.json` se corrompe** (error de UTF-8), simplemente bórralo y deja que se regenere en la próxima ejecución.

---

## ⚙️ Variables de entorno

Puedes configurar variables de entorno para personalizar el comportamiento de la app.

### Opción 1: Archivo `.env`

Crea un archivo `.env` en la raíz del proyecto:

```bash
CURRENT_USER_EMAIL="tucorreo@gmail.com"
GROQ_API_KEY="tu_api_key_de_groq"  # Solo si usas Groq
TIMEZONE="Europe/Madrid"
GOOGLE_CALENDAR_ID="primary"
```

### Opción 2: Variables de sistema

En Linux/Mac:

```bash
export CURRENT_USER_EMAIL="tucorreo@gmail.com"
export GROQ_API_KEY="tu_api_key_de_groq"
export TIMEZONE="Europe/Madrid"
```

En Windows (CMD):

```cmd
set CURRENT_USER_EMAIL=tucorreo@gmail.com
set GROQ_API_KEY=tu_api_key_de_groq
set TIMEZONE=Europe/Madrid
```

### Variables disponibles

| Variable | Descripción | Requerida | Valor por defecto |
|----------|-------------|-----------|-------------------|
| `CURRENT_USER_EMAIL` | Email del usuario "logueado" para asociar citas | ✅ Sí | - |
| `GROQ_API_KEY` | API key de Groq (solo si usas `provider='groq'`) | ❌ No | - |
| `TIMEZONE` | Zona horaria para eventos de Calendar | ❌ No | `Europe/Madrid` |
| `GOOGLE_CALENDAR_ID` | ID del calendario a usar | ❌ No | `primary` |

---

## 🚀 Cómo ejecutar la aplicación

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 2. Configurar Google Calendar

- Asegúrate de tener `credentials.json` en la raíz del proyecto
- Configura `CURRENT_USER_EMAIL` en las variables de entorno (o se configurará automáticamente al iniciar sesión)

### 3. Iniciar Ollama (si usas modelo local)

```bash
ollama serve
```

En otra terminal, verifica que el modelo esté descargado:

```bash
ollama list
```

Si no está, descárgalo:

```bash
ollama pull llama3.2:1b
```

### 4. Ejecutar la app

```bash
streamlit run app.py
```

### 5. Abrir en el navegador

Streamlit mostrará una URL, normalmente:

```
http://localhost:8501
```

Abre esa URL en tu navegador.

---

## 💬 Cómo usar la aplicación

### 1️⃣ Agendar una cita

**Ejemplos de frases:**

- `"Quiero una cita con el médico de cabecera mañana a las 10"`
- `"Ponme una cita de revisión general el 10/12/2025 a las 10:30"`
- `"Agenda una reunión con mi jefe pasado mañana a las 15:00"`

**Flujo:**

1. El sistema detecta la intención de **crear** una cita
2. Extrae automáticamente:
   - **Servicio**: "médico de cabecera", "revisión general", "reunión con mi jefe"
   - **Fecha**: interpreta "mañana", "10/12/2025", "pasado mañana" → formato ISO `YYYY-MM-DD`
   - **Hora**: "a las 10", "10:30", "15:00" → formato `HH:MM`
   - **Nombre y email**: del usuario logueado
3. Genera un JSON con `action: "create"` y todos los datos
4. Crea la cita en:
   - Base de datos SQLite
   - Google Calendar
5. Muestra confirmación con enlace al evento

### 2️⃣ Consultar citas

**Ejemplos de frases:**

- `"¿Qué citas tengo?"`
- `"Ver mis citas"`
- `"Mis citas"`

**Resultado:**

- Genera JSON con `action: "consult"` y tu email como filtro
- Lista todas tus citas futuras desde Google Calendar
- Muestra: título, fecha, hora

### 3️⃣ Cancelar una cita

**Ejemplos de frases:**

- `"Cancela mi cita del 10/12/2025"`
- `"Anula la cita del 2025-12-10"`
- `"Elimina mi cita del 10 de diciembre"`

**Flujo:**

1. Detecta intención de **cancelar**
2. Extrae la fecha del texto
3. Genera JSON con `action: "cancel"` y la fecha como filtro
4. Busca citas con esa fecha en la base de datos
5. Si encuentra una, la borra de:
   - Base de datos SQLite
   - Google Calendar
6. Muestra confirmación

### 4️⃣ Modificar una cita

**Ejemplos de frases:**

- `"Cambia mi cita del 10/12/2025 a las 11:30"`
- `"Reprograma mi cita del 2025-12-10 a las 12:00"`
- `"Mueve mi cita del 10 de diciembre a las 14:00"`

**Flujo:**

1. Detecta intención de **modificar**
2. Extrae:
   - **Fecha original**: "del 10/12/2025"
   - **Nueva fecha y hora**: "a las 11:30"
3. Genera JSON con `action: "modify"`, filtro, nueva_fecha y nueva_hora
4. Busca la cita con la fecha original
5. Actualiza:
   - Base de datos SQLite
   - Evento en Google Calendar
6. Muestra confirmación

### 5️⃣ Uso de PDF

#### Subir un PDF

1. En la barra lateral de Streamlit, haz clic en **"Sube un PDF (opcional)"**
2. Selecciona un PDF con información de una cita (nombre, email, servicio, fecha, hora)
3. El sistema mostrará un preview del contenido extraído

#### Preguntar sobre el PDF

**Ejemplos de frases:**

- `"¿Qué dice el PDF?"`
- `"Resume el PDF"`
- `"Cuéntame sobre el documento"`

**Resultado:**

- El bot lee el PDF y responde en lenguaje natural
- **NO crea ninguna cita**, solo responde preguntas

#### Crear cita desde el PDF

**Ejemplos de frases:**

- `"Crea una cita con los datos del PDF"`
- `"Usa el PDF para agendar la cita"`
- `"Saca los datos del PDF y crea la cita"`

**Flujo:**

1. El sistema extrae automáticamente del PDF:
   - Nombre
   - Email
   - Servicio
   - Fecha (formato ISO: YYYY-MM-DD)
   - Hora (formato HH:MM)
   - Observaciones
2. Genera el JSON de creación con `action: "create"`
3. Crea la cita en BD y Google Calendar

---

## 🧠 Modelos LLM (Ollama / Groq)

### Configuración por defecto

Por defecto, `ChatManagerDB` utiliza:

- **Provider**: Ollama
- **Modelo**: `llama3.2:1b`

### Cambiar el modelo

Puedes cambiar el modelo desde la interfaz de Streamlit:

1. En la barra lateral, selecciona **"Proveedor LLM"**
2. Elige entre:
   - **Ollama (local)**: selecciona un modelo de la lista desplegable
   - **Groq (cloud)**: introduce el nombre del modelo y tu API key

### Modelos recomendados

**Ollama (local):**

- `llama3.2:1b` - Rápido, ligero (recomendado para pruebas)
- `llama3.2:3b` - Mejor calidad, más lento
- `llama3.1:8b` - Alta calidad, requiere más RAM

**Groq (nube):**

- `llama-3.1-8b-instant` - Rápido y preciso
- `llama-3.1-70b-versatile` - Muy bueno para español
- `mixtral-8x7b-32768` - Excelente para tareas complejas

---

## 🔧 Arquitectura técnica

### Componentes principales

#### `app.py`

- Interfaz de usuario con Streamlit
- Maneja el chat y el `file_uploader` para PDFs
- Llama a `ChatManagerDB.ask()` para procesar mensajes
- Ejecuta acciones (create/consult/modify/cancel) según el JSON devuelto
- Integra con Google Calendar a través de `backend/google_calendar.py`
- Gestiona autenticación OAuth con Google

#### `backend/chat_manager.py`

- Motor de conversación con lógica **determinista + LLM**
- **Lógica determinista prioritaria**:
  - Detecta intención por palabras clave: `"agenda"`, `"cancela"`, `"modifica"`, `"qué citas tengo"`
  - Extrae fecha y hora con `dateparser` (interpreta "mañana", "10/12/2025", etc.)
  - Extrae servicio con diccionario de patrones
  - Genera JSON directamente cuando tiene todos los datos
- **LLM como fallback**:
  - Solo se usa cuando la lógica determinista no puede resolver
  - Mantiene memoria de conversación en SQLite
  - Soporta Ollama (local) y Groq (nube)
- **Manejo de PDF**:
  - Detecta si el usuario pregunta sobre el PDF o quiere usarlo para crear cita
  - Extrae datos estructurados del PDF con el LLM

#### `backend/db.py`

- Capa de acceso a datos SQLite
- Tablas:
  - `usuarios` - Información de usuarios (id, nombre, email, token_path)
  - `citas` - Citas agendadas (id_cita, usuario_id, fecha, hora, tipo, descripcion, id_evento_google)
  - `memoria_chat` - Historial de conversación (id_memoria, usuario_id, fecha, mensaje_usuario, respuesta_bot)
- Funciones principales:
  - `init_db()` - Inicializa la base de datos
  - `execute_query()`, `query_all()`, `query_one()` - Operaciones SQL
  - `get_user_by_email()` - Obtiene usuario por email
  - `upsert_user_token()` - Guarda/actualiza token de usuario

#### `backend/services.py`

- Lógica de alto nivel sobre citas
- Funciones principales:
  - `add_appointment()` - Crea cita en la base de datos
  - `set_event_id_for_appointment()` - Asocia `event_id` de Google Calendar
  - `list_appointments()` - Lista/filtra citas (soporta búsqueda por fecha)
  - `find_appointment()` - Busca cita específica
  - `update_appointment()` - Modifica cita existente
  - `delete_appointment()` - Elimina cita
  - `extract_text_from_pdf_bytes()` - Extrae texto de PDF

#### `backend/google_calendar.py`

- Integración con Google Calendar API
- Gestión de credenciales OAuth (`credentials.json`, `token.json`)
- Funciones principales:
  - `get_service()` - Obtiene cliente autenticado de Google Calendar
  - `create_event()` - Crea evento en Calendar
  - `update_event()` - Modifica evento existente (mantiene duración original)
  - `delete_event()` - Elimina evento
  - `get_future_events()` - Lista eventos futuros del calendario
- Manejo robusto de errores:
  - Detecta tokens corruptos o vacíos
  - Regenera automáticamente si es necesario
  - Refresca tokens expirados

#### `backend/agent_rulebased.py`

- Funciones auxiliares para extracción de datos
- `extract_json_block(text)` - Extrae bloques JSON de respuestas del LLM
  - Soporta formato con ` ```json ... ``` `
  - Soporta JSON directo `{ ... }`

#### `models/appointment.py`

- Modelo de datos de citas (dataclass)
- Campos:
  - `id`, `nombre`, `email`, `servicio`
  - `fecha_texto`, `fecha_iso`, `hora_texto`, `hora_iso`
  - `observaciones`, `confianza`, `gcal_event_id`, `created_at`
- Método `to_dict()` para serialización

---

## 🔒 Seguridad y buenas prácticas

### Archivos sensibles

**NO subas al repositorio:**

- `credentials.json` - Credenciales OAuth de Google
- `token.json` - Token de acceso generado
- `token.pkl` - Token alternativo
- `tokens/` - Carpeta con tokens de usuarios
- `.env` - Variables de entorno
- `botcitas.db` - Base de datos (contiene datos personales)

**Añádelos a `.gitignore`:**

```gitignore
credentials.json
token.json
token.pkl
tokens/
.env
__pycache__/
*.pyc
*.db
botcitas.db
```

### Si `token.json` se corrompe

Si ves un error como:

```
'utf-8' codec can't decode byte 0x80...
```

**Solución:**

1. Borra los tokens:
   ```bash
   rm token.json token.pkl
   rm -rf tokens/
   ```
2. Ejecuta la app de nuevo
3. Haz clic en **"Iniciar sesión con Google"**
4. Se abrirá el navegador para reautorizar
5. Se generarán nuevos tokens válidos

### Límites de API

- **Google Calendar API**: 1,000,000 de solicitudes/día (gratis)
- **Groq**: Depende de tu plan (revisa en [console.groq.com](https://console.groq.com/))
- **Ollama**: Sin límites (local)

---

**¡Disfruta de tu asistente de citas inteligente! 🩺🤖**
