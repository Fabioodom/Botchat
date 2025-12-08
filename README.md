<!-- Improved compatibility of back to top link -->
<a id="readme-top"></a>

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![project_license][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]

<br />
<div align="center">
  <a href="https://github.com/Fabioodom/Botchat">
    <img src="images/logo.png" alt="Logo" width="80" height="80">
  </a>

  <h3 align="center">BotChatLM</h3>

  <p align="center">
    Asistente inteligente para agendar, consultar, modificar y cancelar citas sincronizadas con Google Calendar.
    <br />
    <br />
    <a href="https://github.com/Fabioodom/Botchat"><strong>Explorar la documentación »</strong></a>
    <br />
    <br />
    <a href="https://github.com/Fabioodom/Botchat">Ver demo (local)</a>
    &middot;
    <a href="https://github.com/Fabioodom/Botchat/issues/new?labels=bug&template=bug-report---.md">Reportar bug</a>
    &middot;
    <a href="https://github.com/Fabioodom/Botchat/issues/new?labels=enhancement&template=feature-request---.md">Solicitar mejora</a>
  </p>
</div>


<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#features">Features</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

[![Product Name Screen Shot][product-screenshot]](https://github.com/Fabioodom/Botchat)

**BotChatLM** es un bot de citas construido con **Python + Streamlit** que combina:

- Un modelo de lenguaje (LLM) local o en la nube (Ollama / Groq).
- Integración con **Google Calendar** para crear, modificar y eliminar eventos reales.
- Persistencia de citas y memoria de conversación en **SQLite**.
- Lectura de **PDFs** para extraer automáticamente datos de citas (nombre, email, servicio, fecha, hora).

La idea es que el usuario pueda hablar de forma natural:

> “Quiero una cita médica mañana por la tarde”  
> “Usa el PDF para crear la cita con mis datos”  
> “Cancela mi cita del 10/12/2025”  

Y el bot se encarga de:
- Inferir la intención (crear / consultar / modificar / cancelar).
- Preguntar solo lo mínimo necesario.
- Generar un JSON estructurado.
- Guardar la cita en la base de datos.
- Sincronizar el evento en Google Calendar.

<p align="right">(<a href="#readme-top">back to top</a>)</p>


### Features

- 🤖 **Chat con IA** usando Ollama (local) o Groq (cloud).
- 📅 **Sincronización con Google Calendar**:
  - Crear citas.
  - Consultar eventos futuros.
  - Modificar y cancelar eventos.
- 💾 **SQLite** para almacenar citas y memoria del chat.
- 📄 **Lectura de PDF**:
  - El usuario puede subir un PDF.
  - El bot puede usar el contenido del PDF para crear la cita (“usa el pdf…”).
- 🧠 **Gestión de estado y memoria**:
  - Evita preguntar datos que ya se han dado.
  - Mantiene contexto por usuario (email de Google).
- 🖥️ **Interfaz web con Streamlit**, lista para correr en local o servidor.

### Built With

* [![Python][Python.py]][Python-url]
* [Streamlit](https://streamlit.io/)
* [SQLite](https://www.sqlite.org/index.html)
* [Google Calendar API](https://developers.google.com/calendar)
* [LangChain](https://www.langchain.com/)
* [Ollama](https://ollama.com/) / [Groq](https://groq.com/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

A continuación se explica cómo poner el proyecto a funcionar en tu máquina local.

### Prerequisites

- **Python 3.10+** recomendado
- **pip** y (opcional) **virtualenv**
- Para usar LLM local:
  - [Ollama](https://ollama.com/) instalado y al menos un modelo descargado (por ejemplo `llama3.2:1b`).
- Para usar LLM en la nube (Groq):
  - Cuenta en [Groq](https://groq.com/) y **GROQ_API_KEY**.
- Para Google Calendar:
  - Proyecto en Google Cloud con la API de Calendar activada.
  - Archivo `credentials.json` descargado desde Google Cloud Console (OAuth client ID).

### Installation

1. **Clonar el repositorio**

   ```bash
   git clone https://github.com/Fabioodom/Botchat.git
   cd Botchat
