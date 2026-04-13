# 🩺🤖 Agenda IA Inteligente (Versión 1.0 - Stable)

**Asistente conversacional avanzado** para gestionar citas y eventos (médicos, reuniones, exámenes, etc.) implementando una arquitectura Multi-Agente de última generación.

Esta evolución del proyecto integra las siguientes tecnologías clave:
- **CrewAI (Sistemas Multi-Agente):** Flujo secuencial con agentes especializados (Analista y Gestor) para evitar alucinaciones y mantener memoria a corto plazo.
- **Function Calling:** Conexión real y determinista entre el LLM, bases de datos locales y APIs externas.
- **RAG (Retrieval-Augmented Generation):** Uso de ChromaDB y Ollama para dotar a la IA de capacidad para leer y responder basándose en documentos PDF privados.
- **Soporte Multiusuario:** Sesiones persistentes (Cookies) y aislamiento de tokens OAuth (`.json`) para que múltiples usuarios interactúen con sus calendarios de forma segura.
- **Business Intelligence:** Panel de control oculto para la visualización de métricas y analíticas.

---

## 📂 Estructura del proyecto

```text
BOTCHAT/
├── backend/
│   ├── crew_manager.py         # Orquestación del sistema Multi-Agente (CrewAI)
│   ├── tools_openai.py         # Herramientas de Function Calling (CRUD y RAG)
│   ├── db.py                   # Conexión, operaciones SQLite y consultas del Dashboard
│   ├── google_calendar.py      # Integración con Google Calendar API (Multiusuario)
│   └── services.py             # Lógica de negocio y motor de vectorización ChromaDB
├── models/
│   └── appointment.py          # Modelo de datos de citas (Dataclass)
├── tokens/
│   └── *.json                  # Tokens OAuth de cada usuario (NO SUBIR AL REPO)
├── chroma_db_data/             # Base de datos vectorial persistente (NO SUBIR AL REPO)
├── .gitignore
├── app.py                      # Interfaz gráfica Streamlit + Panel Admin
├── botcitas.db                 # Base de datos SQLite local
├── credentials.json            # Credenciales OAuth 2.0 de Google (NO SUBIR AL REPO)
├── README.md                   # Este archivo
└── requirements.txt            # Dependencias del proyecto
```

---
## 🛠️ Requisitos e Instalación

### 1. Software necesario
- **Python 3.10+**
- **Ollama** instalado y ejecutándose localmente para la vectorización (RAG):
  - Descarga: [https://ollama.com](https://ollama.com)
  - Comando para descargar el modelo de embeddings: `ollama pull llama3.2:1b`
- **Groq API key** para el motor de CrewAI:
  - Regístrate en: [https://console.groq.com/](https://console.groq.com/)

### 2. Instalación de dependencias
Abre una terminal en la raíz del proyecto y ejecuta:

```bash
pip install -r requirements.txt
```

---
## 🔐 Configuración de Google Calendar API (OAuth 2.0)

Para que la aplicación pueda interactuar con calendarios reales, es necesario configurar un proyecto en la consola de desarrolladores de Google:

1. Accede a **Google Cloud Console**: [https://console.cloud.google.com/](https://console.cloud.google.com/).
2. **Crea un nuevo proyecto** (ej. "Agenda IA Médica").
3. En el menú lateral, ve a **"APIs y servicios"** > **"Biblioteca"** y habilita la **"Google Calendar API"**.
4. Configura la **"Pantalla de consentimiento OAuth"** (*OAuth consent screen*) añadiendo los permisos (*scopes*) necesarios: `calendar.events`, `userinfo.email` y `userinfo.profile`.
5. Crea credenciales de tipo **"ID de cliente de OAuth"** con el tipo de aplicación **"App de escritorio"**.
6. Descarga el archivo JSON de credenciales, cámbiale el nombre a `credentials.json` y colócalo en la carpeta raíz del proyecto.
7. Al iniciar la aplicación y pulsar en **"Conectar Google Calendar"**, el sistema generará automáticamente el token de acceso en la carpeta `/tokens/`.

---
## 🚀 Cómo ejecutar la aplicación
### 1. Configura tus variables en un archivo .env en la raíz:
```bash
GROQ_API_KEY="tu_api_key_de_groq"
TIMEZONE="Europe/Madrid"
COOKIES_PASSWORD="una_contraseña_segura_para_encriptar_cookies"
```
### 2. Asegúrate de que Ollama este corriendo:
```bash
ollama service
```
### 3. Ejecuta streamlit: 
streamlit run app.py
### 4. Abre tu navegador en https://localhost:8501

---
## 💬 Guía de Uso

### 👤 Perfil Paciente / Usuario
* **Interacción Natural:** El sistema recuerda el contexto de la charla. Puedes decir: *"Necesito cita para una revisión"* y, en el siguiente mensaje, *"Mejor ponla el próximo jueves a las 10"*. El **Agente Analista** fusionará ambas intenciones para completar la solicitud.
* **Sincronización Total:** Todas las operaciones (**Crear, Modificar, Consultar, Eliminar**) se reflejan inmediatamente tanto en tu **Google Calendar** como en la **base de datos local** SQLite.
* **RAG de Normativas:** Sube un PDF a través de la barra lateral. Podrás preguntar a la IA sobre requisitos específicos (ej. *"¿Qué requisitos de ayuno hay en el documento?"*) y la IA responderá basándose estrictamente en el texto del archivo.
* **Sesiones Persistentes:** Si recargas la página o vuelves en otro momento, la aplicación recordará tu inicio de sesión gracias al gestor de **cookies encriptadas**.

---

### 🛡️ Perfil Administrador (Dashboard BI)
La aplicación cuenta con un módulo de **Inteligencia de Negocio** oculto para la gestión global:

1. Abre el desplegable **"Acceso Admin"** en la barra lateral.
2. Activa el interruptor e introduce la contraseña (`admin123` por defecto).
3. La interfaz cambiará automáticamente, mostrando un **Panel de Control (Dashboard)** con:
    * **KPIs:** Usuarios totales, citas agendadas y promedio de citas por usuario.
    * **Gráficos de demanda:** Visualización de los servicios más solicitados.
    * **Tabla interactiva:** Listado detallado de todas las citas del sistema.

---
## 🔧 Arquitectura Técnica

El salto cualitativo de esta versión radica en su núcleo de procesamiento cognitivo:

* **CrewAI (Flujo Secuencial):**
    * **Agente Analista:** Recibe el historial de chat. Su temperatura es `0.0` para realizar cálculos matemáticos precisos de fechas (ej. deducir "mañana"). Extrae la intención pura del usuario.
    * **Agente Gestor:** Recibe los datos limpios. Su objetivo es decidir qué herramienta (*Tool*) ejecutar basándose en el análisis previo.
* **Function Calling:** Las funciones en `tools_openai.py` interceptan la orden del Gestor, aíslan el token del usuario activo y ejecutan código Python puro para hacer peticiones **HTTP a Google Calendar** o **SQL a SQLite**.
* **RAG:** Los PDFs se dividen en *chunks* (1000 caracteres) y se vectorizan localmente usando **ChromaDB** y **Ollama**. Las consultas limpian los saltos de línea propios del formato PDF para evitar alucinaciones de lectura en el LLM.

---

## 🔒 Seguridad y Buenas Prácticas

**Ignorados en el repositorio (`.gitignore`):**

* ❌ `credentials.json` (Secretos de la aplicación)
* ❌ Carpeta `/tokens/` (Tokens de acceso de los usuarios)
* ❌ `.env` (API Keys)
* ❌ `botcitas.db` (Datos personales de los usuarios)
* ❌ `chroma_db_data/` (Bases de datos vectoriales locales)

> **Nota de desarrollo:** Al implementar el aislamiento de tokens JSON por cada usuario, se ha erradicado el uso de variables globales en memoria, asegurando que las peticiones concurrentes de distintos pacientes no colisionen en el backend.