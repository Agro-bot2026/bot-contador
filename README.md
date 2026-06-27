# BotContador

Bot de Telegram de asesoría legal para contratistas de viña en Mendoza. Responde consultas sobre el Estatuto del Contratista de Viñas y Frutales usando RAG (búsqueda sobre documentos legales) y genera informes en PDF. Pensado como herramienta gratuita para trabajadores rurales.

**Tecnología:** Python + python-telegram-bot. Usa Vertex AI (Gemini) para las respuestas, Manus para generar informes complejos, ChromaDB como base vectorial sobre los documentos legales, y Google TTS para respuestas en audio.

---

## Requisitos del servidor

- **Sistema:** Ubuntu / Debian (probado en VPS)
- **Python:** versión 3.10 o superior
- **pm2:** para mantener el bot corriendo (se instala con npm)
- Un **token de bot de Telegram** (de @BotFather)
- Una **API key de Manus** (de https://manus.ai)
- Una **cuenta de servicio de Google Cloud** con Vertex AI habilitado (archivo `llave.json`)

---

## Instalación paso a paso

### 1. Clonar el repositorio

```bash
cd ~
git clone https://github.com/Agro-bot2026/bot-contador.git BotContador
cd BotContador
```

### 2. Instalar Python, el entorno virtual y pm2 (si el VPS es nuevo)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm
sudo npm install -g pm2
```

### 3. Crear el entorno virtual e instalar dependencias

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> Son bastantes dependencias (incluye las de Google Cloud, ChromaDB y ReportLab). Puede tardar varios minutos.
>
> ### 4. Configurar las credenciales (¡el paso clave!)

**a) El archivo `.env`** (token de Telegram y key de Manus). Crealo desde la plantilla:

```bash
cp .env.example .env
nano .env
```

Completá los valores reales:

```
TELEGRAM_TOKEN=tu_token_real_de_telegram
MANUS_API_KEY=tu_api_key_real_de_manus
```

> Guardá con `Ctrl+O`, Enter, y salí con `Ctrl+X`.

**b) La credencial de Google (`llave.json`)**, que NO viene en el repo. Copiala desde tu backup a la carpeta del bot:

```bash
# el archivo debe quedar en: ~/BotContador/llave.json
```

> Es la cuenta de servicio de Google Cloud con permiso de Vertex AI (proyecto `cleanbot-8f137`). El bot la busca en la ruta `llave.json` dentro de su carpeta.

### 5. Generar la base de datos vectorial (RAG)

La carpeta `vectordb/` no viene en el repo (se regenera). Para crearla a partir de los documentos legales:

```bash
source venv/bin/activate
python3 crear_base_vectorial.py
```

> Esto procesa los archivos de `documentos/` y arma la base vectorial de ChromaDB. Puede tardar unos minutos la primera vez.

---

## Arrancar el bot

El bot se ejecuta con **pm2**, que lo mantiene corriendo y lo reinicia solo si se cae.

```bash
pm2 start bot.py --name bot-contador --interpreter ~/BotContador/venv/bin/python3
pm2 save
```

> `pm2 save` guarda la configuración para que el bot vuelva a levantar solo si se reinicia el VPS.

---

## Comandos útiles de pm2

| Acción | Comando |
|---|---|
| Ver procesos corriendo | `pm2 list` |
| Ver logs en vivo | `pm2 logs bot-contador` |
| Reiniciar el bot | `pm2 restart bot-contador` |
| Detener el bot | `pm2 stop bot-contador` |
| Ver detalles | `pm2 info bot-contador` |


---

## Estructura del proyecto

```
BotContador/
├── bot.py                   # Bot principal (Telegram + Vertex AI + Manus + RAG)
├── crear_base_vectorial.py  # Genera la base ChromaDB desde los documentos
├── requirements.txt         # Dependencias de Python
├── .env                     # ⚠️ NO incluido - token Telegram + key Manus
├── .env.example             # Plantilla de credenciales (sin secretos)
├── llave.json               # ⚠️ NO incluido - credencial de Google Cloud
├── documentos/              # Leyes, estatutos, resoluciones (material legal público)
├── *_pdf.py                 # Generadores de informes PDF (cosecha, renaf, etc.)
└── vectordb/                # ⚠️ NO incluido - se regenera con crear_base_vectorial.py
```

---

## Archivos que NO vienen en el repo

Por seguridad y peso, estos quedan fuera de GitHub y los tenés que aportar al reinstalar:

- **`.env`** — token de Telegram y API key de Manus (crealo desde `.env.example`)
- **`llave.json`** — credencial de Google Cloud / Vertex AI (copiala desde tu backup)
- **`claude_key.json`** — solo si reactivás el código de Claude (actualmente sin uso)
- **`vectordb/`** — base vectorial (se regenera con `crear_base_vectorial.py`)
- **`venv/`** — entorno virtual (se regenera con `pip install -r requirements.txt`)
- **`usuarios_autorizados.json`** — datos de usuarios

---

## Nota sobre el motor de IA

El bot usa **Vertex AI (Gemini)** como motor principal y **Manus** para informes complejos, con Gemini como respaldo si Manus falla. Quedó código residual de una prueba con Claude/Anthropic (sin uso activo); si querés reactivarlo, necesitarías agregar `claude_key.json` y completar la integración.
