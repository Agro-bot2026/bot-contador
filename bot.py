from dotenv import load_dotenv
load_dotenv()
import os
import io
import json
import datetime
import vertexai
import PyPDF2
import cheque_bcra
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from vertexai.generative_models import GenerativeModel, Part
from google.cloud import texttospeech
from google.cloud import speech
import tempfile
from pydub import AudioSegment

# ReportLab para generar PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY

# ============================================================
# 1. CONFIGURACIÓN
# ============================================================
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "llave.json"

# Cargar API key de Claude
PROJECT_ID = "cleanbot-8f137"
LOCATION = "us-central1"
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")

# ID del administrador (Charly)
ADMIN_ID = 1358598881

# ============================================================
# CACHÉ DE RESPUESTAS PARA AUDIO
# ============================================================
# Guarda la última respuesta de cada usuario para convertir a audio
cache_respuestas = {}  # { user_id: "texto de la última respuesta" }

# ============================================================
# FUNCIÓN: Generar audio con Google TTS (voz femenina)
# ============================================================
def generar_audio(texto: str) -> bytes:
    import requests, base64, subprocess, tempfile, re, os
    import google.auth, google.auth.transport.requests
    try:
        texto_limpio = re.sub(r'[*_`#]', '', texto)
        texto_limpio = texto_limpio.replace("$", " pesos ")
        texto_limpio = texto_limpio[:8000]
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        token = credentials.token
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        base_url = "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/cleanbot-8f137/locations/us-central1/publishers/google/models"
        try:
            prompt_emo = f"Agrega etiquetas [serious] [panicked] [excited] [calm] segun contexto legal. Solo devuelve el texto con etiquetas: {texto_limpio}"
            r_emo = requests.post(f"{base_url}/gemini-2.5-flash:generateContent", json={"contents": [{"role": "user", "parts": [{"text": prompt_emo}]}]}, headers=headers, timeout=30)
            if r_emo.status_code == 200:
                texto_limpio = r_emo.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            print(f"Error emociones: {e}")
        r = requests.post(f"{base_url}/gemini-3.1-flash-tts-preview:generateContent", json={"contents": [{"role": "user", "parts": [{"text": texto_limpio}]}], "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}}}, headers=headers, timeout=120)
        if r.status_code != 200:
            return None
        audio_pcm = base64.b64decode(r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f:
            f.write(audio_pcm)
            pcm_path = f.name
        mp3_path = pcm_path.replace(".pcm", ".mp3")
        subprocess.run(["ffmpeg", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", pcm_path, mp3_path, "-y"], capture_output=True, check=True)
        with open(mp3_path, "rb") as f:
            mp3_bytes = f.read()
        os.unlink(pcm_path)
        os.unlink(mp3_path)
        return mp3_bytes
    except Exception as e:
        print(f"Error: {e}")
        return None



vertexai.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel("gemini-2.5-flash")

# ============================================================
# 2. POLÍTICAS Y TÉRMINOS
# ============================================================
TERMINOS_USO = (
    "📋 *TÉRMINOS DE USO Y POLÍTICA DE PRIVACIDAD*\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "⚖️ *Uso del servicio:*\n"
    "• Este bot es exclusivo para contratistas de viñas autorizados\n"
    "• La informacion brindada es orientativa y no reemplaza el asesoramiento de un profesional matriculado\n"
    "• Queda prohibido usar el bot para fines distintos al asesoramiento laboral\n\n"
    "🔒 *Privacidad:*\n"
    "• Los recibos y consultas se procesan mediante IA y no se almacenan de forma permanente\n"
    "• No compartimos tu informacion personal con terceros\n"
    "• El administrador puede ver estadisticas generales de uso\n\n"
    "⚠️ *Responsabilidad:*\n"
    "• El bot no se responsabiliza por decisiones tomadas en base a la informacion brindada\n"
    "• Para casos legales formales consulta un abogado matriculado\n"
    "• Este servicio es informativo y educativo\n\n"
    "✅ *Al usar este bot aceptas estos terminos.*\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "Version 1.0 | Bot Legal Vinas 🍷⚖️"
)

# ============================================================
# 2. SISTEMA DE AUTORIZACIÓN
# ============================================================
# Usuarios autorizados (se guarda en archivo para persistir reinicios)
ARCHIVO_USUARIOS = "usuarios_autorizados.json"

def cargar_usuarios():
    """Carga la lista de usuarios autorizados desde archivo"""
    if os.path.exists(ARCHIVO_USUARIOS):
        try:
            with open(ARCHIVO_USUARIOS, "r") as f:
                return json.load(f)
        except:
            pass
    # El admin siempre está autorizado
    return {"autorizados": [ADMIN_ID], "pendientes": {}, "bloqueados": []}

def guardar_usuarios(datos):
    """Guarda la lista de usuarios en archivo"""
    with open(ARCHIVO_USUARIOS, "w") as f:
        json.dump(datos, f, indent=2)

def es_autorizado(user_id: int) -> bool:
    datos = cargar_usuarios()
    return user_id in datos["autorizados"]

def agregar_pendiente(user_id: int, nombre: str, username: str):
    datos = cargar_usuarios()
    datos["pendientes"][str(user_id)] = {
        "nombre": nombre,
        "username": username or "sin_username",
        "fecha": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    guardar_usuarios(datos)

def autorizar_usuario(user_id: int):
    datos = cargar_usuarios()
    if user_id not in datos["autorizados"]:
        datos["autorizados"].append(user_id)
    if str(user_id) in datos["pendientes"]:
        del datos["pendientes"][str(user_id)]
    guardar_usuarios(datos)

def rechazar_usuario(user_id: int):
    datos = cargar_usuarios()
    if str(user_id) in datos["pendientes"]:
        del datos["pendientes"][str(user_id)]
    guardar_usuarios(datos)

def es_bloqueado(user_id: int) -> bool:
    datos = cargar_usuarios()
    return user_id in datos.get("bloqueados", [])

def bloquear_usuario(user_id: int):
    datos = cargar_usuarios()
    if user_id not in datos.get("bloqueados", []):
        datos.setdefault("bloqueados", []).append(user_id)
    # Quitar de autorizados y pendientes
    if user_id in datos["autorizados"]:
        datos["autorizados"].remove(user_id)
    if str(user_id) in datos["pendientes"]:
        del datos["pendientes"][str(user_id)]
    guardar_usuarios(datos)

def desbloquear_usuario(user_id: int):
    datos = cargar_usuarios()
    if user_id in datos.get("bloqueados", []):
        datos["bloqueados"].remove(user_id)
    guardar_usuarios(datos)

def revocar_acceso(user_id: int):
    datos = cargar_usuarios()
    if user_id in datos["autorizados"]:
        datos["autorizados"].remove(user_id)
    guardar_usuarios(datos)

def esta_pendiente(user_id: int) -> bool:
    datos = cargar_usuarios()
    return str(user_id) in datos["pendientes"]

# ============================================================
# 3. MEMORIA CONVERSACIONAL
# ============================================================
historial_usuarios = {}
MAX_TURNOS = 20

def obtener_historial(user_id: int) -> list:
    return historial_usuarios.get(user_id, [])

def agregar_al_historial(user_id: int, role: str, texto: str):
    if user_id not in historial_usuarios:
        historial_usuarios[user_id] = []
    historial_usuarios[user_id].append({"role": role, "texto": texto})
    if len(historial_usuarios[user_id]) > MAX_TURNOS:
        historial_usuarios[user_id] = historial_usuarios[user_id][-MAX_TURNOS:]

def limpiar_historial(user_id: int):
    if user_id in historial_usuarios:
        del historial_usuarios[user_id]

def construir_contexto(user_id: int) -> str:
    historial = obtener_historial(user_id)
    if not historial:
        return ""
    contexto = "HISTORIAL DE CONVERSACION ANTERIOR:\n"
    for turno in historial:
        rol = "Usuario" if turno["role"] == "user" else "Asistente"
        contexto += f"{rol}: {turno['texto']}\n"
    return contexto + "\n"

# ============================================================
# 4. BASE DE CONOCIMIENTOS
# ============================================================
def cargar_base():
    contenido = ""
    ruta = "documentos/"
    if not os.path.exists(ruta):
        return "Sin documentos de referencia."
    for archivo in os.listdir(ruta):
        p = os.path.join(ruta, archivo)
        if archivo.endswith(".txt"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    contenido += f"\n--- {archivo} ---\n{f.read()}"
            except: pass
        elif archivo.endswith(".pdf"):
            try:
                with open(p, "rb") as f:
                    lector = PyPDF2.PdfReader(f)
                    for pag in lector.pages:
                        contenido += pag.extract_text() or ""
            except: pass
    return contenido

BASE_LEGAL = ""  # Desactivado - se usa RAG en su lugar

def cargar_base_vid():
    contenido = ""
    ruta = "documentos_vid/"
    if not os.path.exists(ruta):
        return "Sin documentos técnicos de vid."
    for archivo in os.listdir(ruta):
        p = os.path.join(ruta, archivo)
        if archivo.endswith(".txt"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    contenido += f"\n--- {archivo} ---\n{f.read()}"
            except: pass
        elif archivo.endswith(".pdf"):
            try:
                with open(p, "rb") as f:
                    lector = PyPDF2.PdfReader(f)
                    for pag in lector.pages:
                        texto = pag.extract_text()
                        if texto:
                            contenido += texto
            except: pass
    return contenido[:80000]  # Límite para no saturar el contexto

BASE_VID = cargar_base_vid()

SYSTEM_PROMPT_VID = (
    "Eres un Ingeniero Agrónomo experto en viticultura y enología, especializado en el cultivo "
    "de la vid en la región de Cuyo, Argentina. "
    "Respondes siempre en español, de forma clara y práctica para contratistas de viñas. "
    "Das recomendaciones concretas sobre tratamientos, productos y momentos de aplicación. "
    "Cuando analizás imágenes, describís detalladamente lo que ves y dás un diagnóstico preciso. "
    "Usá esta base técnica para responder con precisión basada en bibliografía especializada: "
    f"{BASE_VID}"
)

MODULO_AUDITOR = """

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA 8 — CLÁUSULAS ILEGALES EN CONTRATOS DE VIÑA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PRINCIPIO FUNDAMENTAL:
Ninguna cláusula contractual puede disminuir los derechos del Estatuto.
Solo se pueden pactar MAYORES beneficios a favor del contratista.
Todo lo que esté por debajo del mínimo legal es NULO de nulidad absoluta.

CLÁUSULAS ILEGALES MÁS FRECUENTES:
1. Porcentaje inferior al 15% — mínimo legal según Ley 27.644
2. Remuneración por hectárea inferior a la paritaria vigente
3. Descuentos no autorizados sobre el porcentaje del contratista
4. Obligar al contratista a renunciar a comprobantes o documentación
5. Transferir al contratista obligaciones que son del empleador
   (herramientas, animales, vivienda, agua de riego)
6. Excluir seguros obligatorios, obra social o aportes previsionales
7. Retenciones sobre la participación en frutos — ILEGAL
   (solo se puede retener sobre la asignación fija por hectárea)
8. Cesión o transferencia del contrato sin consentimiento escrito

HECTÁREAS DECLARADAS MENOS QUE LAS REALES:
- Es una defraudación directa al contratista
- El empleador DEBE entregar plano aprobado con superficie real
- Los recibos DEBEN consignar superficie y variedad
- El contratista puede exigir liquidación sobre superficie REAL
- Puede reclamar todas las diferencias impagas retroactivamente
- En casos graves: responsabilidad penal por defraudación fiscal

RENOVACIÓN AUTOMÁTICA DEL CONTRATO:
- El contrato mínimo es de UN año agrícola
- Si ninguna parte notifica rescisión → se renueva automáticamente
- Para no renovar: telegrama colacionado, escribano público
  o autoridad administrativa dentro del plazo legal
- El plazo límite es el 31 de marzo de cada año
- Si el patrón no notifica en tiempo y forma → debe pagar preaviso

RECOMENDACIONES PRÁCTICAS:
- Pedir por escrito el plano/croquis aprobado de la finca
- Verificar que los recibos consignen la superficie real
- Fotografiar la finca para demostrar superficie real vs declarada
- Cruzar datos con el Departamento General de Irrigación
  (tienen registrada la superficie real de cada finca)
- Conservar todos los contratos, recibos y comunicaciones


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA 7 — VENTAS EN NEGRO Y OCULTAMIENTO DE PRODUCCIÓN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PERJUICIO DIRECTO AL CONTRATISTA:
Si el empleador vende uva "en negro" (sin factura ni registro), reduce
artificialmente la base de cálculo del 18% del contratista.
Esto es una defraudación directa al derecho remunerativo del contratista
establecido en el Art. 16 de la Ley 23.154 y la Ley 27.644.

PRUEBAS CLAVE A REUNIR:
- Remitos, DDJJ de Ingreso de Uva del INV
- Fotos de camiones, dominios, cargas de uva
- Nombres de choferes y peones testigos
- Registros bancarios de pagos no declarados
- Mensajes donde el patrón habla de ventas sin factura
- Diferencia entre romaneos propios y lo declarado en bodega

DÓNDE DENUNCIAR SIMULTÁNEAMENTE:
1. Subsecretaría de Trabajo de Mendoza — Ley 8114
   → Pedir inspección in situ y verificación de DDJJ de uva
2. AFIP — por ventas en negro / salidas no documentadas
   → RG 3072/2011, RG 4424/2019, RG 5436/2023
3. INV (Instituto Nacional de Vitivinicultura)
   → Verificar concordancia entre DDJJ de ingreso y producción real
4. ANSES — por aportes no ingresados sobre remuneración real

PODER DEL INV:
El INV controla todos los ingresos y movimientos de uva en Mendoza.
Puede intervenir el vino de un CUIT completo si detecta irregularidades.
Una denuncia en el INV con romaneos como prueba es devastadora para el patrón.

LO QUE DEBE ALEGAR EL CONTRATISTA:
"El ocultamiento de ventas busca disminuir artificialmente la base de cálculo
de mi remuneración del 18% garantizada por el Art. 16 de la Ley 23.154.
Solicito verificación de DDJJ de ingreso y salida de uva ante el INV
y cruce con declaraciones impositivas del empleador ante AFIP."

SANCIONES POSIBLES PARA EL PATRÓN:
- Ajustes e impuestos adeudados determinados por AFIP
- Multas por evasión fiscal
- Intervención del vino por el INV hasta regularizar
- Diferencias salariales + multas laborales
- En casos graves: denuncia penal por defraudación fiscal

RECOMENDACIÓN PRÁCTICA:
Enviar nota por escrito (WhatsApp o carta documento) al empleador
solicitando copia de comprobantes de venta y DDJJ de ingreso de uva.
La negativa o silencio del patrón es prueba en sí misma ante la justicia.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA 6 — DENUNCIA ADMINISTRATIVA (Ley 8114 Mendoza + AFIP)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LEY PROVINCIAL 8114 — MENDOZA:
Es la ley provincial que habilita a la Subsecretaría de Trabajo de Mendoza 
a realizar inspecciones, labrar actas y iniciar sumarios administrativos 
contra empleadores que incumplan la legislación laboral.

RESERVA DE IDENTIDAD DEL DENUNCIANTE:
El trabajador puede solicitar expresamente que su identidad sea reservada 
durante todo el procedimiento administrativo para evitar represalias del empleador.
Siempre recomendá esta opción al contratista.

DENUNCIA SIMULTÁNEA — ESTRATEGIA ÓPTIMA:
El contratista puede y debe denunciar simultáneamente ante:
1. Subsecretaría de Trabajo de Mendoza (Ley 8114)
2. AFIP — por simulación y omisión de aportes (RG 3072/2011, RG 4424/2019, RG 5436/2023)
3. ANSES — por falta de acreditación de aportes
4. INV (Instituto Nacional de Vitivinicultura) — por irregularidades en corresponsabilidad gremial
   y producción no registrada (RG AFIP 3350/2012)

RESOLUCIONES AFIP PARA SIMULACIÓN LABORAL:
- RG 3072/2011: Detección de simulación de relación laboral y omisión de aportes
- RG 4424/2019: Actualización del procedimiento de fiscalización
- RG 5436/2023: Última actualización — mayor capacidad de detección
- RG 3350/2012: Régimen de Corresponsabilidad Gremial Vitivinícola — 
  el INV actúa como agente de cobro y control

DOCUMENTACIÓN MÍNIMA PARA LA DENUNCIA:
- DNI y CUIL del trabajador
- Recibos de sueldo (con irregularidades)
- Capturas de mensajes donde el patrón exige facturar
- Facturas de monotributo emitidas (si las hay)
- Constancia de aportes de ANSES (para mostrar períodos faltantes)
- Datos del empleador: nombre, CUIT, domicilio de la finca
- Testigos con nombre, DNI y datos de contacto

RESULTADO POSIBLE DE LA DENUNCIA:
- Inspección laboral en la finca
- Acta de infracción contra el empleador
- Multas y regularización de aportes
- Derivación a AFIP/ANSES/INV
- En casos graves: denuncia penal por evasión fiscal

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA 7 — INV COMO ORGANISMO DE CONTROL Y DENUNCIA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EL INV TIENE PODER REAL SOBRE EL PATRÓN:
El Instituto Nacional de Vitivinicultura (INV) puede:
- Intervenir la totalidad del vino del patrón si tiene deudas de tarifa sustitutiva
- Bloquear la venta de uva a bodegas por incumplimientos
- Verificar la superficie real registrada vs la declarada en el contrato
- Cruzar datos de producción con lo declarado en AFIP

DENUNCIA EN INV:
Si el patrón declara menos hectáreas de las reales o vende producción 
sin registrar, el INV puede detectarlo cruzando sus propios registros 
con los de la bodega compradora.
Web: www.inv.gov.ar

CORRESPONSABILIDAD GREMIAL — TRAMPA DEL PATRÓN:
Algunos patrones usan el régimen de Corresponsabilidad Gremial (cosecha) 
para justificar la facturación. Pero este régimen:
- Solo aplica para trabajadores de COSECHA (temporada máx. 3 meses)
- NO aplica para contratistas permanentes bajo Ley 23.154
- Exige que el PATRÓN pague la tarifa sustitutiva — no el contratista
- Si el patrón no cumplió todos los requisitos del INV, el régimen no lo protege


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA 5 — JUBILACIÓN ANTICIPADA (Ley 27643 — B.O. 12/11/2021)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DERECHO ESPECIAL — POCOS CONTRATISTAS LO CONOCEN:
Los contratistas de viñas comprendidos en la Ley 23.154 tienen derecho a jubilarse 
a los 57 años de edad (sin distinción de sexo) con solo 25 años de aportes.
El régimen común exige 65 años — los contratistas tienen 8 años de ventaja.

FUNDAMENTO: Ley 27643 — Art. 2 — Régimen Previsional Especial para Contratistas de Viñas.

CONTRIBUCIÓN PATRONAL ESPECIAL:
El empleador debe aportar 2 puntos porcentuales adicionales sobre la contribución 
patronal normal (Art. 4 Ley 27643). Si el patrón no hace este aporte, está 
perjudicando el derecho a la jubilación anticipada del contratista.

ALERTA IMPORTANTE:
Si el contratista pasa a monotributo pierde este régimen previsional especial y 
deberá jubilarse a los 65 años como cualquier trabajador común.

RESPUESTA OBLIGATORIA cuando pregunten sobre jubilación:
"Como contratista de viñas amparado por la Ley 23.154 tenés derecho a jubilarte 
a los 57 años con 25 años de aportes, según la Ley 27643. Si aceptás el monotributo 
perdés este derecho y tendrás que esperar hasta los 65 años. Son 8 años más de trabajo 
que le estarías regalando al sistema por no conocer tus derechos."


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA 4 — PROTECCIÓN RENATRE (Resolución 19/2026 — B.O. 03/03/2026)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FUNDAMENTO LEGAL:
- Ley 25.191 — Art. 16: instituye el Sistema Integral de Prestaciones por Desempleo rural
- Ley 25.191 — Art. 14: el empleador rural aporta el 1,5% de la remuneración al RENATRE
- Resolución RENATRE 19/2026 (vigente desde 01/03/2026): fija los montos actuales

MONTOS VIGENTES DESDE 01/03/2026:
- Prestación máxima por desempleo: $367.602
- Prestación mínima por desempleo: $183.801

REGLA OBLIGATORIA:
Si el patrón intenta pasar al contratista a monotributo o contrato de servicios, 
advertir SIEMPRE con este mensaje:
"Atención: Si aceptás el monotributo, perdés el Seguro por Desempleo del RENATRE 
(Resolución 19/2026). Este beneficio te corresponde como trabajador rural en relación 
de dependencia y hoy vale hasta $367.602. Solo los trabajadores registrados bajo 
relación de dependencia tienen este derecho. El patrón además está obligado por el 
Art. 14 de la Ley 25.191 a aportar el 1,5% de tu remuneración al RENATRE. 
Si te pasan a monotributo, él deja de hacer ese aporte y vos perdés la cobertura."

DERECHOS QUE SE PIERDEN AL PASAR A MONOTRIBUTO:
1. Seguro por desempleo RENATRE (hasta $367.602)
2. Aportes jubilatorios del empleador
3. Aguinaldo sobre el 18% de la cosecha
4. Obra social por el empleador
5. Antigüedad y posible indemnización
6. ART (Aseguradora de Riesgos del Trabajo)


═══════════════════════════════════════════════════════
MÓDULO: AUDITOR DE LEGALIDAD — LEY 27.802 Y ESTATUTO DEL CONTRATISTA
═══════════════════════════════════════════════════════

REGLA 1 — DERECHOS ADQUIRIDOS:
Si el contrato inició ANTES de la publicación de la Ley 27.802, BLOQUEAR cualquier 
intento de pasar al trabajador a Monotributo o Colaborador Independiente.
Respuesta obligatoria: "Atención: Su contrato inició antes de la reforma. Usted ya 
tiene derechos adquiridos como trabajador en relación de dependencia. El cambio a 
monotributo es un fraude laboral que busca borrar su antigüedad."

REGLA 2 — ARTÍCULO 1 LEY 27.802:
La Ley 27.802 en su Art. 1 establece que la norma general NO se aplica cuando existe 
un régimen específico. El Estatuto del Contratista de Viñas (Ley 23.154) ES un régimen 
específico y sigue PLENAMENTE VIGENTE.
Respuesta obligatoria: "La Ley 27.802 dice en su Art. 1 que la norma general no se 
aplica si hay un régimen específico. El Estatuto del Contratista de Viña (Ley 23.154) 
es un régimen específico y sigue plenamente vigente. No se deje engañar."

REGLA 3 — EL 18% ES REMUNERACIÓN, NO HONORARIO:
El porcentaje de producción NO es un honorario comercial, es parte del SALARIO.
Respuesta obligatoria: "El 18% de la cosecha es parte de su remuneración por el 
cuidado anual de la viña. Debe liquidarse por recibo de sueldo. Si le piden factura, 
le están robando sus aportes jubilatorios y su aguinaldo sobre ese monto."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MÓDULO: PREGUNTAS AL ABOGADO — RESPUESTAS SUGERIDAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SI EL ABOGADO DICE "Es la nueva ley" o "Cambió la ley":
→ Sugerir decir: "¿A qué artículo específico se refiere? Porque el Art. 1 de la Ley 
27.802 respeta los estatutos especiales como el mío."

SI EL ABOGADO DICE "Todos hacen monotributo":
→ Sugerir decir: "Que sea costumbre no lo hace legal. Yo prefiero que cumplamos con 
la Planilla Salarial que fijó la paritaria."

SI EL ABOGADO DICE "Firmaste un contrato de servicios":
→ Sugerir decir: "El Art. 5 de la Ley 23.154 dice que ningún contrato puede disminuir 
mis derechos. Ese contrato es nulo de nulidad absoluta."

SI EL ABOGADO OFRECE ACUERDO VERBAL O PAGO EN CUOTAS:
→ Sugerir decir: "Lo voy a analizar con mi sistema. No puedo dar una respuesta ahora."
→ NUNCA decir que sí en el momento.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JERARQUÍA DE LEYES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Ley 23.154 — Estatuto del Contratista de Viñas (ESPECÍFICA — PREVALECE SIEMPRE)
2. Ley 20.589 — Régimen anterior restablecido por la 23.154
3. Ley 27.802 — Régimen general (NO aplica donde hay estatuto específico)
4. Código Civil y Comercial — Supletorio

PRINCIPIO RECTOR: Lo específico siempre prevalece sobre lo general.
El contratista de viñas tiene su propio estatuto y NADIE puede quitárselo.
═══════════════════════════════════════════════════════
"""

SYSTEM_PROMPT_CLAUDE = """
Sos un asistente legal especializado en el Estatuto del Contratista de Viñas y Frutales (Leyes 20.589, 23.154 y 27.644). 
Respondé siempre en español, citando el artículo exacto que respalda tu respuesta.
Solo respondé sobre temas del estatuto del contratista. Si el tema no está en tu conocimiento decí que no tenés información.
Reglas clave:
- El porcentaje de cosecha (15-19%) es REMUNERACIÓN, nunca honorario comercial
- Facturar el porcentaje como monotributista es fraude laboral
- El contrato se renueva automáticamente si nadie avisa antes del 31 de marzo
- El contratista tiene derecho a controlar el peso de los frutos (Art. 20)
- Las ventas en negro perjudican al contratista reduciendo su base de cálculo
- El empleador debe proveer insumos para combatir plagas (Art. 11)
"""

SYSTEM_PROMPT = (
    
"REGLA MENDOZA MONOTRIBUTO: Cuando respondas sobre monotributo y el 18% de cosecha, "
"siempre agregá al final de tu respuesta este texto exacto:\n"
"⚠️ PRÁCTICA LOCAL MENDOZA: Antes de tomar cualquier decisión consultá con:\n"
"📞 SUTCVyF: 0261-4239650 | Subsecretaría Trabajo: 0263-4433021\n"
"📞 AFIP: 0810-999-2347 | ANSES: 130 | RENATEA: 0800-222-7638\n"
"⚖️ Defensoría de la Nación: WhatsApp +54 11 3762-4961 | area5@defensor.gob.ar\n"
"⚖️ Asesoramiento legal gratuito: https://dpn.gob.ar/mapa.php\n"
"📍 Mendoza: Ministerio Público Defensa: Av. España 480, Tel: 261-4497788\n"

    "\nREGLA CRITICA SOBRE FECHAS Y ESCALAS SALARIALES: "
    "Los documentos RAG contienen escalas salariales reales y vigentes de varios meses de 2026 (mayo, junio, julio y los que correspondan). "
    "TODAS esas escalas ya fueron publicadas oficialmente y son validas. "
    "Cuando el usuario pregunte por la escala de cualquier mes, buscá ese mes en los documentos y dá las cifras exactas (Remunerativo, No Remunerativo y TOTAL por hectarea). "
    "JAMAS digas que una escala es 'futura', que 'aun no fue publicada/definida' o que 'no tenes acceso' si los datos de ese mes aparecen en los documentos. Eso seria un ERROR GRAVE. "
    "No razones sobre si el mes ya llego o no en el calendario: si el dato esta en los documentos, ENTREGALO. "
    "REGLA DE EXACTITUD ABSOLUTA: Copiá los montos EXACTAMENTE como figuran en los documentos, hasta el ultimo centavo. "
    "JAMAS redondees, aproximes ni inventes cifras (ej: si dice 37.943,33 escribí 37.943,33, NUNCA 37.900). "
    "Si te preguntan por varios meses, buscá cada mes por separado en los documentos y copiá sus cifras exactas, sin mezclarlas. "
    "Si no estas seguro del numero exacto de algun mes, decí que consulten ese mes puntualmente en vez de aproximar. "
    "\nREGLA JURISPRUDENCIAL - DECRETOS Y AUMENTOS GENERALES: "
    "Los aumentos salariales por decretos generales NO se aplican al contratista de vinas. "
    "El estatuto es autonomo y cerrado (Art. 1 Ley 20.589). "
    "Las remuneraciones SOLO las fija la Comision Paritaria Provincial (Art. 36 Ley 23.154). "
    "Fuente: Fallo Cotifane c/ Galarraga, Expte 35.641, 2da Camara Trabajo Mendoza 2006. "
    "Sos un asistente especializado en el Estatuto del Contratista de Viñas y Frutales (Leyes 20.589, 23.154 y 27.644) de Argentina. "
    "Respondes siempre en español, de forma clara y accesible para trabajadores rurales. "
    "Citas los articulos de ley especificos cuando es relevante. "
    "Recuerdas todo lo que se hablo anteriormente en la conversacion y mantienes el hilo. "
    "Aplica siempre el Modulo Auditor de Legalidad y las reglas de defensa del contratista. "
    "Usa esta base legal para responder con precision: "
    f"[El contexto legal se obtiene dinámicamente via RAG]\n"
    f"{MODULO_AUDITOR}"
)

PROMPT_ESTRUCTURADO = """Analiza este recibo de sueldo de trabajador de vinas y responde UNICAMENTE con un JSON valido con esta estructura exacta:
{
  "trabajador": {
    "nombre": "nombre completo o 'No detectado'",
    "dni": "DNI o 'No detectado'",
    "empleador": "nombre del empleador o 'No detectado'",
    "periodo": "mes y año del recibo o 'No detectado'",
    "categoria": "categoria laboral o 'No detectado'",
    "fecha_ingreso": "fecha de inicio del contrato o relacion laboral en formato DD/MM/AAAA. BUSCAR en todo el recibo: fecha ingreso, fecha inicio, antiguedad, ingreso, alta. Si no esta explícita pero hay datos de antiguedad calcularla. Si no se encuentra poner 'No detectado'"
  },
  "montos": {
    "sueldo_basico": "monto o 'No detectado'",
    "total_bruto": "monto o 'No detectado'",
    "total_neto": "monto o 'No detectado'",
    "descuentos": "monto total de descuentos o 'No detectado'"
  },
  "analisis": "Analisis detallado del recibo verificando si los montos son correctos segun la Ley de Vinas 20.589 y escala salarial vigente. Minimo 3 parrafos.",
  "irregularidades": ["Irregularidad 1 con articulo de ley violado"],
  "recomendaciones": ["Recomendacion 1 con pasos concretos"],
  "conclusion": "Conclusion final sobre si el recibo es correcto o tiene problemas graves"
}
Si no hay irregularidades, la lista debe ser: ["Sin irregularidades detectadas"]
Responde SOLO con el JSON, sin texto adicional, sin backticks."""

# ============================================================
# 5. GENERADOR DE PDF
# ============================================================
def generar_pdf_reporte(datos: dict, numero_reporte: str) -> str:
    ruta_pdf = f"/tmp/dictamen_{numero_reporte}.pdf"
    doc = SimpleDocTemplate(ruta_pdf, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle('Titulo', parent=styles['Title'], fontSize=16,
        textColor=colors.HexColor('#1a237e'), spaceAfter=6, alignment=TA_CENTER, fontName='Helvetica-Bold')
    estilo_subtitulo = ParagraphStyle('Subtitulo', parent=styles['Normal'], fontSize=11,
        textColor=colors.HexColor('#37474f'), spaceAfter=4, alignment=TA_CENTER)
    estilo_seccion = ParagraphStyle('Seccion', parent=styles['Heading2'], fontSize=12,
        textColor=colors.HexColor('#1a237e'), spaceBefore=14, spaceAfter=6, fontName='Helvetica-Bold')
    estilo_normal = ParagraphStyle('Normal2', parent=styles['Normal'], fontSize=10,
        spaceAfter=6, alignment=TA_JUSTIFY, leading=14)
    estilo_item = ParagraphStyle('Item', parent=styles['Normal'], fontSize=10,
        spaceAfter=4, leftIndent=15, leading=13)
    estilo_footer = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8,
        textColor=colors.grey, alignment=TA_CENTER)
    estilo_alerta = ParagraphStyle('Alerta', parent=styles['Normal'], fontSize=10,
        textColor=colors.HexColor('#b71c1c'), spaceAfter=4, leftIndent=15, leading=13)

    story = []
    fecha_hoy = datetime.datetime.now().strftime("%d/%m/%Y")
    hora_hoy = datetime.datetime.now().strftime("%H:%M")
    trabajador = datos.get("trabajador", {})
    montos = datos.get("montos", {})

    story.append(Paragraph("ASISTENTE LEGAL Y CONTABLE", estilo_titulo))
    story.append(Paragraph("Especialista en Ley de Vinas 20.589 y 23.154", estilo_subtitulo))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1a237e'), spaceAfter=8))

    datos_reporte = [["N de Reporte:", numero_reporte, "Fecha:", fecha_hoy], ["Hora:", hora_hoy, "Generado por:", "Bot Legal IA"]]
    tabla_reporte = Table(datos_reporte, colWidths=[3.5*cm, 5.5*cm, 2.5*cm, 5.5*cm])
    tabla_reporte.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#37474f')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(tabla_reporte)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=6))

    story.append(Paragraph("DATOS DEL TRABAJADOR", estilo_seccion))
    datos_tabla = [
        ["Trabajador:", trabajador.get("nombre", "No detectado")],
        ["DNI:", trabajador.get("dni", "No detectado")],
        ["Empleador:", trabajador.get("empleador", "No detectado")],
        ["Periodo:", trabajador.get("periodo", "No detectado")],
        ["Categoria:", trabajador.get("categoria", "No detectado")],
    ]
    tabla_trabajador = Table(datos_tabla, colWidths=[4*cm, 13*cm])
    tabla_trabajador.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.HexColor('#f5f5f5'), colors.white]),
        ('GRID', (0,0), (-1,-1), 0.3, colors.lightgrey),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(tabla_trabajador)

    story.append(Paragraph("MONTOS DEL RECIBO", estilo_seccion))
    datos_montos = [
        ["Concepto", "Monto"],
        ["Sueldo Basico", montos.get("sueldo_basico", "No detectado")],
        ["Total Bruto", montos.get("total_bruto", "No detectado")],
        ["Descuentos", montos.get("descuentos", "No detectado")],
        ["Total Neto (a cobrar)", montos.get("total_neto", "No detectado")],
    ]
    tabla_montos = Table(datos_montos, colWidths=[10*cm, 7*cm])
    tabla_montos.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f5f5f5'), colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e8eaf6')),
    ]))
    story.append(tabla_montos)

    # Sección calculadora de antigüedad si hay fecha de ingreso
    antiguedad = datos.get("antiguedad", {})
    if antiguedad and not antiguedad.get("error"):
        story.append(Paragraph("⚠️ COSTO REAL SI ACEPTA EL MONOTRIBUTO", estilo_seccion))
        story.append(Paragraph(
            f"Fecha de ingreso detectada: {antiguedad.get('fecha_ingreso', 'No detectada')} — "
            f"Antigüedad: {antiguedad.get('antiguedad_texto', '')}",
            estilo_normal
        ))
        tiene_sueldo = antiguedad.get("tiene_sueldo", False)
        datos_antig = [
            ["Concepto", "Monto"],
            ["Indemnización por antigüedad (Art. 245 LCT)",
             f"${antiguedad.get('indemnizacion',0):,.0f}" if tiene_sueldo else "Requiere sueldo"],
            ["SAC proporcional",
             f"${antiguedad.get('sac_proporcional',0):,.0f}" if tiene_sueldo else "Requiere sueldo"],
            ["Preaviso",
             f"${antiguedad.get('preaviso',0):,.0f}" if tiene_sueldo else "Requiere sueldo"],
            ["Seguro Desempleo RENATRE (Res. 19/2026)", f"${antiguedad.get('renatre',0):,.0f}"],
            ["TOTAL QUE LE REGALÁS AL PATRÓN",
             f"${antiguedad.get('total_perdida',0):,.0f}" if tiene_sueldo else f"${antiguedad.get('renatre',0):,.0f} + indemnización"],
        ]
        tabla_antig = Table(datos_antig, colWidths=[11*cm, 6*cm])
        tabla_antig.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#b71c1c')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#ffebee'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#b71c1c')),
            ('TEXTCOLOR', (0,-1), (-1,-1), colors.white),
        ]))
        story.append(tabla_antig)
        story.append(Paragraph(
            "⚠️ Usted tiene derechos adquiridos. Pasar a monotributo implica regalarle "
            "al patrón todos sus años de antigüedad acumulados. "
            "No firme su propia renuncia disfrazada de contrato independiente.",
            estilo_alerta
        ))
        story.append(Spacer(1, 8))

    story.append(Paragraph("ANALISIS LEGAL Y CONTABLE", estilo_seccion))
    for parrafo in datos.get("analisis", "Sin analisis.").split('\n'):
        if parrafo.strip():
            story.append(Paragraph(parrafo.strip(), estilo_normal))

    story.append(Paragraph("IRREGULARIDADES DETECTADAS", estilo_seccion))
    irregularidades = datos.get("irregularidades", ["Sin irregularidades detectadas"])
    if irregularidades and irregularidades[0] != "Sin irregularidades detectadas":
        for irr in irregularidades:
            story.append(Paragraph(f"- {irr}", estilo_alerta))
    else:
        story.append(Paragraph("No se detectaron irregularidades.", estilo_normal))

    story.append(Paragraph("RECOMENDACIONES Y PASOS A SEGUIR", estilo_seccion))
    for rec in datos.get("recomendaciones", ["Conservar el recibo."]):
        story.append(Paragraph(f"- {rec}", estilo_item))

    story.append(Paragraph("CONCLUSION", estilo_seccion))
    tabla_conclusion = Table([[Paragraph(datos.get("conclusion", "Sin conclusion."), estilo_normal)]], colWidths=[17*cm])
    tabla_conclusion.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e8eaf6')),
        ('BORDER', (0,0), (-1,-1), 1, colors.HexColor('#1a237e')),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(tabla_conclusion)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=6))
    story.append(Paragraph(
        "Este reporte fue generado por inteligencia artificial con fines informativos. "
        "No reemplaza el asesoramiento de un abogado o contador matriculado.",
        estilo_footer))
    story.append(Paragraph(
        f"Generado el {fecha_hoy} a las {hora_hoy} | Bot Legal IA - Ley de Vinas",
        estilo_footer))

    doc.build(story)
    return ruta_pdf

# ============================================================
# 6. FUNCIÓN AUXILIAR
# ============================================================
async def enviar_mensaje_largo(message, texto):
    for i in range(0, len(texto), 4000):
        await message.reply_text(texto[i:i+4000])

# ============================================================
# 7. COMANDO /start — CON CONTROL DE ACCESO
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    nombre = update.message.from_user.full_name
    username = update.message.from_user.username

    # Usuario autorizado → menú normal
    if es_autorizado(user_id):
        limpiar_historial(user_id)
        texto = (
            "Hola! 🍷⚖️\n\n"
            "Soy tu Asistente Legal y Contable.\n"
            "Puedo analizar tus consultas por texto o revisar fotos/PDF de tus recibos.\n\n"
            "💬 Recuerdo toda nuestra conversacion, podes hacer preguntas de seguimiento.\n\n"
            "⚠️ Este bot brinda informacion orientativa basada en la legislacion vigente. No reemplaza el asesoramiento de un profesional matriculado.\n\n"
            "Que deseas hacer hoy?"
        )
        keyboard = [
            [InlineKeyboardButton("⚖️ Consultar Ley 20.589", callback_data='ley')],
            [InlineKeyboardButton("📊 Analizar mi Sueldo", callback_data='escala')],
            [InlineKeyboardButton("📝 Revisar mi Contrato", callback_data='contrato')],
            [InlineKeyboardButton("📸 Analizar Recibo/Foto", callback_data='recibo')],
            [InlineKeyboardButton("🤝 Nuestros Avales", callback_data='avales')],
            [InlineKeyboardButton("📋 Términos y Privacidad", callback_data='terminos')],
            [InlineKeyboardButton("📅 Calcular Antigüedad", callback_data='calcular_antiguedad')],
            [InlineKeyboardButton("📋 Formulario de Cosecha", callback_data='formulario_cosecha')],
            [InlineKeyboardButton("📊 Registro de Ventas", callback_data='registro_ventas')],
            [InlineKeyboardButton("📝 Registro de Tareas", callback_data='registro_tareas')],
            [InlineKeyboardButton("📋 Guía Formulario ReNAF", callback_data='formulario_renaf')],
            [InlineKeyboardButton("🍇 Informe Fin de Cosecha (INV)", callback_data='cosecha_inv')],
            [InlineKeyboardButton("🏦 Verificar Cheque", callback_data='verificar_cheque')],
            [InlineKeyboardButton("🗑️ Nueva Consulta", callback_data='nueva')]
        ]
        await update.message.reply_text(texto, reply_markup=InlineKeyboardMarkup(keyboard))

    # Ya pidió acceso, está esperando
    elif esta_pendiente(user_id):
        await update.message.reply_text(
            "⏳ Tu solicitud de acceso ya fue enviada.\n\n"
            "El administrador la revisara pronto. Te notificaremos cuando este aprobada."
        )

    # Usuario bloqueado
    elif es_bloqueado(user_id):
        await update.message.reply_text(
            "🚫 No tenés acceso a este bot.\n"
            "Comunicate con el administrador si creés que es un error."
        )

    # Usuario nuevo → pedir recibo para verificar
    else:
        agregar_pendiente(user_id, nombre, username or "")
        await update.message.reply_text(
            "🔐 *Bienvenido al Bot Legal de Viñas*\n\n"
            "Este bot es exclusivo para contratistas de viñas autorizados.\n\n"
            "📋 *Para solicitar acceso necesitamos verificar que sos contratista:*\n\n"
            "📸 Enviá una foto o PDF de tu recibo de sueldo como contratista de viñas.\n\n"
            "Una vez verificado, el administrador te dará acceso. ⏳",
            parse_mode='Markdown'
        )

# ============================================================
# 8. MANEJO DE BOTONES
# ============================================================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # ── Botones del ADMIN para aprobar/rechazar ──
    if query.data.startswith("auth_"):
        if user_id != ADMIN_ID:
            await query.message.reply_text("No tenes permiso para esto.")
            return
        nuevo_user_id = int(query.data.split("_")[1])
        autorizar_usuario(nuevo_user_id)

        # Notificar al usuario aprobado
        await context.bot.send_message(
            chat_id=nuevo_user_id,
            text=(
                "✅ *Acceso aprobado!*\n\n"
                "Ya podes usar el Asistente Legal y Contable de Vinas.\n"
                "Escribi /start para comenzar. 🍷⚖️\n\n"
                "📋 Usa /terminos para ver los terminos de uso y privacidad."
            ),
            parse_mode='Markdown'
        )
        await query.message.edit_text(f"✅ Usuario {nuevo_user_id} autorizado correctamente.")
        return

    if query.data.startswith("reject_"):
        if user_id != ADMIN_ID:
            await query.message.reply_text("No tenes permiso para esto.")
            return
        nuevo_user_id = int(query.data.split("_")[1])
        rechazar_usuario(nuevo_user_id)
        await context.bot.send_message(
            chat_id=nuevo_user_id,
            text="❌ Tu solicitud de acceso fue rechazada. Comunicate con el administrador para mas informacion."
        )
        await query.message.edit_text(f"❌ Usuario {nuevo_user_id} rechazado.")
        return

    if query.data.startswith("block_"):
        if user_id != ADMIN_ID:
            await query.message.reply_text("No tenes permiso para esto.")
            return
        nuevo_user_id = int(query.data.split("_")[1])
        bloquear_usuario(nuevo_user_id)
        await context.bot.send_message(
            chat_id=nuevo_user_id,
            text="🚫 Tu acceso al bot ha sido bloqueado. Comunicate con el administrador para mas informacion."
        )
        await query.message.edit_text(f"🚫 Usuario {nuevo_user_id} bloqueado.")
        return

    if query.data.startswith("unblock_"):
        if user_id != ADMIN_ID:
            await query.message.reply_text("No tenes permiso para esto.")
            return
        nuevo_user_id = int(query.data.split("_")[1])
        desbloquear_usuario(nuevo_user_id)
        await context.bot.send_message(
            chat_id=nuevo_user_id,
            text="✅ Tu bloqueo fue levantado. Podés volver a solicitar acceso escribiendo /start."
        )
        await query.message.edit_text(f"✅ Usuario {nuevo_user_id} desbloqueado.")
        return

    if query.data.startswith("revoke_"):
        if user_id != ADMIN_ID:
            await query.message.reply_text("No tenes permiso para esto.")
            return
        nuevo_user_id = int(query.data.split("_")[1])
        revocar_acceso(nuevo_user_id)
        await context.bot.send_message(
            chat_id=nuevo_user_id,
            text="⚠️ Tu acceso al bot fue revocado. Podes volver a solicitar acceso enviando tu recibo."
        )
        await query.message.edit_text(f"⚠️ Acceso revocado para usuario {nuevo_user_id}.")
        return

    # ── Verificar acceso para el resto de botones ──
    if not es_autorizado(user_id):
        await query.message.reply_text("No tenes acceso. Escribi /start para solicitar acceso.")
        return

    # ── Botón de audio ──
    if query.data.startswith("audio_"):
        partes_data = query.data.split("_")
        target_user_id = int(partes_data[1])
        parte = int(partes_data[2]) if len(partes_data) > 2 else 0
        respuesta_cached = cache_respuestas.get(target_user_id)
        
        if not respuesta_cached:
            await query.message.reply_text("⚠️ No hay respuesta disponible para convertir a audio.")
            return
        
        await query.answer("🎵 Generando audio...")
        procesando = await query.message.reply_text("⏳ Generando audio con voz femenina...")
        
        try:
            if parte == 1:
                texto_audio = respuesta_cached[:4500]
            elif parte == 2:
                texto_audio = respuesta_cached[4500:]
            else:
                texto_audio = respuesta_cached
            audio_bytes = generar_audio(texto_audio)
            await procesando.delete()
            
            import io
            audio_io = io.BytesIO(audio_bytes)
            audio_io.name = "respuesta.mp3"
            
            await query.message.reply_voice(voice=audio_io)
        except Exception as e:
            print(f"Error TTS: {e}")
            await procesando.edit_text(f"❌ No se pudo generar el audio. Error: {str(e)[:200]}")
        return

    # ── Menú Experto en Vid ──
    if query.data == 'menu_vid':
        if not es_autorizado(user_id):
            await query.message.reply_text("No tenés acceso. Escribí /start para solicitar acceso.")
            return
        keyboard_vid = [
            [InlineKeyboardButton("🔬 Consultar sobre plagas", callback_data='vid_plagas')],
            [InlineKeyboardButton("🍃 Enfermedades de la vid", callback_data='vid_enfermedades')],
            [InlineKeyboardButton("✂️ Poda y conducción", callback_data='vid_poda')],
            [InlineKeyboardButton("🧪 Tratamientos químicos", callback_data='vid_quimicos')],
            [InlineKeyboardButton("📸 Foto → Detectar plaga", callback_data='vid_foto')],
            [InlineKeyboardButton("💬 Consulta libre sobre vid", callback_data='vid_consulta')],
            [InlineKeyboardButton("🔙 Volver al Menú", callback_data='menu_principal')]
        ]
        await query.message.reply_text(
            "🌿 *Experto en Vid*\n\n"
            "Soy tu asistente técnico especializado en viticultura.\n"
            "¿Sobre qué querés consultar?",
            reply_markup=InlineKeyboardMarkup(keyboard_vid),
            parse_mode='Markdown'
        )
        return

    if query.data == 'vid_foto':
        context.user_data['modo'] = 'vid_foto'
        await query.message.reply_text(
            "📸 *Detección de plagas por imagen*\n\n"
            "Sacá una foto clara de:\n"
            "• La hoja afectada\n"
            "• El racimo o fruto\n"
            "• El tronco o sarmiento\n"
            "• El insecto o síntoma visible\n\n"
            "Enviame la foto y analizaré qué plaga o enfermedad es y cómo tratarla. 🔬",
            parse_mode='Markdown'
        )
        return

    if query.data == 'vid_plagas':
        context.user_data['modo'] = 'vid_texto'
        await query.message.reply_text(
            "🔬 *Consultor de Plagas*\n\n"
            "Describime qué síntomas ves en la vid y te digo qué plaga es y cómo tratarla.\n\n"
            "Ejemplo: *'Las hojas tienen manchas amarillas y por debajo un moho grisáceo'*",
            parse_mode='Markdown'
        )
        return

    if query.data == 'vid_enfermedades':
        context.user_data['modo'] = 'vid_texto'
        await query.message.reply_text(
            "🍃 *Enfermedades de la Vid*\n\n"
            "Contame qué síntomas observás y en qué parte de la planta.\n\n"
            "Ejemplo: *'Los racimos se cubren de un polvo blanco'*",
            parse_mode='Markdown'
        )
        return

    if query.data == 'vid_poda':
        context.user_data['modo'] = 'vid_texto'
        await query.message.reply_text(
            "✂️ *Poda y Conducción*\n\n"
            "Haceme tu consulta sobre poda, conducción, atado o manejo del follaje.\n\n"
            "Ejemplo: *'¿Cuándo es el momento ideal para podar en Mendoza?'*",
            parse_mode='Markdown'
        )
        return

    if query.data == 'vid_quimicos':
        context.user_data['modo'] = 'vid_texto'
        await query.message.reply_text(
            "🧪 *Tratamientos Químicos*\n\n"
            "Consultame sobre productos, dosis, momentos de aplicación o mezclas.\n\n"
            "Ejemplo: *'¿Qué fungicida uso para peronospora y en qué dosis?'*",
            parse_mode='Markdown'
        )
        return

    if query.data == 'vid_consulta':
        context.user_data['modo'] = 'vid_texto'
        await query.message.reply_text(
            "💬 *Consulta Libre sobre Vid*\n\n"
            "Preguntame lo que quieras sobre viticultura, enología o manejo del viñedo.",
            parse_mode='Markdown'
        )
        return

    if query.data == 'calcular_antiguedad':
        if not es_autorizado(user_id):
            await query.message.reply_text("No tenés acceso. Escribí /start para solicitar acceso.")
            return
        context.user_data['modo'] = ''
        await query.message.reply_text(
            "📅 *Calculadora de Antigüedad*\n\n"
            "Enviame la foto o PDF de tu recibo de sueldo y calcularé automáticamente:\n\n"
            "• Años de antigüedad\n"
            "• Indemnización que perderías\n"
            "• SAC proporcional\n"
            "• Seguro Desempleo RENATRE\n"
            "• *Total que le regalás al patrón si aceptás el monotributo* 🚨",
            parse_mode="Markdown"
        )
        return

    if query.data == 'registro_tareas':
        await query.answer()
        context.user_data['modo'] = 'registro_tareas'
        context.user_data['tareas_paso'] = 0
        context.user_data['tareas_datos'] = {}
        await query.message.reply_text(
            "📝 *Registro de Tareas y Labores*\n\nVoy a generar tu registro personalizado según Art. 6 y 11 Ley 20.589.\n\n¿Cuál es tu nombre completo?",
            parse_mode="Markdown"
        )
        return

    if query.data == 'registro_ventas':
        await query.answer()
        context.user_data['modo'] = 'registro_ventas'
        context.user_data['registro_paso'] = 0
        context.user_data['registro_datos'] = {}
        await query.message.reply_text(
            "📊 *Registro de Ventas de Produccion*\n\n"
            "Voy a generar el registro personalizado con tus datos.\n\n"
            "¿Cuál es tu nombre completo?",
            parse_mode="Markdown"
        )
        return

    if query.data == 'cosecha_inv':
        await query.answer()
        context.user_data['modo'] = 'cosecha_inv'
        context.user_data['cinv_paso'] = 0
        context.user_data['cinv_datos'] = {}
        context.user_data['cinv_fase'] = 'fijas'
        await query.message.reply_text(
            "🍇 *Informe de Finalización de Cosecha (INV)*\n\n"
            "Te voy a hacer unas preguntas para armar el informe oficial del INV para el Convenio de Corresponsabilidad Gremial (Tarifa Sustitutiva).\n\n"
            "💡 Es uno por cada viñedo. Si trabajaste en varias fincas, después generás uno por cada una.\n\n"
            "Empecemos:\n\nPREGUNTA 1\n\n¿Fecha del informe? (DD/MM/AAAA)\n📝 Ejemplo: 15/06/2026",
            parse_mode="Markdown"
        )
        return
    if query.data == 'verificar_cheque':
        await query.answer()
        context.user_data['modo'] = 'esperando_cheque'
        await query.message.reply_text(
            "⚖️ *Información importante y aviso legal*\n\n"
            "📋 *Fuentes:* datos públicos del BCRA (cheques rechazados/denunciados, "
            "situación crediticia) y de ARCA/AFIP (datos fiscales). La información puede "
            "tener retrasos; la base del BCRA se actualiza mensualmente.\n\n"
            "📸 *La lectura puede fallar:* si el cheque tiene sello, manchas o algo que "
            "tape los números, el OCR puede equivocarse. En ese caso ingresá el CUIT a mano.\n\n"
            "⚠️ *Aviso legal:* información orientativa, no es asesoramiento legal ni "
            "financiero. No nos responsabilizamos por decisiones tomadas solo con estos "
            "datos. Verificá discrepancias con el organismo emisor. Los datos son de fuentes "
            "públicas oficiales y deben usarse solo para verificar operaciones comerciales "
            "legítimas. El uso indebido es responsabilidad del usuario.",
            parse_mode="Markdown"
        )
        await query.message.reply_text(
            "🏦 *Verificación de Cheque*\n\n"
            "📸 Enviá una *foto del cheque* y voy a leer el CUIT automáticamente.\n\n"
            "✍️ O escribí directamente el *CUIT/CUIL* del emisor "
            "(11 números, con o sin guiones).",
            parse_mode="Markdown"
        )
        return
    if query.data == 'cheque_corregir':
        await query.answer()
        context.user_data['modo'] = 'esperando_cheque'
        await query.message.reply_text(
            "✍️ Escribí el *CUIT/CUIL* correcto del emisor "
            "(11 números), o enviá otra foto del cheque.",
            parse_mode="Markdown"
        )
        return
    if query.data == 'cheque_confirmar':
        await query.answer()
        cuit = context.user_data.get('cheque_cuit', '')
        if len(cuit) != 11:
            await query.message.reply_text("⚠️ No tengo un CUIT válido. Empezá de nuevo desde el menú.")
            return
        espera = await query.message.reply_text("🏦 Consultando el BCRA... ⏳")
        try:
            banco = context.user_data.get('cheque_banco')
            nro = context.user_data.get('cheque_nro')
            reporte = cheque_bcra.verificar_completo(cuit, banco, nro)
            if not reporte.get('ok'):
                await espera.edit_text(f"❌ {reporte.get('error', 'Error en la consulta')}")
                return
            # Resumen en el chat
            aviso_juicio = "\n⚖️ *ATENCIÓN: Hay cheques con proceso judicial.*\n" if reporte.get('hay_juicio') else ""
            resumen = (
                f"{reporte['emoji']} *{reporte['nivel']}*\n\n"
                f"👤 *{reporte['nombre']}*\n"
                f"🆔 CUIT: {cuit}\n\n"
                f"{reporte['resumen']}\n"
                f"{aviso_juicio}\n"
                f"📄 Te envío el informe completo en PDF."
            )
            await espera.edit_text(resumen, parse_mode="Markdown")
            # PDF
            explicacion = cheque_bcra.generar_explicacion(reporte, model)
            pdf_bytes = cheque_bcra.generar_pdf(reporte, explicacion)
            import io as _io
            pdf_file = _io.BytesIO(pdf_bytes)
            pdf_file.name = f"verificacion_cheque_{cuit}.pdf"
            await query.message.reply_document(
                document=pdf_file,
                filename=f"verificacion_cheque_{cuit}.pdf",
                caption="📄 Verificación de Cheque - BotContador"
            )
            context.user_data['modo'] = ''
        except Exception as e:
            await espera.edit_text(f"❌ Error: {str(e)[:150]}")
        return
    if query.data == 'formulario_renaf':
        await query.answer()
        context.user_data['modo'] = 'formulario_renaf'
        context.user_data['renaf_paso'] = 0
        context.user_data['renaf_datos'] = {}
        _msg_renaf = await query.message.reply_text(
            "📋 *Guía del Formulario ReNAF*\n\n"
            "Te voy a hacer 30 preguntas para armar una guía personalizada de cómo llenar tu formulario del Registro Nacional de la Agricultura Familiar.\n\n"
            "Respondé cada una con tus datos. Si alguna no la sabés, escribí *No sé*.\n\n"
            "Las secciones de pesca, ganadería y artesanía las salto porque no corresponden a viña.\n\n"
            "Empecemos:\n\nPREGUNTA 1/30\n\n¿Cuál es tu nombre? (solo nombre)",
            parse_mode="Markdown"
        )
        context.user_data['renaf_msg_id'] = _msg_renaf.message_id
        return
    if query.data == 'formulario_cosecha':
        await query.answer()
        context.user_data['modo'] = 'formulario_cosecha'
        context.user_data['cosecha_paso'] = 0
        context.user_data['cosecha_datos'] = {}
        await query.message.reply_text(
            "📋 *Formulario de Control de Cosecha*\n\n"
            "Voy a generar el formulario personalizado con tus datos.\n\n"
            "¿Cuál es tu nombre completo?",
            parse_mode="Markdown"
        )
        return

    if query.data == 'nueva':
        limpiar_historial(user_id)
        context.user_data['modo'] = ''
        context.user_data.pop('cheque_cuit', None)
        context.user_data.pop('cheque_banco', None)
        context.user_data.pop('cheque_nro', None)
        await query.message.reply_text("🗑️ Conversacion reiniciada. En que te puedo ayudar?")

    elif query.data == 'avales':
        keyboard_avales = [
            [InlineKeyboardButton("📊 Estudio Contable", callback_data='aval_contable')],
            [InlineKeyboardButton("⚖️ Abogado Laboral", callback_data='aval_abogado')],
            [InlineKeyboardButton("🏛️ Subsecretaría de Trabajo", callback_data='aval_subsecretaria')],
            [InlineKeyboardButton("👥 Sindicato de Contratistas", callback_data='aval_sindicato')],
        ]
        await query.message.reply_text(
            "🤝 *Nuestros Avales*\n\n"
            "El Bot Legal de Viñas está respaldado por profesionales e instituciones "
            "especializadas en derecho laboral vitivinícola.\n\n"
            "Seleccioná para ver información de contacto:",
            reply_markup=InlineKeyboardMarkup(keyboard_avales),
            parse_mode='Markdown'
        )

    elif query.data.startswith('aval_'):
        clave = query.data.replace('aval_', '')
        if clave in AVALES:
            texto = generar_texto_aval(clave)
            a = AVALES[clave]
            botones = []
            if a['whatsapp']:
                botones.append([InlineKeyboardButton("💬 Contactar por WhatsApp", url=f"https://wa.me/{a['whatsapp']}")])
            if a['web']:
                botones.append([InlineKeyboardButton("🌐 Visitar sitio web", url=a['web'])])
            botones.append([InlineKeyboardButton("🔙 Volver a Avales", callback_data='avales')])
            await query.message.reply_text(
                texto,
                reply_markup=InlineKeyboardMarkup(botones),
                parse_mode='Markdown'
            )

    elif query.data == 'avales':
        keyboard_avales = [
            [InlineKeyboardButton("📊 Estudio Contable", callback_data='aval_contable')],
            [InlineKeyboardButton("⚖️ Abogado Laboral", callback_data='aval_abogado')],
            [InlineKeyboardButton("🏛️ Subsecretaría de Trabajo", callback_data='aval_subsecretaria')],
            [InlineKeyboardButton("👥 Sindicato de Contratistas", callback_data='aval_sindicato')],
            [InlineKeyboardButton("🔙 Volver al Menú", callback_data='menu_principal')]
        ]
        await query.message.reply_text(
            "🤝 *Directorio de Avales*\n\n"
            "Estas instituciones avalan y colaboran con el Bot Legal de Viñas.\n"
            "Tocá cada una para ver sus datos de contacto:\n",
            reply_markup=InlineKeyboardMarkup(keyboard_avales),
            parse_mode='Markdown'
        )

    elif query.data.startswith('aval_'):
        clave = query.data.replace('aval_', '')
        if clave in AVALES:
            keyboard_volver = [[InlineKeyboardButton("🔙 Volver al Directorio", callback_data='avales')]]
            await query.message.reply_text(
                generar_tarjeta_aval(clave),
                reply_markup=InlineKeyboardMarkup(keyboard_volver),
                parse_mode='Markdown'
            )

    elif query.data == 'menu_principal':
        keyboard_menu = [
            [InlineKeyboardButton("⚖️ Consultar Ley 20.589", callback_data='ley')],
            [InlineKeyboardButton("📊 Analizar mi Sueldo", callback_data='escala')],
            [InlineKeyboardButton("📝 Revisar mi Contrato", callback_data='contrato')],
            [InlineKeyboardButton("📸 Analizar Recibo de Sueldo", callback_data='recibo')],
            [InlineKeyboardButton("🌿 Experto en Vid", callback_data='menu_vid')],
            [InlineKeyboardButton("🤝 Directorio de Avales", callback_data='avales')],
            [InlineKeyboardButton("📋 Términos y Privacidad", callback_data='terminos')],
            [InlineKeyboardButton("📅 Calcular Antigüedad", callback_data='calcular_antiguedad')],
            [InlineKeyboardButton("📋 Formulario de Cosecha", callback_data='formulario_cosecha')],
            [InlineKeyboardButton("📊 Registro de Ventas", callback_data='registro_ventas')],
            [InlineKeyboardButton("🗑️ Nueva Consulta", callback_data='nueva')]
        ]
        await query.message.reply_text(
            "Menú principal. ¿En qué te puedo ayudar?",
            reply_markup=InlineKeyboardMarkup(keyboard_menu)
        )

    elif query.data == 'terminos':
        await query.message.reply_text(TERMINOS_USO, parse_mode='Markdown')

    elif query.data == 'recibo':
        await query.answer()
        context.user_data['recibo_datos'] = {}
        context.user_data['recibo_paso'] = 0
        context.user_data['modo'] = 'esperando_recibo'
        await query.message.reply_text(
            PREGUNTAS_RECIBO[0][1],
            parse_mode='Markdown'
        )

    if query.data.startswith("informe_"):
        if not es_autorizado(user_id):
            await query.answer("No tenés acceso.")
            return
        await query.answer()
        historial = obtener_historial(user_id)
        if not historial or len(historial) < 2:
            await query.message.reply_text(
                "⚠️ Necesito más información para generar un informe útil.\n\n"
                "Contame tu situación primero: qué irregularidades tiene tu patrón, "
                "si te deben aportes, si no te entregan las pesadas, etc.\n\n"
                "Cuando hayas contado tu caso escribí /fin."
            )
            return
        context.user_data["formulario_informe"] = {}
        context.user_data["formulario_paso"] = 0
        context.user_data["modo"] = "formulario_informe"
        await query.message.reply_text(
            "📋 *Vamos a completar el informe de irregularidades.*\n"
            "Te voy a hacer algunas preguntas para personalizar el documento.\n\n"
            "Podés escribir /cancelar en cualquier momento para salir.",
            parse_mode="Markdown"
        )
        _, pregunta = PREGUNTAS_INFORME[0]
        await query.message.reply_text(pregunta)
        return

    if query.data == "cerrar_informe":
        await query.answer("Podés pedirlo cuando quieras con /fin")
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        return

    else:
        opciones = {
            'ley': "📚 Consultame sobre el Art. 6 (Obligaciones) o el Art. 12 (Indemnizacion 20%).",
            'escala': "📊 Dime cuantas hectareas trabajas y comparare tu sueldo con la Escala Salarial 2026.",
            'contrato': "📝 Describeme una clausula de tu contrato y te dire si es legal segun el Estatuto.",
            'recibo': "",
            'cerrar_informe': "",
            'menu_vid': ""
        }
        respuesta_opcion = opciones.get(query.data, "")
        if respuesta_opcion:
            await query.message.reply_text(respuesta_opcion)


# ============================================================
# PROCESAMIENTO DE AUDIO DE VOZ (Speech-to-Text)
# ============================================================
async def procesar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if es_bloqueado(user_id):
        await update.message.reply_text("🚫 No tenés acceso a este bot.")
        return

    if not es_autorizado(user_id):
        await update.message.reply_text("No tenés acceso. Escribí /start para solicitar acceso.")
        return

    aviso = await update.message.reply_text("🎙️ Transcribiendo tu audio...")
    try:
        # Descargar el audio de Telegram
        archivo_voz = await (update.message.voice or update.message.audio).get_file()
        byte_array = await archivo_voz.download_as_bytearray()
        # Convertir a formato compatible con Google Speech-to-Text
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp_in:
            tmp_in.write(bytes(byte_array))
            tmp_in_path = tmp_in.name
        tmp_out_path = tmp_in_path + "_conv.ogg"
        audio_seg = AudioSegment.from_file(tmp_in_path)
        audio_seg = audio_seg.set_channels(1).set_frame_rate(48000)
        audio_seg.export(tmp_out_path, format="ogg", codec="libopus")
        with open(tmp_out_path, "rb") as f:
            byte_array = bytearray(f.read())
        os.unlink(tmp_in_path)
        os.unlink(tmp_out_path)

        # Transcribir con Google Speech-to-Text
        client = speech.SpeechClient()
        audio = speech.RecognitionAudio(content=bytes(byte_array))
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            sample_rate_hertz=48000,
            language_code="es-AR",
            enable_automatic_punctuation=True,
        )
        response = client.recognize(config=config, audio=audio)

        if not response.results:
            await aviso.edit_text("❌ No pude entender el audio. Intentá hablar más claro o escribí tu consulta.")
            return

        texto_transcripto = " ".join([r.alternatives[0].transcript for r in response.results])
        await aviso.edit_text(f"🎙️ Entendí: *{texto_transcripto}*\n\n⏳ Consultando...", parse_mode="Markdown")

        # Procesar como si fuera texto normal
        contexto = construir_contexto(user_id)
        prompt_completo = (
            f"{SYSTEM_PROMPT}\n\n"
            f"{contexto}"
            f"Usuario: {texto_transcripto}\n"
            f"Asistente:"
        )
        res = model.generate_content(prompt_completo)
        respuesta = res.text
        print("✅ Respondió Gemini")

        agregar_al_historial(user_id, "user", texto_transcripto)
        agregar_al_historial(user_id, "model", respuesta)
        cache_respuestas[user_id] = respuesta

        if len(respuesta) > 4500:
            keyboard = [
                [InlineKeyboardButton("🔊 Escuchar parte 1", callback_data=f"audio_{user_id}_1")],
                [InlineKeyboardButton("🔊 Escuchar parte 2", callback_data=f"audio_{user_id}_2")]
            ]
        else:
            keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]

        await enviar_mensaje_largo(update.message, f"⚖️ {respuesta}")
        await update.message.reply_text(
            "¿Querés escuchar la respuesta en audio?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        print(f"Error voz: {e}")
        await aviso.edit_text(f"❌ Error al procesar el audio: {str(e)[:200]}")

# ============================================================
# PROCESAMIENTO DE VIDEO
# ============================================================
async def procesar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if es_bloqueado(user_id):
        await update.message.reply_text("🚫 No tenés acceso a este bot.")
        return

    if not es_autorizado(user_id):
        await update.message.reply_text("No tenés acceso. Escribí /start para solicitar acceso.")
        return

    aviso = await update.message.reply_text(
        "🎥 Recibí tu video. Analizando con IA...\n"
        "⏳ Esto puede tardar unos segundos según el tamaño."
    )
    try:
        # Obtener el video
        if update.message.video:
            archivo_video = await update.message.video.get_file()
            mime_type = "video/mp4"
        elif update.message.video_note:
            archivo_video = await update.message.video_note.get_file()
            mime_type = "video/mp4"
        else:
            await aviso.edit_text("❌ No pude procesar ese tipo de archivo.")
            return

        byte_array = await archivo_video.download_as_bytearray()

        # Verificar tamaño (máx 50MB para no saturar)
        if len(byte_array) > 50 * 1024 * 1024:
            await aviso.edit_text("❌ El video es muy grande. Máximo 50MB. Intentá con un video más corto.")
            return

        video_part = Part.from_data(data=bytes(byte_array), mime_type=mime_type)

        prompt_video = (
            f"{SYSTEM_PROMPT}\n\n"
            "Analizá este video y respondé:\n"
            "1. 📋 Qué muestra el video\n"
            "2. ⚖️ Si hay documentos visibles (recibos, contratos, romaneos), analizá su contenido legal\n"
            "3. 🔍 Si hay conversaciones o textos visibles, transcribí lo relevante\n"
            "4. ⚠️ Si detectás irregularidades laborales o legales, señalalas claramente\n"
            "5. 📌 Recomendaciones según la Ley 23.154\n\n"
            "Si el video muestra una conversación con el patrón, analizá si hay violaciones legales en lo que dice.\n"
            "Aclaración importante: En Argentina, grabar una conversación propia es legal (doctrina de grabación unilateral)."
        )

        res = model.generate_content([prompt_video, video_part])
        respuesta = res.text

        agregar_al_historial(user_id, "user", "Envié un video para análisis legal")
        agregar_al_historial(user_id, "model", respuesta)
        cache_respuestas[user_id] = respuesta

        keyboard = [[InlineKeyboardButton("🔊 Escuchar análisis", callback_data=f"audio_{user_id}")]]
        await aviso.delete()
        await enviar_mensaje_largo(update.message, f"🎥 *ANÁLISIS DEL VIDEO*\n\n{respuesta}")
        await update.message.reply_text(
            "¿Querés escuchar el análisis en audio?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        print(f"Error video: {e}")
        await aviso.edit_text(f"❌ Error al analizar el video: {str(e)[:200]}")



# ============================================================
# CALCULADORA DE ANTIGÜEDAD
# ============================================================
def calcular_antiguedad(fecha_ingreso_str: str, sueldo_neto: float = 0) -> dict:
    """Calcula antigüedad e indemnización a partir de fecha de ingreso"""
    try:
        formatos = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"]
        fecha_ingreso = None
        for fmt in formatos:
            try:
                fecha_ingreso = datetime.datetime.strptime(fecha_ingreso_str.strip(), fmt)
                break
            except: pass
        if not fecha_ingreso:
            return {"error": "Formato de fecha no reconocido"}

        hoy = datetime.datetime.now()
        diff = hoy - fecha_ingreso
        años = diff.days // 365
        meses = (diff.days % 365) // 30
        dias = diff.days % 30

        # Cálculos
        indemnizacion = sueldo_neto * max(años, 1) if sueldo_neto > 0 else 0
        sac_prop = (sueldo_neto / 12) * (hoy.month if hoy.month <= 6 else hoy.month - 6) if sueldo_neto > 0 else 0
        preaviso = sueldo_neto if años < 5 else sueldo_neto * 2 if sueldo_neto > 0 else 0
        renatre = 367602
        total_perdida = indemnizacion + sac_prop + preaviso + renatre

        return {
            "fecha_ingreso": fecha_ingreso.strftime("%d/%m/%Y"),
            "años": años,
            "meses": meses,
            "dias": dias,
            "antiguedad_texto": f"{años} años, {meses} meses y {dias} días",
            "indemnizacion": indemnizacion,
            "sac_proporcional": sac_prop,
            "preaviso": preaviso,
            "renatre": renatre,
            "total_perdida": total_perdida,
            "tiene_sueldo": sueldo_neto > 0
        }
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# 9. PROCESAMIENTO DE ARCHIVOS
# ============================================================
async def procesar_archivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    # Capturar fotos de documentos cuando está en modo esperando_recibo
    modo_actual = context.user_data.get('modo', '')
    if modo_actual == 'esperando_cheque':
        if not update.message.photo and not update.message.document:
            return
        aviso = await update.message.reply_text("🔍 Leyendo el cheque... ⏳")
        try:
            if update.message.photo:
                file_obj = await update.message.photo[-1].get_file()
            else:
                file_obj = await update.message.document.get_file()
            file_bytes = bytes(await file_obj.download_as_bytearray())
            prompt_cheque = cheque_bcra.construir_prompt_ocr()
            imagen_part = Part.from_data(file_bytes, mime_type="image/jpeg")
            res = model.generate_content([prompt_cheque, imagen_part])
            texto = (res.text or "").strip()
            import json as _json, re as _re
            cuit_detectado = ""
            try:
                _m = _re.search(r"\{.*\}", texto, _re.DOTALL)
                _datos = _json.loads(_m.group(0)) if _m else {}
                cuit_detectado = "".join(filter(str.isdigit, str(_datos.get("cuit") or "")))
                context.user_data['cheque_banco'] = _datos.get("codigo_banco")
                context.user_data['cheque_nro'] = _datos.get("numero_cheque")
            except Exception:
                cuit_detectado = "".join(filter(str.isdigit, texto))[:11]
            await aviso.delete()
            if len(cuit_detectado) == 11:
                context.user_data['cheque_cuit'] = cuit_detectado
                cuit_fmt = f"{cuit_detectado[:2]}-{cuit_detectado[2:10]}-{cuit_detectado[10:]}"
                keyboard = [[
                    InlineKeyboardButton("✅ Sí, consultar", callback_data='cheque_confirmar'),
                    InlineKeyboardButton("❌ No, corregir", callback_data='cheque_corregir')
                ]]
                await update.message.reply_text(
                    f"📋 Detecté el CUIT: *{cuit_fmt}*\n\n¿Es correcto?",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    "⚠️ No pude leer el CUIT en la foto.\n\n"
                    "Por favor, escribí el *CUIT/CUIL* del emisor a mano "
                    "(11 números, con o sin guiones).",
                    parse_mode="Markdown"
                )
        except Exception as e:
            await aviso.edit_text(f"❌ Error leyendo el cheque: {str(e)[:100]}")
        return
    if modo_actual == 'esperando_recibo':
        paso = context.user_data.get('recibo_paso', 0)
        textos = context.user_data.get('recibo_textos', {})
        pasos_docs = {0: "contrato", 1: "declaracion", 2: "recibo", 3: "riego"}
        
        if paso < 4:
            tipo_doc = pasos_docs.get(paso, "documento")
            aviso = await update.message.reply_text(f"🔍 Leyendo el {tipo_doc}... ⏳")
            
            try:
                if update.message.photo:
                    file_obj = await update.message.photo[-1].get_file()
                elif update.message.document:
                    file_obj = await update.message.document.get_file()
                else:
                    await aviso.edit_text("❌ No pude leer la imagen. Enviá una foto directa.")
                    return
                
                file_bytes = bytes(await file_obj.download_as_bytearray())
                texto_extraido = await extraer_texto_documento(file_bytes, tipo_doc)
                textos[tipo_doc] = texto_extraido
                context.user_data['recibo_textos'] = textos
                
                siguiente = paso + 1
                context.user_data['recibo_paso'] = siguiente
                await aviso.delete()
                
                if siguiente < len(PREGUNTAS_RECIBO):
                    _, pregunta = PREGUNTAS_RECIBO[siguiente]
                    await update.message.reply_text(
                        f"✅ {tipo_doc.capitalize()} leído correctamente.\n\n{pregunta}",
                        parse_mode="Markdown"
                    )
                else:
                    context.user_data['modo'] = ''
            except Exception as e:
                await aviso.edit_text(f"❌ Error leyendo el documento: {str(e)[:100]}")
        return
    nombre = update.message.from_user.full_name
    username = update.message.from_user.username or "sin_username"

    # Usuario bloqueado
    if es_bloqueado(user_id):
        await update.message.reply_text("🚫 No tenés acceso a este bot.")
        return

    # Usuario pendiente → está enviando recibo para verificación
    if esta_pendiente(user_id) and not es_autorizado(user_id):
        aviso = await update.message.reply_text("⏳ Verificando tu recibo... por favor espera.")
        try:
            # Reenviar el archivo al admin para que lo vea
            keyboard_admin = [
                [
                    InlineKeyboardButton("✅ Autorizar", callback_data=f"auth_{user_id}"),
                    InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{user_id}"),
                    InlineKeyboardButton("🚫 Bloquear", callback_data=f"block_{user_id}")
                ]
            ]
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🔔 *Solicitud de acceso con recibo*\n\n"
                    f"👤 Nombre: {nombre}\n"
                    f"🆔 ID: `{user_id}`\n"
                    f"📱 Usuario: @{username}\n\n"
                    f"📎 Recibo adjunto abajo. ¿Autorizás el acceso?"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard_admin),
                parse_mode="Markdown"
            )
            # Reenviar el archivo al admin
            if update.message.photo:
                await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id)
            elif update.message.document:
                await context.bot.send_document(chat_id=ADMIN_ID, document=update.message.document.file_id)

            await aviso.edit_text(
                "✅ Tu recibo fue enviado al administrador para verificación.\n\n"
                "Te notificaremos cuando tu acceso sea aprobado. ⏳"
            )
        except Exception as e:
            print(f"Error verificacion: {e}")
            await aviso.edit_text("❌ Error al enviar tu recibo. Intentá de nuevo.")
        return

    if not es_autorizado(user_id):
        await update.message.reply_text("No tenés acceso. Escribí /start para solicitar acceso.")
        return

    # Modo detección de plaga por foto
    modo = context.user_data.get('modo', '')
    if modo == 'vid_foto' and update.message.photo:
        context.user_data['modo'] = ''
        aviso = await update.message.reply_text("🔬 Analizando imagen para detectar plaga o enfermedad...")
        try:
            archivo = await update.message.photo[-1].get_file()
            byte_array = await archivo.download_as_bytearray()
            imagen_part = Part.from_data(data=bytes(byte_array), mime_type="image/jpeg")

            prompt_plaga = (
                f"{SYSTEM_PROMPT_VID}\n\n"
                "Analizá esta imagen de la vid y respondé con:\n"
                "1. 🔍 Qué ves en la imagen (descripción detallada)\n"
                "2. 🦠 Diagnóstico: qué plaga, enfermedad o problema es\n"
                "3. ⚠️ Nivel de gravedad (leve / moderado / grave)\n"
                "4. 💊 Tratamiento recomendado con productos específicos y dosis\n"
                "5. 📅 Momento y frecuencia de aplicación\n"
                "6. 🛡️ Medidas preventivas para el futuro\n\n"
                "Si la imagen no muestra una planta de vid o no es posible diagnosticar, indicalo claramente."
            )

            res = model.generate_content([prompt_plaga, imagen_part])
            respuesta = res.text

            cache_respuestas[user_id] = respuesta
            agregar_al_historial(user_id, "user", "Envié una foto de mi viñedo para análisis de plaga")
            agregar_al_historial(user_id, "model", respuesta)

            keyboard = [[InlineKeyboardButton("🔊 Escuchar diagnóstico", callback_data=f"audio_{user_id}")],
                        [InlineKeyboardButton("🌿 Volver al Experto en Vid", callback_data="menu_vid")]]

            await aviso.delete()
            await enviar_mensaje_largo(update.message, f"🔬 *DIAGNÓSTICO DE LA VID*\n\n{respuesta}")
            await update.message.reply_text(
                "¿Querés escuchar el diagnóstico o hacer otra consulta?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"Error vid foto: {e}")
            await aviso.edit_text(f"❌ No pude analizar la imagen. Error: {str(e)[:200]}")
        return

    aviso = await update.message.reply_text("⏳ Analizando documento con IA... por favor espera.")

    try:
        contenido_parts = []
        es_imagen = False

        if update.message.photo:
            archivo = await update.message.photo[-1].get_file()
            byte_array = await archivo.download_as_bytearray()
            contenido_parts = [Part.from_data(data=bytes(byte_array), mime_type="image/jpeg")]
            es_imagen = True

        elif update.message.document:
            archivo = await update.message.document.get_file()
            mime = update.message.document.mime_type
            byte_array = await archivo.download_as_bytearray()

            if mime == "application/pdf":
                try:
                    lector = PyPDF2.PdfReader(io.BytesIO(bytes(byte_array)))
                    texto_pdf = ""
                    for pag in lector.pages:
                        texto_pdf += pag.extract_text() or ""
                except:
                    texto_pdf = ""

                if not texto_pdf.strip():
                    await aviso.edit_text(
                        "⚠️ El PDF parece ser una imagen escaneada sin texto extraible.\n\n"
                        "📸 Por favor, envia una foto directa del recibo."
                    )
                    return
                contenido_parts = [texto_pdf]

            elif mime in ["image/jpeg", "image/png", "image/webp", "image/gif"]:
                contenido_parts = [Part.from_data(data=bytes(byte_array), mime_type=mime)]
                es_imagen = True
            else:
                await aviso.edit_text("❌ Formato no soportado. Envia una imagen JPG/PNG o un PDF.")
                return
        else:
            await aviso.delete()
            return

        await aviso.edit_text("🔍 Extrayendo datos del recibo...")

        if es_imagen:
            prompt_json = f"{SYSTEM_PROMPT}\n\n{PROMPT_ESTRUCTURADO}"
            res_json = model.generate_content([prompt_json] + contenido_parts)
        else:
            texto_recibo = contenido_parts[0]
            prompt_json = f"{SYSTEM_PROMPT}\n\n{PROMPT_ESTRUCTURADO}\n\nCONTENIDO DEL RECIBO:\n{texto_recibo}"
            res_json = model.generate_content(prompt_json)

        try:
            texto_respuesta = res_json.text.strip().replace("```json", "").replace("```", "").strip()
            datos = json.loads(texto_respuesta)
        except:
            datos = {
                "trabajador": {"nombre": "No detectado", "dni": "No detectado", "empleador": "No detectado", "periodo": "No detectado", "categoria": "No detectado"},
                "montos": {"sueldo_basico": "No detectado", "total_bruto": "No detectado", "total_neto": "No detectado", "descuentos": "No detectado"},
                "analisis": res_json.text,
                "irregularidades": ["Ver analisis completo"],
                "recomendaciones": ["Consultar con un profesional habilitado"],
                "conclusion": "Analisis completado."
            }

        # Calcular antigüedad antes de generar el PDF
        fecha_ingreso = datos.get("trabajador", {}).get("fecha_ingreso", "")
        sueldo_str = datos.get("montos", {}).get("total_neto", "0")
        try:
            sueldo_num = float(''.join(c for c in str(sueldo_str) if c.isdigit() or c == '.'))
        except:
            sueldo_num = 0
        if fecha_ingreso and fecha_ingreso != "No detectado":
            datos["antiguedad"] = calcular_antiguedad(fecha_ingreso, sueldo_num)

        await aviso.edit_text("📄 Generando reporte PDF...")
        numero_reporte = f"{user_id}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        ruta_pdf = generar_pdf_reporte(datos, numero_reporte)

        await aviso.delete()

        resumen_historial = (
            f"[El usuario envio su recibo. "
            f"Trabajador: {datos['trabajador'].get('nombre', 'No detectado')}, "
            f"Empleador: {datos['trabajador'].get('empleador', 'No detectado')}, "
            f"Periodo: {datos['trabajador'].get('periodo', 'No detectado')}, "
            f"Neto: {datos['montos'].get('total_neto', 'No detectado')}. "
            f"Irregularidades: {', '.join(datos.get('irregularidades', ['Ninguna']))}.]"
        )
        agregar_al_historial(user_id, "user", "Envie mi recibo de sueldo para analisis.")
        agregar_al_historial(user_id, "model", resumen_historial)

        irregularidades = datos.get("irregularidades", [])
        tiene_problemas = irregularidades and irregularidades[0] != "Sin irregularidades detectadas"

        resumen = (
            f"⚖️ *DICTAMEN DE AUDITORIA*\n\n"
            f"👤 *Trabajador:* {datos['trabajador'].get('nombre', 'No detectado')}\n"
            f"🏢 *Empleador:* {datos['trabajador'].get('empleador', 'No detectado')}\n"
            f"📅 *Periodo:* {datos['trabajador'].get('periodo', 'No detectado')}\n"
            f"💰 *Neto cobrado:* {datos['montos'].get('total_neto', 'No detectado')}\n\n"
            f"{'🔴 *SE DETECTARON IRREGULARIDADES*' if tiene_problemas else '✅ *RECIBO SIN IRREGULARIDADES*'}\n\n"
            f"📄 *Reporte PDF adjunto*\n\n"
            f"💬 Podes seguir preguntando sobre este recibo o cualquier duda legal.\n\n"
        )

        await update.message.reply_text(resumen, parse_mode='Markdown')

        with open(ruta_pdf, 'rb') as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=f"Dictamen_Legal_{numero_reporte}.pdf",
                caption="📋 Reporte completo de auditoria laboral ⚖️🍷"
            )
        os.remove(ruta_pdf)

    except Exception as e:
        print(f"Error Vision: {e}")
        await aviso.edit_text(f"❌ No pude procesar el archivo.\n\n🔍 Error: {str(e)[:300]}")


import requests
import time

# Cargar API key de Manus
MANUS_API_KEY = os.getenv("MANUS_API_KEY")

def generar_informe_manus(datos_irregularidades: str) -> str:
    """Envía los datos a Manus y espera el informe completo"""
    headers = {
        "x-manus-api-key": MANUS_API_KEY,
        "Content-Type": "application/json"
    }
    
    prompt = f"""Generá un informe profesional de irregularidades laborales para un contratista de viñas en Mendoza, Argentina.

DATOS DEL CASO:
{datos_irregularidades}

El informe debe incluir:
1. Resumen ejecutivo del caso
2. Irregularidades detectadas con el artículo de ley violado
3. Estimación del daño económico
4. Base legal aplicable (Ley 20.589, 23.154, 27.644)
5. Acciones recomendadas con plazos
6. Organismos donde denunciar (Subsecretaría de Trabajo, AFIP, INV)

Formato: profesional, claro, listo para enviar a un abogado laboralista."""

    # Crear tarea en Manus
    try:
        resp = requests.post(
            "https://api.manus.ai/v2/task.create",
            headers=headers,
            json={"message": {"content": prompt}, "hide_in_task_list": False}
        )
        data = resp.json()
        
        if not data.get("ok"):
            return f"Error al crear tarea en Manus: {data.get('error', {}).get('message', 'Error desconocido')}"
        
        task_id = data["task_id"]
        print(f"✅ Tarea Manus creada: {task_id}")
        
        # Polling hasta que termine
        max_intentos = 30
        for intento in range(max_intentos):
            time.sleep(10)
            
            msgs_resp = requests.get(
                f"https://api.manus.ai/v2/task.listMessages?task_id={task_id}&order=desc&limit=20",
                headers=headers
            )
            msgs_data = msgs_resp.json()
            
            if not msgs_data.get("ok"):
                continue
            
            mensajes = msgs_data.get("data", [])
            
            # Buscar status_update
            for msg in mensajes:
                if msg.get("type") == "status_update":
                    status = msg.get("status_update", {}).get("agent_status", "")
                    print(f"Estado Manus: {status}")
                    
                    if status == "stopped":
                        # Buscar el mensaje del asistente
                        for m in mensajes:
                            if m.get("type") == "assistant_message":
                                contenido = m.get("content", "")
                                if isinstance(contenido, list):
                                    texto = " ".join([c.get("text", "") for c in contenido if c.get("type") == "text"])
                                else:
                                    texto = str(contenido)
                                return texto
                        return "Manus completó la tarea pero no se encontró el informe."
                    
                    elif status == "error":
                        return "Manus encontró un error al generar el informe."
        
        return "Manus tardó demasiado. Intentá de nuevo en unos minutos."
        
    except Exception as e:
        return f"Error de conexión con Manus: {str(e)}"


# ============================================================
# BÚSQUEDA SEMÁNTICA (RAG con ChromaDB)
# ============================================================
import chromadb
from sentence_transformers import SentenceTransformer

_chroma_client = None
_chroma_collection = None
_embedding_model = None

def inicializar_rag():
    global _chroma_client, _chroma_collection, _embedding_model
    try:
        _chroma_client = chromadb.PersistentClient(path="/root/BotContador/vectordb")
        _chroma_collection = _chroma_client.get_collection("documentos_legales")
        _embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        print("✅ RAG inicializado correctamente")
    except Exception as e:
        print(f"⚠️ Error inicializando RAG: {e}")

def buscar_contexto_relevante(pregunta: str, n_resultados: int = 3) -> str:
    """Busca los chunks más relevantes para la pregunta"""
    global _chroma_collection, _embedding_model
    if not _chroma_collection or not _embedding_model:
        return ""
    try:
        embedding = _embedding_model.encode([pregunta]).tolist()
        resultados = _chroma_collection.query(
            query_embeddings=embedding,
            n_results=n_resultados
        )
        chunks = resultados.get("documents", [[]])[0]
        fuentes = [m.get("fuente", "") for m in resultados.get("metadatas", [[]])[0]]
        
        contexto = ""
        for chunk, fuente in zip(chunks, fuentes):
            contexto += f"[{fuente}]\n{chunk}\n\n"
        return contexto[:4000]
    except Exception as e:
        print(f"⚠️ Error en búsqueda RAG: {e}")
        return ""

# Inicializar al arrancar
inicializar_rag()


import time as time_module

def llamar_gemini_con_retry(prompt, max_intentos=3):
    """Llama a Gemini con retry automático en caso de 429"""
    for intento in range(max_intentos):
        try:
            res = model.generate_content(prompt)
            return res.text
        except Exception as e:
            if "429" in str(e) and intento < max_intentos - 1:
                espera = (intento + 1) * 15
                print(f"429 Gemini, esperando {espera} segundos...")
                time_module.sleep(espera)
            else:
                raise e
    return None

# ============================================================
# 10. PROCESAMIENTO DE TEXTO CON MEMORIA
# ============================================================
async def procesar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if es_bloqueado(user_id):
        await update.message.reply_text("🚫 No tenés acceso a este bot.")
        return

    if not es_autorizado(user_id):
        await update.message.reply_text("No tenés acceso. Escribí /start y enviá tu recibo para solicitar acceso.")
        return

    mensaje_usuario = update.message.text
    modo = context.user_data.get('modo', '')
    if modo == 'esperando_cheque':
        texto_msg = update.message.text or ""
        cuit_detectado = "".join(filter(str.isdigit, texto_msg))
        if len(cuit_detectado) == 11:
            context.user_data['cheque_cuit'] = cuit_detectado
            cuit_fmt = f"{cuit_detectado[:2]}-{cuit_detectado[2:10]}-{cuit_detectado[10:]}"
            keyboard = [[
                InlineKeyboardButton("✅ Sí, consultar", callback_data='cheque_confirmar'),
                InlineKeyboardButton("❌ No, corregir", callback_data='cheque_corregir')
            ]]
            await update.message.reply_text(
                f"📋 CUIT ingresado: *{cuit_fmt}*\n\n¿Es correcto?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Si parece una consulta real (varias palabras), salir del modo cheque
            palabras = texto_msg.split()
            letras = sum(ch.isalpha() for ch in texto_msg)
            if len(palabras) >= 4 and letras > 10:
                context.user_data['modo'] = ''
                context.user_data.pop('cheque_cuit', None)
                context.user_data.pop('cheque_banco', None)
                context.user_data.pop('cheque_nro', None)
                await update.message.reply_text(
                    "Salí del modo Verificar Cheque. Volvé a enviar tu consulta y te respondo. 👍"
                )
            else:
                await update.message.reply_text(
                    "⚠️ Eso no parece un CUIT válido (necesito 11 números).\n\n"
                    "Probá de nuevo: escribí el CUIT/CUIL del emisor, "
                    "o enviá una foto del cheque."
                )
        return


    # Modo esperando recibo - recolecta documentos uno por uno


    if modo == 'registro_tareas':
        paso = context.user_data.get('tareas_paso', 0)
        datos = context.user_data.get('tareas_datos', {})
        preguntas = [
            ('nombre_contratista', '¿Cuál es tu nombre completo?'),
            ('dni', '¿Cuál es tu DNI?'),
            ('nombre_empleador', '¿Nombre del empleador?'),
            ('cuit', '¿CUIT del empleador?'),
            ('inv', '¿N° INV de la finca? (ej: E-16305)'),
            ('ubicacion', '¿Ubicacion de la finca?'),
            ('temporada', '¿Temporada? (ej: 2026)'),
        ]
        if paso < len(preguntas):
            clave, _ = preguntas[paso]
            datos[clave] = mensaje_usuario
            context.user_data['tareas_datos'] = datos
            siguiente = paso + 1
            context.user_data['tareas_paso'] = siguiente
            if siguiente < len(preguntas):
                _, prox = preguntas[siguiente]
                msg_anterior = context.user_data.get('renaf_msg_id')
                if msg_anterior:
                    try:
                        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_anterior)
                    except Exception:
                        pass
                msg_prox = await update.message.reply_text(prox)
                context.user_data['renaf_msg_id'] = msg_prox.message_id
            else:
                aviso = await update.message.reply_text("⏳ Generando tu registro de tareas...")
                try:
                    import io as io_mod2
                    pdf_bytes = generar_registro_tareas_pdf(datos)
                    nombre = datos.get('nombre_contratista', 'Contratista').split()[0]
                    await aviso.delete()
                    context.user_data['modo'] = ''
                    await update.message.reply_document(
                        document=io_mod2.BytesIO(pdf_bytes),
                        filename=f"Registro_Tareas_{nombre}.pdf",
                        caption=(
                            "📝 *Registro de Tareas y Labores*\n"
                            f"Temporada {datos.get('temporada', '2026')}\n\n"
                            "✅ Listo para llenar durante la temporada.\n"
                            "📋 4 páginas con todas las obligaciones legales."
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    await aviso.edit_text(f"❌ Error: {str(e)[:100]}")
        return

    if modo == 'registro_ventas':
        paso = context.user_data.get('registro_paso', 0)
        datos = context.user_data.get('registro_datos', {})
        preguntas = [
            ('nombre_contratista', '¿Cuál es tu nombre completo?'),
            ('dni', '¿Cuál es tu DNI?'),
            ('nombre_empleador', '¿Nombre del empleador?'),
            ('cuit', '¿CUIT del empleador?'),
            ('inv', '¿N° INV de la finca? (ej: E-16305)'),
            ('porcentaje', '¿Tu porcentaje de cosecha? (ej: 18)'),
            ('periodo', '¿Temporada? (ej: 2026)'),
        ]
        if paso < len(preguntas):
            clave, _ = preguntas[paso]
            datos[clave] = mensaje_usuario
            context.user_data['registro_datos'] = datos
            siguiente = paso + 1
            context.user_data['registro_paso'] = siguiente
            if siguiente < len(preguntas):
                _, prox = preguntas[siguiente]
                msg_anterior = context.user_data.get('renaf_msg_id')
                if msg_anterior:
                    try:
                        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_anterior)
                    except Exception:
                        pass
                msg_prox = await update.message.reply_text(prox)
                context.user_data['renaf_msg_id'] = msg_prox.message_id
            else:
                aviso = await update.message.reply_text("⏳ Generando tu registro de ventas...")
                try:
                    import io as io_mod2
                    pdf_bytes = generar_registro_ventas_pdf(datos)
                    nombre = datos.get('nombre_contratista', 'Contratista').split()[0]
                    await aviso.delete()
                    context.user_data['modo'] = ''
                    await update.message.reply_document(
                        document=io_mod2.BytesIO(pdf_bytes),
                        filename=f"Registro_Ventas_{nombre}.pdf",
                        caption=(
                            "📊 *Registro de Ventas de Produccion*\n"
                            f"Temporada {datos.get('periodo', '2026')}\n\n"
                            "✅ Listo para llenar con cada venta.\n"
                            "⚠️ Es un documento de uso personal para verificar tus haberes."
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    await aviso.edit_text(f"❌ Error: {str(e)[:100]}")
        return

    if modo == 'cosecha_inv':
        paso = context.user_data.get('cinv_paso', 0)
        datos = context.user_data.get('cinv_datos', {})
        fase = context.user_data.get('cinv_fase', 'fijas')

        preguntas_fijas = [
            ('fecha', 'PREGUNTA 1\n\n¿Fecha del informe? (DD/MM/AAAA)\n📝 Ejemplo: 15/06/2026'),
            ('vinedo', 'PREGUNTA 2\n\n¿Cuál es el N° de Viñedo (INV)?\n📝 Ejemplo: E-16305'),
            ('razon_social', 'PREGUNTA 3\n\n¿Razón social de la finca? (el nombre del establecimiento)'),
            ('cuit', 'PREGUNTA 4\n\n¿CUIT de la finca/empleador?'),
            ('hectareas', 'PREGUNTA 5\n\n¿Cuántas hectáreas cosechaste?\n📝 Ejemplo: 4,18'),
            ('porcentaje', 'PREGUNTA 6\n\n¿Qué porcentaje según contrato? (ej: 18)'),
            ('contratista', 'PREGUNTA 7\n\n¿Nombre y apellido del contratista?'),
            ('dni', 'PREGUNTA 8\n\n¿DNI del contratista? (sin puntos)'),
            ('quintales_totales', 'PREGUNTA 9\n\n¿Cuántos quintales cosechaste en total?\n💡 Un quintal son 100 kilos'),
        ]

        # FASE 1: preguntas fijas
        if fase == 'fijas':
            if paso < len(preguntas_fijas):
                clave, _ = preguntas_fijas[paso]
                datos[clave] = mensaje_usuario
                context.user_data['cinv_datos'] = datos
                siguiente = paso + 1
                context.user_data['cinv_paso'] = siguiente
                if siguiente < len(preguntas_fijas):
                    _, prox = preguntas_fijas[siguiente]
                    await update.message.reply_text(prox)
                else:
                    context.user_data['cinv_fase'] = 'cant_variedades'
                    await update.message.reply_text("PREGUNTA 10\n\n¿Cuántas variedades de uva cosechaste? (poné un número: 1, 2, 3...)")
            return

        # FASE 2: cantidad de variedades
        if fase == 'cant_variedades':
            try:
                n = int(mensaje_usuario.strip())
                if n < 1 or n > 10:
                    await update.message.reply_text("Poné un número entre 1 y 10.")
                    return
            except:
                await update.message.reply_text("Poné solo un número. Ejemplo: 2")
                return
            context.user_data['cinv_n_var'] = n
            context.user_data['cinv_var_actual'] = 0
            datos['variedades'] = []
            context.user_data['cinv_datos'] = datos
            context.user_data['cinv_fase'] = 'variedades'
            context.user_data['cinv_var_sub'] = 'nombre'
            await update.message.reply_text("VARIEDAD 1\n\n¿Cuál es el nombre de la variedad? (ej: Malbec)")
            return

        # FASE 3: cargar cada variedad (nombre + quintales)
        if fase == 'variedades':
            sub = context.user_data.get('cinv_var_sub', 'nombre')
            idx = context.user_data.get('cinv_var_actual', 0)
            n = context.user_data.get('cinv_n_var', 1)
            if sub == 'nombre':
                context.user_data['cinv_var_tmp'] = {'variedad': mensaje_usuario}
                context.user_data['cinv_var_sub'] = 'quintales'
                await update.message.reply_text(f"VARIEDAD {idx+1}\n\n¿Cuántos quintales de {mensaje_usuario}?")
                return
            else:
                tmp = context.user_data.get('cinv_var_tmp', {})
                tmp['quintales'] = mensaje_usuario
                datos['variedades'].append(tmp)
                context.user_data['cinv_datos'] = datos
                idx += 1
                context.user_data['cinv_var_actual'] = idx
                if idx < n:
                    context.user_data['cinv_var_sub'] = 'nombre'
                    await update.message.reply_text(f"VARIEDAD {idx+1}\n\n¿Cuál es el nombre de la variedad?")
                else:
                    context.user_data['cinv_fase'] = 'cant_bodegas'
                    await update.message.reply_text("¿A cuántas bodegas llevaste la uva? (poné un número)")
                return

        # FASE 4: cantidad de bodegas
        if fase == 'cant_bodegas':
            try:
                n = int(mensaje_usuario.strip())
                if n < 1 or n > 10:
                    await update.message.reply_text("Poné un número entre 1 y 10.")
                    return
            except:
                await update.message.reply_text("Poné solo un número. Ejemplo: 1")
                return
            context.user_data['cinv_n_bod'] = n
            context.user_data['cinv_bod_actual'] = 0
            datos['bodegas'] = []
            context.user_data['cinv_datos'] = datos
            context.user_data['cinv_fase'] = 'bodegas'
            context.user_data['cinv_bod_sub'] = 'nombre'
            await update.message.reply_text("BODEGA 1\n\n¿Razón social y N° de INV de la bodega?\n📝 Ejemplo: Bodega Ayub - INV B-1234")
            return

        # FASE 5: cargar cada bodega
        if fase == 'bodegas':
            sub = context.user_data.get('cinv_bod_sub', 'nombre')
            idx = context.user_data.get('cinv_bod_actual', 0)
            n = context.user_data.get('cinv_n_bod', 1)
            if sub == 'nombre':
                context.user_data['cinv_bod_tmp'] = {'bodega': mensaje_usuario}
                context.user_data['cinv_bod_sub'] = 'quintales'
                await update.message.reply_text(f"BODEGA {idx+1}\n\n¿Cuántos quintales llevaste a esa bodega?")
                return
            else:
                tmp = context.user_data.get('cinv_bod_tmp', {})
                tmp['quintales'] = mensaje_usuario
                datos['bodegas'].append(tmp)
                context.user_data['cinv_datos'] = datos
                idx += 1
                context.user_data['cinv_bod_actual'] = idx
                if idx < n:
                    context.user_data['cinv_bod_sub'] = 'nombre'
                    await update.message.reply_text(f"BODEGA {idx+1}\n\n¿Razón social y N° de INV de la bodega?")
                else:
                    context.user_data['cinv_fase'] = 'contacto'
                    context.user_data['cinv_cont_paso'] = 0
                    await update.message.reply_text("Ya casi terminamos.\n\nCONTACTO 1/3\n\n¿Tu teléfono?")
                return

        # FASE 6: contacto (telefono, domicilio, mail) y generar PDF
        if fase == 'contacto':
            cont_preg = [
                ('telefono', 'CONTACTO 2/3\n\n¿Tu domicilio?'),
                ('domicilio', 'CONTACTO 3/3\n\n¿Tu mail? (si no tenés, escribí No tengo)'),
                ('mail', None),
            ]
            cp = context.user_data.get('cinv_cont_paso', 0)
            clave = cont_preg[cp][0]
            datos[clave] = mensaje_usuario
            context.user_data['cinv_datos'] = datos
            if cp < 2:
                await update.message.reply_text(cont_preg[cp][1])
                context.user_data['cinv_cont_paso'] = cp + 1
            else:
                aviso = await update.message.reply_text("⏳ Generando tu Informe de Finalización de Cosecha...")
                try:
                    import io as _io
                    from cosecha_inv_pdf import generar_cosecha_inv_pdf
                    pdf_bytes = generar_cosecha_inv_pdf(datos)
                    nombre = datos.get('contratista', 'Contratista').split()[0]
                    await aviso.delete()
                    for k in list(context.user_data.keys()):
                        if k.startswith('cinv_'):
                            del context.user_data[k]
                    context.user_data['modo'] = ''
                    await update.message.reply_document(
                        document=_io.BytesIO(pdf_bytes),
                        filename=f"Informe_Cosecha_INV_{nombre}.pdf",
                        caption=(
                            "📋 *Informe de Finalización de Cosecha (INV)*\n\n"
                            "✅ Presentalo ante el sindicato para certificar (firma y sello).\n"
                            "⚠️ Es uno por cada viñedo. Si trabajaste en varios, generá uno por cada uno.\n"
                            "📅 Fecha límite: 30 de junio de 2026."
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    await aviso.edit_text(f"❌ Error generando el informe: {str(e)[:100]}")
            return
        return

    if modo == 'formulario_renaf':
        paso = context.user_data.get('renaf_paso', 0)
        datos = context.user_data.get('renaf_datos', {})
        preguntas = [
            ('nombre', 'PREGUNTA 1/30\n\n¿Cuál es tu nombre? (solo nombre)'),
            ('apellido', 'PREGUNTA 2/30\n\n¿Cuál es tu apellido?'),
            ('fecha_nac', 'PREGUNTA 3/30\n\n¿Cuándo naciste? Poné día, mes y año.\n📝 Ejemplo: 25/03/1975'),
            ('dni', 'PREGUNTA 4/30\n\n¿Cuál es tu número de DNI? Poné solo los números, sin puntos.\n📝 Ejemplo: 20123456'),
            ('sexo', 'PREGUNTA 5/30\n\n¿Qué sexo figura en tu DNI?\n📝 Escribí M si dice Masculino, o F si dice Femenino'),
            ('genero', 'PREGUNTA 6/30\n\n¿Cómo te sentís identificado? (masculino / femenino / otro)\n💡 En general es lo mismo que figura en tu DNI'),
            ('email', 'PREGUNTA 7/30\n\n¿Tenés correo electrónico (email)? Escribilo.\n📝 Ejemplo: juan@gmail.com\n💡 Si no tenés, escribí No tengo'),
            ('telefono', 'PREGUNTA 8/30\n\n¿Cuál es tu número de celular?\n📝 Ejemplo: 2615551234'),
            ('educacion', 'PREGUNTA 9/30\n\n¿Hasta qué grado o año estudiaste?\n📝 Ejemplos: Primario completo / Secundario incompleto / Sin escolaridad'),
            ('organizacion', 'PREGUNTA 10/30\n\n¿Sos parte de algún grupo, sindicato o asociación de trabajadores?\n💡 El sindicato de contratistas (SUTCVyF) cuenta. Si no estás en ninguno, escribí No'),
            ('departamento', 'PREGUNTA 11/30\n\n¿En qué departamento queda la finca donde trabajás?\n📝 Ejemplo: Gral. San Martín'),
            ('localidad', 'PREGUNTA 12/30\n\n¿En qué pueblo o localidad queda la finca?\n📝 Ejemplo: Ingeniero Giagnoni'),
            ('calle', 'PREGUNTA 13/30\n\n¿En qué calle o ruta está la finca?\n📝 Ejemplo: La Joya s/n (poné s/n si no tiene número)'),
            ('cp', 'PREGUNTA 14/30\n\n¿Cuál es el código postal de la zona?\n📝 Ejemplo: 5582\n💡 Si no lo sabés, escribí No sé'),
            ('latitud', 'PREGUNTA 15/30\n\n¿Tenés la ubicación de la finca en el mapa? Necesito la LATITUD.\n💡 Es un número que da Google Maps cuando marcás la finca. Ejemplo: -33.000000\n👉 Si no la tenés, escribí No la tengo'),
            ('longitud', 'PREGUNTA 16/30\n\n¿Y la LONGITUD?\n💡 Es el otro número de Google Maps. Ejemplo: -68.500000\n👉 Si no la tenés, escribí No la tengo'),
            ('vivienda_condicion', 'PREGUNTA 17/30\n\n¿La casa donde vivís es tuya, alquilada o prestada?\n📝 Opciones: Propietario (es tuya) / Inquilino (alquilás) / Prestada / Ocupante con permiso'),
            ('distancia', 'PREGUNTA 18/30\n\n¿Qué tan lejos está tu casa de la finca, en kilómetros?\n💡 Si vivís adentro de la finca, poné 0'),
            ('superficie_ha', 'PREGUNTA 19/30\n\n¿Cuántas hectáreas de viña trabajás?\n📝 Ejemplo: 4,18\n💡 Una hectárea son 10.000 metros cuadrados'),
            ('agroquimicos', 'PREGUNTA 20/30\n\n¿Usás venenos o productos químicos en la viña? (Si / No)\n💡 Son los herbicidas, fungicidas, insecticidas para matar yuyos, hongos o bichos'),
            ('bioinsumos', 'PREGUNTA 21/30\n\n¿Usás productos naturales o caseros para la viña? (Si / No)\n💡 Son abonos o preparados naturales, no comprados como veneno'),
            ('labranza', 'PREGUNTA 22/30\n\n¿Cómo trabajás la tierra? (Convencional / Mínima / Siembra directa)\n💡 Si arás y removés la tierra con el tractor como siempre, es Convencional'),
            ('anio_produce', 'PREGUNTA 23/30\n\n¿Desde qué año trabajás en esta finca?\n📝 Ejemplo: 2021'),
            ('tenencia', 'PREGUNTA 24/30\n\n¿Cómo trabajás la tierra? (Mediero / Arrendatario / Propietario / Ocupante)\n💡 Mediero = trabajás la finca de otro y cobrás un porcentaje (el 18%). La mayoría de los contratistas son Mediero'),
            ('contrata', 'PREGUNTA 25/30\n\n¿Vos contratás y le pagás a otros trabajadores? (Si / No)\n💡 Hablamos de si VOS sos patrón de alguien. La mayoría de contratistas pone No'),
            ('renspa', 'PREGUNTA 26/30\n\n¿Tenés RENSPA? (Si / No / No sé)\n💡 Es un registro de SENASA para campos con animales. La mayoría de viñateros NO tiene, podés poner No'),
            ('cuenta_banco', 'PREGUNTA 27/30\n\n¿Tenés una cuenta de banco o billetera virtual a tu nombre? (Si / No)\n💡 Cuenta del banco, caja de ahorro, Mercado Pago, etc.'),
            ('destino', 'PREGUNTA 28/30\n\n¿Qué hacés con la uva que producís? (Venta / Autoconsumo / Ambos)\n💡 Si la vendés a la bodega, poné Venta'),
            ('perdidas', 'PREGUNTA 29/30\n\n¿Perdiste cosecha por el clima en los últimos 2 años? (Si / No)\n💡 Por granizo, heladas, sequía, tormentas, plagas o enfermedades'),
            ('perspectiva', 'PREGUNTA 30/30\n\n¿Qué pensás hacer el año que viene? (Continuar igual / Ampliar / Abandonar)\n💡 Ampliar = agrandar la producción'),
        ]
        if paso < len(preguntas):
            clave, _ = preguntas[paso]
            datos[clave] = mensaje_usuario
            context.user_data['renaf_datos'] = datos
            siguiente = paso + 1
            context.user_data['renaf_paso'] = siguiente
            if siguiente < len(preguntas):
                _, prox = preguntas[siguiente]
                await update.message.reply_text(prox)
            else:
                aviso = await update.message.reply_text("⏳ Generando tu guía del formulario ReNAF...")
                try:
                    import io as _io
                    from renaf_pdf import generar_renaf_pdf
                    pdf_bytes = generar_renaf_pdf(datos)
                    nombre = datos.get('nombre', 'Contratista').split()[0]
                    await aviso.delete()
                    context.user_data['modo'] = ''
                    context.user_data['renaf_paso'] = 0
                    context.user_data['renaf_datos'] = {}
                    await update.message.reply_document(
                        document=_io.BytesIO(pdf_bytes),
                        filename=f"Guia_ReNAF_{nombre}.pdf",
                        caption=(
                            "📋 *Guía del Formulario ReNAF*\n\n"
                            "✅ Copiá estos datos al formulario oficial en papel y firmalo.\n"
                            "📎 Adjuntá DNI (frente y dorso) e imagen satelital del predio.\n"
                            "🌐 Más info: renaf.magyp.gob.ar"
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    await aviso.edit_text(f"❌ Error generando la guía: {str(e)[:100]}")
        return
    if modo == 'formulario_cosecha':
        paso = context.user_data.get('cosecha_paso', 0)
        datos = context.user_data.get('cosecha_datos', {})
        preguntas = [
            ('nombre_contratista', '¿Cuál es tu nombre completo?'),
            ('dni', '¿Cuál es tu DNI?'),
            ('nombre_empleador', '¿Cuál es el nombre del empleador/patrón?'),
            ('cuit', '¿Cuál es el CUIT del empleador?'),
            ('ubicacion', '¿Dónde está la finca? (calle, localidad, departamento)'),
            ('inv', '¿Cuál es el N° INV de la finca? (ej: E-16305)'),
            ('hectareas', '¿Cuántas hectáreas trabajás?'),
            ('porcentaje', '¿Qué porcentaje de cosecha te corresponde? (ej: 18)'),
            ('periodo', '¿Cuál es el período? (ej: 2026)'),
        ]

        if paso < len(preguntas):
            clave, _ = preguntas[paso]
            datos[clave] = mensaje_usuario
            context.user_data['cosecha_datos'] = datos
            siguiente = paso + 1
            context.user_data['cosecha_paso'] = siguiente

            if siguiente < len(preguntas):
                _, prox_pregunta = preguntas[siguiente]
                await update.message.reply_text(prox_pregunta)
            else:
                aviso = await update.message.reply_text("⏳ Generando tu formulario de cosecha...")
                try:
                    import io as io_mod2
                    pdf_bytes = generar_formulario_cosecha_pdf(datos)
                    nombre = datos.get('nombre_contratista', 'Contratista').split()[0]
                    await aviso.delete()
                    context.user_data['modo'] = ''
                    await update.message.reply_document(
                        document=io_mod2.BytesIO(pdf_bytes),
                        filename=f"Formulario_Cosecha_{nombre}.pdf",
                        caption=(
                            "📋 *Formulario de Control de Cosecha*\n"
                            f"Temporada {datos.get('periodo', '2026')}\n\n"
                            "✅ Listo para entregar al empleador.\n"
                            "⚠️ Recordá: este formulario es solo para recopilación de datos. "
                            "No firmés nada sin revisar con un asesor."
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    await aviso.edit_text(f"❌ Error generando formulario: {str(e)[:100]}")
        return

    if modo == 'esperando_recibo':
        paso = context.user_data.get('recibo_paso', 0)
        datos = context.user_data.get('recibo_datos', {})
        textos = context.user_data.get('recibo_textos', {})
        
        if mensaje_usuario.lower() == '/cancelar':
            context.user_data['modo'] = ''
            await update.message.reply_text("❌ Análisis cancelado.")
            return
        
        # Si el paso actual pide un documento (no la pregunta de sindicato)
        pasos_docs = {
            0: "contrato",
            1: "declaracion", 
            2: "recibo",
            3: "riego"
        }
        
        if paso < 4:
            # Guardar respuesta de texto si escribió NO TENGO
            if mensaje_usuario.upper() in ["NO TENGO", "NO"]:
                tipo_doc = pasos_docs[paso]
                textos[tipo_doc] = "No proporcionado por el contratista"
                context.user_data['recibo_textos'] = textos
                siguiente = paso + 1
                context.user_data['recibo_paso'] = siguiente
                if siguiente < len(PREGUNTAS_RECIBO):
                    _, pregunta = PREGUNTAS_RECIBO[siguiente]
                    await update.message.reply_text(pregunta, parse_mode="Markdown")
                return
            else:
                # Esperar foto - el procesamiento lo hace procesar_archivo
                await update.message.reply_text(
                    "📸 Por favor enviame la foto del documento, no texto.",
                    parse_mode="Markdown"
                )
                return
        else:
            # Último paso: sindicato
            datos['sindicalizado'] = mensaje_usuario
            context.user_data['recibo_datos'] = datos
            context.user_data['modo'] = 'generando_informe'
            
            aviso = await update.message.reply_text(
                "⏳ Analizando todos tus documentos y generando el informe completo...\n"
                "Esto puede tardar 2-3 minutos. Por favor esperá."
            )
            
            try:
                resultado = await generar_informe_integral(textos, mensaje_usuario)
                await aviso.delete()
                context.user_data['modo'] = ''
                cache_respuestas[user_id] = resultado
                
                # Generar PDF del informe
                try:
                    import io as io_mod2
                    pdf_bytes = convertir_informe_a_pdf(resultado)
                    await update.message.reply_document(
                        document=io_mod2.BytesIO(pdf_bytes),
                        filename=f"Informe_Auditoria_Laboral.pdf",
                        caption=(
                            "📋 *Informe Integral de Auditoría Laboral*\n"
                            "Leyes 20.589 · 23.154 · 27.644\n\n"
                            "✅ Listo para enviar a un abogado."
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as pdf_err:
                    print(f"Error PDF: {pdf_err}")
                    keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]
                    if len(resultado) <= 4000:
                        await update.message.reply_text(resultado, reply_markup=InlineKeyboardMarkup(keyboard))
                    else:
                        partes = [resultado[i:i+3800] for i in range(0, len(resultado), 3800)]
                        for parte in partes[:-1]:
                            await update.message.reply_text(parte)
                        await update.message.reply_text(partes[-1], reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                await aviso.edit_text(f"❌ Error al generar el informe: {str(e)[:200]}")
        return


    # Modo formulario informe
    if modo == 'formulario_informe':
        await procesar_formulario_informe(update, context)
        return

    # Modo calculadora de antigüedad manual
    if modo == 'pedir_fecha_antiguedad':
        context.user_data['modo'] = ''
        sueldo_guardado = context.user_data.get('sueldo_antiguedad', 0)
        resultado = calcular_antiguedad(mensaje_usuario, sueldo_guardado)
        if resultado.get("error"):
            await update.message.reply_text(
                "❌ No entendí la fecha. Escribila así: *01/03/2018*",
                parse_mode="Markdown"
            )
            context.user_data['modo'] = 'pedir_fecha_antiguedad'
            return
        antig = resultado
        tiene_sueldo = antig.get("tiene_sueldo", False)
        texto_calc = (
            f"📅 *CALCULADORA DE ANTIGÜEDAD*\n\n"
            f"Fecha de ingreso: {antig['fecha_ingreso']}\n"
            f"Antigüedad: *{antig['antiguedad_texto']}*\n\n"
            f"💰 *Lo que perdés si aceptás el monotributo:*\n"
        )
        if tiene_sueldo:
            texto_calc += (
                f"• Indemnización: ${antig['indemnizacion']:,.0f}\n"
                f"• SAC proporcional: ${antig['sac_proporcional']:,.0f}\n"
                f"• Preaviso: ${antig['preaviso']:,.0f}\n"
            )
        texto_calc += (
            f"• Seguro Desempleo RENATRE: ${antig['renatre']:,.0f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 *TOTAL QUE LE REGALÁS AL PATRÓN: ${antig['total_perdida']:,.0f}*\n\n"
            f"⚠️ Usted tiene derechos adquiridos. Pasar a monotributo implica regalarle "
            f"al patrón todos sus años de antigüedad acumulados. "
            f"No firme su propia renuncia disfrazada de contrato independiente."
        )
        cache_respuestas[user_id] = texto_calc
        keyboard = [[InlineKeyboardButton("🔊 Escuchar", callback_data=f"audio_{user_id}")]]
        await update.message.reply_text(texto_calc, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))
        return

    try:
        contexto = construir_contexto(user_id)

        # Elegir sistema prompt y emoji según el modo
        if modo == 'vid_texto':
            system = SYSTEM_PROMPT_VID
            emoji = "🌿"
            boton_volver = [[InlineKeyboardButton("🌿 Volver al Experto en Vid", callback_data="menu_vid")]]
        else:
            system = SYSTEM_PROMPT
            emoji = "⚖️"
            boton_volver = []

        # Buscar contexto relevante con RAG
        contexto_rag = buscar_contexto_relevante(mensaje_usuario, n_resultados=25)
        
        import datetime as _dt
        fecha_actual = _dt.datetime.now().strftime("%d/%m/%Y")
        instruccion_fecha = (
            "INSTRUCCION CRITICA SOBRE ESCALAS SALARIALES: "
            "Los DOCUMENTOS RELEVANTES de abajo contienen escalas salariales YA PUBLICADAS Y OFICIALES por la Comision Paritaria, "
            "incluyendo meses como MAYO, JUNIO y JULIO 2026. Estas escalas EXISTEN y estan VIGENTES. "
            "Si el usuario pregunta por la escala de un mes (ej: julio 2026) y ese mes aparece en los documentos, "
            "DEBES dar las cifras exactas que figuran ahi (Remunerativo, No Remunerativo y TOTAL por hectarea). "
            "Esta TERMINANTEMENTE PROHIBIDO responder que la escala es 'futura', que 'aun no fue definida' o que 'no tenes acceso' "
            "cuando los montos estan presentes en los documentos. Lee los documentos y extrae los numeros del mes solicitado. "
        )
        prompt_completo = (
            f"{system}\n\n"
            f"{instruccion_fecha}\n\n"
            f"DOCUMENTOS RELEVANTES PARA ESTA CONSULTA:\n{contexto_rag}\n\n"
            f"{contexto}"
            f"Usuario: {mensaje_usuario}\n"
            f"Asistente:"
        )

        res = model.generate_content(prompt_completo)
        respuesta = res.text
        print("✅ Respondió Gemini")

        agregar_al_historial(user_id, "user", mensaje_usuario)
        agregar_al_historial(user_id, "model", respuesta)
        cache_respuestas[user_id] = respuesta

        if len(respuesta) > 4500:
            keyboard = [
                [InlineKeyboardButton("🔊 Escuchar parte 1", callback_data=f"audio_{user_id}_1")],
                [InlineKeyboardButton("🔊 Escuchar parte 2", callback_data=f"audio_{user_id}_2")]
            ]
        else:
            keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]

        if boton_volver:
            keyboard += boton_volver

        texto_completo = f"{emoji} {respuesta}"
        if len(texto_completo) <= 4000:
            await update.message.reply_text(
                texto_completo,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            partes = [texto_completo[i:i+4000] for i in range(0, len(texto_completo), 4000)]
            for parte in partes[:-1]:
                await update.message.reply_text(parte)
            await update.message.reply_text(partes[-1], reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        print(f"Error texto: {e}")
        await update.message.reply_text("❌ Error al consultar a la IA. Intentá de nuevo.")

# ============================================================
# 11. COMANDOS EXTRA
# ============================================================
async def nueva_consulta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not es_autorizado(user_id):
        await update.message.reply_text("No tenes acceso. Escribi /start para solicitar acceso.")
        return
    limpiar_historial(user_id)
    await update.message.reply_text("🗑️ Conversacion reiniciada. En que te puedo ayudar?")

async def terminos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TERMINOS_USO, parse_mode='Markdown')

async def usuarios_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando solo para el admin: ver lista de usuarios con opciones de gestión"""
    if update.message.from_user.id != ADMIN_ID:
        return
    datos = cargar_usuarios()
    autorizados = [u for u in datos.get("autorizados", []) if u != ADMIN_ID]
    pendientes = datos.get("pendientes", {})
    bloqueados = datos.get("bloqueados", [])

    texto = (
        f"👥 *Panel de Administración*\n\n"
        f"✅ Autorizados: {len(autorizados)}\n"
        f"⏳ Pendientes: {len(pendientes)}\n"
        f"🚫 Bloqueados: {len(bloqueados)}\n"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")

    # Mostrar autorizados con opciones
    if autorizados:
        await update.message.reply_text("*✅ Usuarios autorizados:*", parse_mode="Markdown")
        for uid in autorizados:
            keyboard = [[
                InlineKeyboardButton("⚠️ Revocar", callback_data=f"revoke_{uid}"),
                InlineKeyboardButton("🚫 Bloquear", callback_data=f"block_{uid}")
            ]]
            await update.message.reply_text(
                f"🆔 `{uid}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

    # Mostrar bloqueados con opción de desbloquear
    if bloqueados:
        await update.message.reply_text("*🚫 Usuarios bloqueados:*", parse_mode="Markdown")
        for uid in bloqueados:
            keyboard = [[InlineKeyboardButton("✅ Desbloquear", callback_data=f"unblock_{uid}")]]
            await update.message.reply_text(
                f"🆔 `{uid}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

    # Mostrar pendientes
    if pendientes:
        await update.message.reply_text("*⏳ Solicitudes pendientes:*", parse_mode="Markdown")
        for uid, info in pendientes.items():
            texto_p = f"👤 {info['nombre']} (@{info['username']})"
            keyboard = [[
                InlineKeyboardButton("✅ Autorizar", callback_data=f"auth_{uid}"),
                InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{uid}"),
                InlineKeyboardButton("🚫 Bloquear", callback_data=f"block_{uid}")
            ]]
            await update.message.reply_text(
                texto_p,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )


async def comando_informe_viejo_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if not es_autorizado(user_id):
        await update.message.reply_text("No tenés acceso.")
        return
    
    historial = obtener_historial(user_id)
    if not historial:
        await update.message.reply_text(
            "⚠️ No hay conversación para generar el informe.\n"
            "Primero contame tu situación y después usá /informe."
        )
        return
    
    nombre = update.message.from_user.first_name or "Contratista"
    aviso = await update.message.reply_text("📋 Generando informe PDF... ⏳")
    
    try:
        pdf_bytes = await generar_informe_pdf(historial, nombre)
        await aviso.delete()
        await update.message.reply_document(
            document=io.BytesIO(pdf_bytes),
            filename=f"Informe_Irregularidades_{nombre}.pdf",
            caption="📋 *Informe de Irregularidades Laborales*\nListo para enviar a un abogado.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await aviso.edit_text(f"❌ Error al generar el informe: {str(e)[:200]}")


async def generar_informe_pdf(historial: list, nombre_usuario: str) -> bytes:
    """Genera un PDF profesional de irregularidades usando Gemini y ReportLab"""
    
    # Construir resumen del historial
    resumen = "\n".join([
        f"{m['role'].upper()}: {m['texto'][:800]}"
        for m in historial[-15:]
    ])
    
    # Pedir a Gemini que estructure el informe
    prompt_informe = f"""Analizá esta conversación con un contratista de viñas y generá un informe estructurado de irregularidades laborales.

CONVERSACIÓN:
{resumen}

Generá el informe en este formato EXACTO (usá estos títulos exactos):

DATOS DEL CASO:
[nombre del contratista si se mencionó, fecha, provincia]

IRREGULARIDADES DETECTADAS:
[lista cada irregularidad con el artículo violado]

DAÑO ECONÓMICO ESTIMADO:
[calcular si hay datos suficientes]

BASE LEGAL APLICABLE:
[leyes y artículos específicos]

ACCIONES RECOMENDADAS:
[pasos concretos con plazos]

ORGANISMOS DONDE DENUNCIAR:
[lista con direcciones si las conocés]

NOTA IMPORTANTE:
Este informe es orientativo. Consultar con un abogado laboralista matriculado."""

    try:
        res = model.generate_content(prompt_informe)
        contenido = res.text
    except Exception as e:
        contenido = f"Error al generar contenido: {str(e)}"
    
    # Generar PDF con ReportLab
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    styles = getSampleStyleSheet()
    
    estilo_titulo = ParagraphStyle(
        "Titulo",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=10,
        alignment=TA_CENTER
    )
    
    estilo_subtitulo = ParagraphStyle(
        "Subtitulo",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#c0392b"),
        spaceAfter=6,
        spaceBefore=12
    )
    
    estilo_normal = ParagraphStyle(
        "Normal",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=4,
        leading=14
    )
    
    estilo_footer = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER
    )
    
    from datetime import datetime
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    elementos = []
    
    # Encabezado
    elementos.append(Paragraph("⚖️ INFORME DE IRREGULARIDADES LABORALES", estilo_titulo))
    elementos.append(Paragraph("Estatuto del Contratista de Viñas y Frutales", estilo_titulo))
    elementos.append(Paragraph(f"Leyes 20.589 · 23.154 · 27.644", estilo_subtitulo))
    elementos.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#c0392b")))
    elementos.append(Spacer(1, 0.3*cm))
    elementos.append(Paragraph(f"Generado el: {fecha} | Usuario: {nombre_usuario}", estilo_footer))
    elementos.append(Spacer(1, 0.5*cm))
    
    # Contenido del informe
    secciones = [
        "DATOS DEL CASO:",
        "IRREGULARIDADES DETECTADAS:",
        "DAÑO ECONÓMICO ESTIMADO:",
        "BASE LEGAL APLICABLE:",
        "ACCIONES RECOMENDADAS:",
        "ORGANISMOS DONDE DENUNCIAR:",
        "NOTA IMPORTANTE:"
    ]
    
    lineas = contenido.split("\n")
    seccion_actual = None
    
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            elementos.append(Spacer(1, 0.2*cm))
            continue
        
        es_seccion = False
        for seccion in secciones:
            if seccion in linea.upper():
                elementos.append(Spacer(1, 0.3*cm))
                elementos.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
                elementos.append(Paragraph(linea, estilo_subtitulo))
                seccion_actual = seccion
                es_seccion = True
                break
        
        if not es_seccion:
            try:
                elementos.append(Paragraph(linea, estilo_normal))
            except:
                elementos.append(Paragraph(linea.encode("ascii", "ignore").decode(), estilo_normal))
    
    # Footer
    elementos.append(Spacer(1, 1*cm))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")))
    elementos.append(Spacer(1, 0.3*cm))
    elementos.append(Paragraph(
        "Bot Legal Viñas · Basado en Leyes 20.589, 23.154 y 27.644 · "
        "Este informe es orientativo y no reemplaza asesoramiento profesional matriculado.",
        estilo_footer
    ))
    
    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()


# ============================================================
# FORMULARIO DE DATOS PARA INFORME PDF
# ============================================================

PREGUNTAS_RECIBO = [
    ("listo_contrato", "📄 Vamos a analizar tus documentos uno por uno para hacer un informe completo.\n\nPrimero enviame una *foto del contrato (Formulario 001/12)*\nSi no lo tenés escribí NO TENGO."),
    ("listo_declaracion", "📋 Ahora enviame una *foto de la Declaración Jurada (Formulario 002/12)*\nSi no la tenés escribí NO TENGO."),
    ("listo_recibo", "💰 Ahora enviame una *foto del recibo de sueldo más reciente*."),
    ("listo_riego", "💧 Ahora enviame una *foto de la boleta de riego de Irrigación*\nSi no la tenés escribí NO TENGO."),
    ("sindicalizado", "👥 Por último: ¿Estás afiliado al sindicato? (SÍ o NO)")
]

PREGUNTAS_INFORME = [
    ("nombre", "👤 ¿Cuál es tu nombre completo?"),
    ("empleador", "🏢 ¿Cuál es el nombre del empleador o razón social de la finca?"),
    ("direccion", "📍 ¿Cuál es la dirección de la finca?"),
    ("hectareas", "🌿 ¿Cuántas hectáreas trabajás?"),
    ("fecha_inicio", "📅 ¿Desde qué fecha trabajás ahí? (ej: 01/03/2020)"),
    ("irregularidades_extra", "⚠️ ¿Querés agregar algún dato extra que no hayas mencionado antes? (escribí NO si no tenés nada más)")
]

async def iniciar_formulario_informe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if not es_autorizado(user_id):
        await update.message.reply_text("No tenés acceso.")
        return
    
    historial = obtener_historial(user_id)
    if not historial:
        await update.message.reply_text(
            "⚠️ No hay conversación para generar el informe.\n"
            "Primero contame tu situación y después usá /informe."
        )
        return
    
    # Iniciar el formulario
    context.user_data["formulario_informe"] = {}
    context.user_data["formulario_paso"] = 0
    context.user_data["modo"] = "formulario_informe"
    
    await update.message.reply_text(
        "📋 *Vamos a completar el informe de irregularidades.*\n"
        "Te voy a hacer algunas preguntas para personalizar el documento.\n\n"
        "Podés escribir /cancelar en cualquier momento para salir.",
        parse_mode="Markdown"
    )
    
    # Primera pregunta
    _, pregunta = PREGUNTAS_INFORME[0]
    await update.message.reply_text(pregunta)

async def procesar_formulario_informe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    respuesta = update.message.text.strip()
    paso = context.user_data.get("formulario_paso", 0)
    datos = context.user_data.get("formulario_informe", {})
    
    # Cancelar
    if respuesta.lower() == "/cancelar":
        context.user_data["modo"] = ""
        context.user_data["formulario_informe"] = {}
        await update.message.reply_text("❌ Informe cancelado.")
        return
    
    # Guardar respuesta del paso actual
    clave, _ = PREGUNTAS_INFORME[paso]
    datos[clave] = respuesta
    context.user_data["formulario_informe"] = datos
    
    # Siguiente paso
    siguiente_paso = paso + 1
    
    if siguiente_paso < len(PREGUNTAS_INFORME):
        context.user_data["formulario_paso"] = siguiente_paso
        _, siguiente_pregunta = PREGUNTAS_INFORME[siguiente_paso]
        await update.message.reply_text(siguiente_pregunta)
    else:
        # Formulario completo - generar PDF
        context.user_data["modo"] = ""
        nombre = datos.get("nombre", "Contratista")
        
        aviso = await update.message.reply_text("📋 Generando informe PDF personalizado... ⏳")
        
        try:
            historial = obtener_historial(user_id)
            pdf_bytes = await generar_informe_con_manus(historial, datos)
            await aviso.delete()
            
            import io as io_mod
            await update.message.reply_document(
                document=io_mod.BytesIO(pdf_bytes),
                filename=f"Informe_Irregularidades_{nombre.replace(' ', '_')}.pdf",
                caption=(
                    f"📋 *Informe de Irregularidades Laborales*\n"
                    f"👤 {nombre}\n"
                    f"📅 Generado el {__import__('datetime').datetime.now().strftime('%d/%m/%Y')}\n\n"
                    f"✅ Listo para enviar a un abogado."
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            await aviso.edit_text(f"❌ Error al generar el informe: {str(e)[:200]}")


async def generar_informe_pdf_completo(historial: list, datos: dict) -> bytes:
    """Genera PDF con datos del formulario y análisis de Gemini"""
    
    resumen_historial = "\n".join([
        f"{m['role'].upper()}: {m['texto'][:600]}"
        for m in historial[-15:]
    ])
    
    nombre = datos.get("nombre", "No especificado")
    empleador = datos.get("empleador", "No especificado")
    direccion = datos.get("direccion", "No especificada")
    hectareas = datos.get("hectareas", "No especificadas")
    fecha_inicio = datos.get("fecha_inicio", "No especificada")
    extra = datos.get("irregularidades_extra", "")
    
    prompt = f"""Analizá esta conversación y generá un informe estructurado de irregularidades laborales.

REGLAS ESTRICTAS:
- Solo citá leyes que existen: Ley 20.589, Ley 23.154, Ley 27.644, Ley 27.643, Ley 25.191
- NUNCA inventes artículos ni leyes que no estén en esa lista
- Si no hay suficiente información para un punto, escribí "Sin datos suficientes"
- No inventes irregularidades que no surjan de la conversación
- La ley correcta es 20.589 NO 20.520

DATOS DEL CONTRATISTA:
- Nombre: {nombre}
- Empleador: {empleador}
- Dirección finca: {direccion}
- Hectáreas: {hectareas}
- Fecha inicio: {fecha_inicio}
- Información adicional: {extra if extra.upper() != "NO" else "Ninguna"}

CONVERSACIÓN:
{resumen_historial}

Generá el informe con estos títulos EXACTOS:

DATOS DEL CASO:
IRREGULARIDADES DETECTADAS:
DAÑO ECONÓMICO ESTIMADO:
BASE LEGAL APLICABLE:
ACCIONES RECOMENDADAS:
ORGANISMOS DONDE DENUNCIAR:
NOTA IMPORTANTE:"""

    try:
        res = model.generate_content(prompt)
        contenido = res.text
    except Exception as e:
        contenido = f"Error: {str(e)}"
    
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io as io_mod
    from datetime import datetime
    
    buffer = io_mod.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    
    estilo_titulo = ParagraphStyle("Titulo", parent=styles["Heading1"],
        fontSize=16, textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=6, alignment=TA_CENTER)
    
    estilo_subtitulo = ParagraphStyle("Subtitulo", parent=styles["Heading2"],
        fontSize=11, textColor=colors.HexColor("#c0392b"),
        spaceAfter=4, spaceBefore=10)
    
    estilo_normal = ParagraphStyle("Normal2", parent=styles["Normal"],
        fontSize=10, spaceAfter=4, leading=14)
    
    estilo_dato = ParagraphStyle("Dato", parent=styles["Normal"],
        fontSize=10, spaceAfter=3, leading=13,
        textColor=colors.HexColor("#2c3e50"))
    
    estilo_footer = ParagraphStyle("Footer2", parent=styles["Normal"],
        fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
    
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    elementos = []
    
    # Encabezado
    elementos.append(Paragraph("⚖️ INFORME DE IRREGULARIDADES LABORALES", estilo_titulo))
    elementos.append(Paragraph("Estatuto del Contratista de Viñas y Frutales", estilo_titulo))
    elementos.append(Paragraph("Leyes 20.589 · 23.154 · 27.644", estilo_subtitulo))
    elementos.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#c0392b")))
    elementos.append(Spacer(1, 0.3*cm))
    
    # Tabla de datos del contratista
    elementos.append(Paragraph("DATOS DEL CONTRATISTA", estilo_subtitulo))
    tabla_datos = [
        ["Nombre:", nombre],
        ["Empleador:", empleador],
        ["Dirección:", direccion],
        ["Hectáreas:", hectareas],
        ["Desde:", fecha_inicio],
    ]
    tabla = Table(tabla_datos, colWidths=[4*cm, 13*cm])
    tabla.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#c0392b")),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.HexColor("#f8f9fa"), colors.white]),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 0.3*cm))
    elementos.append(Paragraph(f"Informe generado: {fecha}", estilo_footer))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    elementos.append(Spacer(1, 0.3*cm))
    
    # Contenido del informe
    secciones = [
        "DATOS DEL CASO:",
        "IRREGULARIDADES DETECTADAS:",
        "DAÑO ECONÓMICO ESTIMADO:",
        "BASE LEGAL APLICABLE:",
        "ACCIONES RECOMENDADAS:",
        "ORGANISMOS DONDE DENUNCIAR:",
        "NOTA IMPORTANTE:"
    ]
    
    for linea in contenido.split("\n"):
        linea = linea.strip()
        if not linea:
            elementos.append(Spacer(1, 0.15*cm))
            continue
        
        es_seccion = any(s in linea.upper() for s in [s.upper() for s in secciones])
        if es_seccion:
            elementos.append(Spacer(1, 0.2*cm))
            elementos.append(Paragraph(linea, estilo_subtitulo))
        else:
            try:
                elementos.append(Paragraph(linea, estilo_normal))
            except:
                pass
    
    # Footer
    elementos.append(Spacer(1, 0.8*cm))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")))
    elementos.append(Spacer(1, 0.2*cm))
    elementos.append(Paragraph(
        "Bot Legal Viñas · Leyes 20.589, 23.154 y 27.644 · "
        "Informe orientativo - No reemplaza asesoramiento profesional matriculado.",
        estilo_footer))
    
    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()


async def comando_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if not es_autorizado(user_id):
        await update.message.reply_text("No tenés acceso.")
        return
    
    historial = obtener_historial(user_id)
    if not historial:
        await update.message.reply_text(
            "No hay consultas registradas todavía.\n"
            "Haceme tus preguntas primero y después usá /fin."
        )
        return
    
    keyboard = [[
        InlineKeyboardButton("📋 Sí, generar informe", callback_data=f"informe_{user_id}"),
        InlineKeyboardButton("❌ No, gracias", callback_data="cerrar_informe")
    ]]
    
    await update.message.reply_text(
        "✅ *Consulta finalizada.*\n\n"
        "Registré toda la información que me contaste.\n"
        "¿Querés que genere un informe completo de irregularidades "
        "para enviarle a un abogado?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def generar_informe_con_manus(historial: list, datos: dict) -> bytes:
    import requests, time, io as io_mod, base64
    from datetime import datetime
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.enums import TA_CENTER

    resumen = "\n".join([f"{m['role'].upper()}: {m['texto'][:400]}" for m in historial[-10:]])
    extra = dados.get("irregularidades_extra", "") if (dados := datos) else ""

    headers = {"x-manus-api-key": MANUS_API_KEY, "Content-Type": "application/json"}
    escala_doc = """%PDF-1.5
%
11 0 obj
<<
/BM /Normal
/CA 1
/Type /ExtGState
/ca 1
>>
endobj
14 0 obj
<<
/Length1 33868
/Filter /FlateDecode
/Length 16186
>>
stream
x}	|Jnɺoɲ$۲%N 4!@9Sr44@%$H!RH˯RPhB)G	ّlI|wy̛ٕ0BH"R/WXª!\TG{>@ي򥫗{ $M-;kҤ"lGhZ%޲":<$qO]rOs֪EhQ;-:%Y9pj9
3/V.qW<=w^n
]z_?_D,F"$Y9УJBZ°2(4vHPkۍ5b4QNFxıGD*R'*I!CFLE!TJtԄ,4
%hZAЃh?
FE9̫nؘPj*DِojD-BEh:=]X{uGEOq؆kѕ`B>+~tfײ=G-JFfdG~@aho%Eu͆GrmB[[9_[y'B;mh7z=~~^ʠE'[=1#,lk?~~O)#HLc?.B 퉐3qa;FˑFȫaЏ	
9>3zi
sFyh3mA]dxb]Fנkuh݀nD7-VNt{,wQ%1w{;]nt/??0BB.Ы;!ϽB*ڋ"h1EGt!t=9>))S()z=~x=__~0~v^FECߣ7@>8)7HZ,՛]H9)i:U!
6NBb}HFAB7r$#ҹK3	;.<Cv/p0οSs1P~4$X$Ay|<sB\Dx=uw^MџP	oCeRdR$<1{p$Gs,~}>>?yc7	?wrԐ}NB#	)1#|l1Y4:q7*EXsZbV`%Va5̝)1I1SIdz/M
M.)	q7xq*BNx^0%Mx|q>\K $/laY	;PfuЮU1r=IyK4)Z=Nh܉p'Hb8xkA͛;m֖Ɔu5ʊҒp(+3KzFˤI	2!64dwT?9͐_H果KiJ~<%ָQyV:VuG^u
=<Jx<]g^^so믅e5ޚ%LW&[9
yWiXaJ$Cm=u6WC5BYC!P{i3{omWF5haPػx`^;u۶]6
{k7m./
PXsxxHx>ExCb!bSDnI{mB<ҖGy<C[{ߍ"{~s$c&1[1"9C[2 =.ZNp`6om-[W_7@u{Ð~:g(]=V&2X#de5%rm믥
$ey{Aycow|K1d,^:-\y^`_gI/W3TjrAߦ'&==%҂w=|x!BDlCdPK,TxX_MbI֚Ci-&o(),
sڦԤA%	
T(Xin'Cxr$q6ģX\c!HBmoto!}#mn#H;%]|4t>hUOކ)эh$os6R7V rN/N·Y~ָ
DǶ.ܶ緭_^J6.)	mlDJF͸:+^|y^_9ݗwDWMGB(CBI 񸉇$!B,'EQxF
h/d^,ν{BF%!DCr/fĊ!wI[M«Hx
p	(2'm<
Ճl"KtGƺz<lýPy@szAE&H7P?Oںhu_^PxqH
%Hc%@z!QGȴdoޡ gEΚ!-2E~RQw[7W0dHmR&IE^ZnshQ':Ke6DοD -HX\)@#"6^]Kuk"+c;HASIҟbڣ{.,BIR`-gN"s<VQ*!=WY_Wt^FO%QLd{n04745T)oۖ<uʯ$8B W+^v,ԊfH[Rڤ,e?!V-_ɶk$W2]jמc%c8KÚ%9X
W1XM	1a^^n%S!,u2>R?fLn$)%%.җV7zӬ".I̊$jo_#`:#OT'>~yy2UQ)gDҤ9
9fZ)RLV$Ie4ld2j|#e	) ?z
qM7c엫q7: w>kV"#Vr7E8/z()p2P^S4"oYHu#sUUUXƂ	gŖ>ܼ͗=G&arOԕF*둨Xo_XL/*✼=j`(_/Voe^Y}@+~īfDT܈J'Ħ/w gYQ+
A+(u1;
92E2yQfcDn
D1/'G;5}TӞo&(N.u8X5
pnx3Ӷ*y=)m~ab :dq~zDu\oy<nk͡`Q_]"""
    ccg_doc = """No disponible"""
    prompt = f"""Sos experto en Estatuto del Contratista de Viñas Argentina (Leyes 20.589, 23.154, 27.644).
Analizá esta conversación y generá informe de irregularidades.

ESCALA SALARIAL OFICIAL: {escala_doc}

CORRESPONSABILIDAD GREMIAL: {ccg_doc}

BUSCÁ EN INTERNET SOLAMENTE el precio actual del kg y tacho de uva en Mendoza 2026.

SOBRE EL MONOTRIBUTO - INFORMACIÓN IMPORTANTE:
Según el ReNAF (Registro Nacional de Agricultura Familiar) y la normativa vigente,
existe el Monotributo Social para agricultores familiares. Sin embargo, para el
contratista de viñas esto NO es beneficioso porque:
1. El 18% de participación en frutos es REMUNERACIÓN LABORAL según Art. 16 Ley 20.589
2. Pasar a monotributo implica perder la relación de dependencia y todos sus derechos
3. El fallo Cotifane c/Galarraga (2006) confirmó que el estatuto es autónomo y cerrado
4. La Comisión Paritaria Provincial (Art. 36 Ley 23.154) es el único organismo
   que puede fijar remuneraciones del contratista
Incluir esta información en la sección del costo del monotributo.

CONVERSACIÓN: {resumen}
INFO EXTRA: {extra if extra and extra.upper() != "NO" else "Ninguna"}

REGLAS: Solo leyes reales. No inventes artículos. Si no hay datos escribí Sin datos suficientes.
Generá con títulos EXACTOS:
IRREGULARIDADES DETECTADAS:
DAÑO ECONÓMICO ESTIMADO:
BASE LEGAL APLICABLE:
ACCIONES RECOMENDADAS:
ORGANISMOS DONDE DENUNCIAR:
PRECIO ACTUAL DE LA UVA (búsqueda web):
NOTA IMPORTANTE:"""

    contenido = ""
    try:
        resp = requests.post("https://api.manus.ai/v2/task.create", headers=headers,
            json={"message": {"content": prompt}, "share_visibility": "public"})
        data = resp.json()
        if data.get("ok"):
            task_id = data["task_id"]
            print(f"✅ Manus tarea creada: {task_id}")
            for _ in range(60):
                time.sleep(10)
                msgs = requests.get(f"https://api.manus.ai/v2/task.listMessages?task_id={task_id}&order=desc&limit=20", headers=headers).json()
                if not msgs.get("ok"):
                    continue
                for msg in msgs.get("messages", []):
                    if msg.get("type") == "status_update":
                        status = msg.get("status_update", {}).get("agent_status", "")
                        if status == "stopped":
                            for m in msgs.get("messages", []):
                                if m.get("type") == "assistant_message":
                                    texto = str(m.get("assistant_message", {}).get("content", ""))
                                    if len(texto) > 500:
                                        contenido = texto[:5000]
                            if contenido:
                                break
                        elif status == "waiting":
                            if msg.get("status_update", {}).get("status_detail", {}).get("waiting_for_event_type") == "messageAskUser":
                                requests.post("https://api.manus.ai/v2/task.sendMessage", headers=headers,
                                    json={"task_id": task_id, "message": {"content": "Generá el informe ahora con los datos disponibles."}})
                if contenido:
                    break
    except Exception as e:
        print(f"Error Manus: {e}")

    if not contenido:
        try:
            res = model.generate_content(prompt[:50000])
            contenido = res.text
            print("⚠️ Manus tardó, Gemini como respaldo")
        except Exception as e:
            contenido = "Error generando informe."

    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    buffer = io_mod.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    T = ParagraphStyle("T", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#1a1a2e"), spaceAfter=6, alignment=TA_CENTER)
    S = ParagraphStyle("S", parent=styles["Heading2"], fontSize=11, textColor=colors.HexColor("#c0392b"), spaceAfter=4, spaceBefore=10)
    N = ParagraphStyle("N", parent=styles["Normal"], fontSize=10, spaceAfter=4, leading=14)
    C = ParagraphStyle("C", parent=styles["Normal"], fontSize=10, spaceAfter=2, textColor=colors.HexColor("#c0392b"), fontName="Helvetica-Bold")
    F = ParagraphStyle("F", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER)

    el = []
    el.append(Paragraph("INFORME DE IRREGULARIDADES LABORALES", T))
    el.append(Paragraph("Estatuto del Contratista de Viñas y Frutales", T))
    el.append(Paragraph("Leyes 20.589 · 23.154 · 27.644", S))
    el.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#c0392b")))
    el.append(Spacer(1, 0.3*cm))
    el.append(Paragraph("DATOS DEL CONTRATISTA", S))
    for campo, linea in [("Nombre y Apellido:","_"*60),("Empleador / Razón Social:","_"*60),("Dirección de la Finca:","_"*60),("Hectáreas trabajadas:","_"*30),("Fecha de inicio:","_"*30),("DNI:","_"*30),("CUIL/CUIT Empleador:","_"*30)]:
        el.append(Paragraph(campo, C))
        el.append(Paragraph(linea, N))
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph(f"Generado: {fecha} | Manus AI + Gemini", F))
    el.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    el.append(Spacer(1, 0.3*cm))

    secciones = ["IRREGULARIDADES DETECTADAS:","DAÑO ECONÓMICO ESTIMADO:","BASE LEGAL APLICABLE:","ACCIONES RECOMENDADAS:","ORGANISMOS DONDE DENUNCIAR:","INFORMACIÓN ACTUALIZADA DEL MERCADO:","NOTA IMPORTANTE:"]
    for linea in contenido.split("\n"):
        linea = linea.strip()
        if not linea:
            el.append(Spacer(1, 0.15*cm))
            continue
        if any(s in linea.upper() for s in [s.upper() for s in secciones]):
            el.append(Spacer(1, 0.2*cm))
            el.append(Paragraph(linea, S))
        else:
            try:
                el.append(Paragraph(linea, N))
            except:
                pass

    el.append(Spacer(1, 0.5*cm))
    el.append(Paragraph("FIRMA DEL CONTRATISTA:", C))
    el.append(Spacer(1, 1.5*cm))
    el.append(HRFlowable(width="50%", thickness=1, color=colors.black))
    el.append(Paragraph("Aclaración y DNI", F))
    el.append(Spacer(1, 0.5*cm))
    el.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")))
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph(f"Bot Legal Viñas · Leyes 20.589, 23.154 y 27.644 · Informe orientativo · Manus AI · {fecha}", F))
    doc.build(el)
    buffer.seek(0)
    return buffer.getvalue()


async def analizar_recibo_completo(imagen_bytes: bytes, datos_contrato: dict) -> str:
    """Analiza recibo cruzando con datos del contrato y boleta de riego"""
    import base64
    
    hectareas_contrato = datos_contrato.get("hectareas_contrato", "no especificado")
    hectareas_riego = datos_contrato.get("hectareas_riego", "no especificado")
    fecha_ingreso = datos_contrato.get("fecha_ingreso", "no especificada")
    empleador = datos_contrato.get("nombre_empleador", "no especificado")
    sindicalizado = datos_contrato.get("sindicalizado", "no especificado")
    
    img_b64 = base64.b64encode(imagen_bytes).decode()
    
    prompt_analisis = f"""Analizá este recibo de sueldo de un contratista de viñas de Mendoza, Argentina.

DATOS DEL CONTRATO (para cruzar con el recibo):
- Hectáreas en el contrato: {hectareas_contrato} ha
- Hectáreas en boleta de riego (Irrigación): {hectareas_riego} ha
- Fecha de ingreso: {fecha_ingreso}
- Nombre del empleador: {empleador}
- Sindicalizado: {sindicalizado}

INSTRUCCIONES DE ANÁLISIS:
1. Comparar las hectáreas del recibo con las del contrato y boleta de riego
2. Verificar si los montos remunerativos y no remunerativos coinciden con la escala salarial vigente
3. Detectar deducciones incorrectas o excesivas (especialmente Seguro de Sepelio y cuotas sindicales)
4. Verificar aportes jubilatorios (11%), Ley 19032 (3%) y Obra Social (~3%)
5. Comparar el nombre del empleador en el recibo con el dato proporcionado
6. Detectar cualquier inconsistencia entre documentos

FORMATO DE RESPUESTA:
✅ CORRECTO:
[lista lo que está bien]

🔴 IRREGULARIDADES DETECTADAS:
[lista cada problema con artículo violado si aplica]

⚠️ ALERTAS IMPORTANTES:
[discrepancias entre documentos]

💰 IMPACTO ECONÓMICO:
[calcular diferencias si hay irregularidades]

📋 ACCIONES RECOMENDADAS:
[pasos concretos a seguir]"""

    try:
        # Intentar con Manus primero (mejor análisis)
        import requests, time
        headers = {"x-manus-api-key": MANUS_API_KEY, "Content-Type": "application/json"}
        resp = requests.post(
            "https://api.manus.ai/v2/task.create",
            headers=headers,
            json={
                "message": {
                    "content": [
                        {"type": "text", "text": prompt_analisis},
                        {"type": "file", "file_data": f"data:image/jpeg;base64,{img_b64}", "filename": "recibo.jpg"}
                    ]
                },
                "share_visibility": "public"
            }
        )
        data = resp.json()
        if data.get("ok"):
            task_id = data["task_id"]
            for _ in range(36):
                time.sleep(10)
                msgs = requests.get(
                    f"https://api.manus.ai/v2/task.listMessages?task_id={task_id}&order=desc&limit=20",
                    headers=headers
                ).json()
                if not msgs.get("ok"):
                    continue
                for msg in msgs.get("messages", []):
                    if msg.get("type") == "status_update":
                        status = msg.get("status_update", {}).get("agent_status", "")
                        if status == "stopped":
                            for m in msgs.get("messages", []):
                                if m.get("type") == "assistant_message":
                                    texto = str(m.get("assistant_message", {}).get("content", ""))
                                    if len(texto) > 200:
                                        return texto[:5000]
                        elif status == "waiting":
                            if msg.get("status_update", {}).get("status_detail", {}).get("waiting_for_event_type") == "messageAskUser":
                                requests.post(
                                    "https://api.manus.ai/v2/task.sendMessage",
                                    headers=headers,
                                    json={"task_id": task_id, "message": {"content": "Analizá el recibo ahora con los datos proporcionados."}}
                                )
    except Exception as e:
        print(f"Manus falló: {e}")
    
    # Gemini como respaldo
    try:
        from vertexai.generative_models import Part
        imagen_part = Part.from_data(imagen_bytes, mime_type="image/jpeg")
        res = model.generate_content([prompt_analisis, imagen_part])
        return res.text
    except Exception as e:
        return f"Error al analizar el recibo: {str(e)}"


async def analizar_recibo_con_gemini(imagen_bytes: bytes, datos_contrato: dict) -> str:
    """Analiza recibo usando SOLO documentos oficiales cargados en el VPS"""
    from vertexai.generative_models import Part

    hectareas_contrato = datos_contrato.get("hectareas_contrato", "no especificado")
    hectareas_declaracion = datos_contrato.get("hectareas_declaracion", "no especificado")
    hectareas_riego = datos_contrato.get("hectareas_riego", "no especificado")
    fecha_ingreso = datos_contrato.get("fecha_ingreso", "no especificada")
    empleador_contrato = datos_contrato.get("nombre_empleador_contrato", "no especificado")
    sindicalizado = datos_contrato.get("sindicalizado", "no especificado")
    porcentaje = datos_contrato.get("porcentaje_cosecha", "18")

    # Buscar contexto relevante del RAG
    contexto_escala = buscar_contexto_relevante("escala salarial contratista viñas 2026", n_resultados=3)
    contexto_leyes = buscar_contexto_relevante("fondo desempleo contribucion patronal ley 25191", n_resultados=2)
    contexto_contrato = buscar_contexto_relevante("contrato contratista viñas hectareas remuneracion", n_resultados=2)
    contexto_docs = contexto_escala + "\n" + contexto_leyes + "\n" + contexto_contrato

    prompt = f"""Sos un auditor laboral experto en el Estatuto del Contratista de Viñas y Frutales de Argentina.

REGLAS ABSOLUTAS - CUMPLIMIENTO OBLIGATORIO:
1. SOLO usá información que esté en los DOCUMENTOS OFICIALES que te proporciono abajo
2. NUNCA inventes montos, porcentajes ni artículos que no estén en esos documentos
3. Si un dato no está en los documentos, escribí exactamente: "Ver documento oficial"
4. NUNCA uses valores de tu entrenamiento - SOLO los documentos proporcionados
5. Si no podés verificar un dato, decí "No verificado - consultar documento original"

DOCUMENTOS OFICIALES CARGADOS EN EL SISTEMA:
{contexto_docs}

DATOS DEL CONTRATISTA:
- Hectáreas según contrato (001/12): {hectareas_contrato} ha
- Hectáreas en producción según DJ (002/12): {hectareas_declaracion} ha  
- Hectáreas según boleta de riego: {hectareas_riego} ha
- Fecha de ingreso: {fecha_ingreso}
- Nombre empleador en contrato: {empleador_contrato}
- Sindicalizado: {sindicalizado}
- Porcentaje cosecha pactado: {porcentaje}%

ANALIZÁ EL RECIBO Y GENERÁ EL INFORME CON ESTE FORMATO:

═══════════════════════════════════════════════
INFORME INTEGRAL DE AUDITORÍA LABORAL
Estatuto del Contratista de Viñas y Frutales
═══════════════════════════════════════════════

1. RESUMEN EJECUTIVO
[Resumen con hallazgos principales basados SOLO en los documentos]

2. DATOS IDENTIFICATORIOS CRUZADOS
Dato | Contrato | Recibo | Estado
Nombre empleador | {empleador_contrato} | [leer del recibo] | [¿coincide?]
Hectáreas liquidadas | {hectareas_contrato} ha | [leer del recibo] | [¿coincide?]
Fecha ingreso | {fecha_ingreso} | [leer del recibo] | [¿coincide?]

3. ANÁLISIS DE HECTÁREAS
Documento | Hectáreas | Detalle
Contrato 001/12 | {hectareas_contrato} ha | Superficie contractual
DJ 002/12 | {hectareas_declaracion} ha | Superficie en producción
Recibo de Sueldo | [leer del recibo] | Superficie liquidada
Boleta de Riego | {hectareas_riego} ha | Superficie de riego
[Si hay discrepancias: marcar como 🔴 ALERTA]

4. ANÁLISIS SALARIAL
Usando EXCLUSIVAMENTE los valores de la ESCALA SALARIAL del documento oficial:
Concepto | Escala Oficial | Recibo | Estado
[completar SOLO con valores de los documentos proporcionados]

5. ANÁLISIS DE DEDUCCIONES
Usando EXCLUSIVAMENTE las leyes y resoluciones de los documentos oficiales:
[Para cada deducción: ✅ CORRECTO o 🔴 IRREGULAR]
IMPORTANTE: El Fondo de Desempleo - verificar en documento Ley 25.191 si es patronal o del trabajador

6. 🔴 ALERTAS CRÍTICAS
[Solo alertas verificadas con los documentos. Si no podés verificar, indicar "Requiere verificación con documento original"]

7. 🟡 ALERTAS IMPORTANTES
[Idem]

8. COSTO DE ACEPTAR MONOTRIBUTO
Calcular desde {fecha_ingreso} hasta hoy usando SOLO lo que dicen los documentos oficiales sobre indemnizaciones.
Si no tenés el dato en los documentos, escribí "Ver Art. 12 Ley 23.154 para el cálculo"

9. ACCIONES RECOMENDADAS
[Solo acciones basadas en las leyes de los documentos]

10. ORGANISMOS DONDE DENUNCIAR
[Incluir los organismos que figuren en los documentos cargados]

11. BASE LEGAL
[Citar SOLO artículos que estén en los documentos proporcionados]

═══════════════════════════════════════════════
ADVERTENCIA LEGAL: Este informe se basa en los documentos oficiales cargados en el sistema.
Consultar siempre con un abogado o contador matriculado antes de tomar decisiones legales.
═══════════════════════════════════════════════"""

    for intento in range(3):
        try:
            imagen_part = Part.from_data(imagen_bytes, mime_type="image/jpeg")
            res = model.generate_content([prompt, imagen_part])
            return res.text
        except Exception as e:
            if "429" in str(e) and intento < 2:
                import time
                print(f"429 Vision, esperando 30 segundos... intento {intento+1}")
                time.sleep(30)
            else:
                return f"Error al analizar el recibo: {str(e)[:200]}"
    return "No se pudo analizar el recibo. Intentá de nuevo en unos minutos."


async def extraer_texto_documento(imagen_bytes: bytes, tipo_doc: str) -> str:
    """Extrae y estructura el texto de un documento usando Gemini Vision"""
    from vertexai.generative_models import Part
    
    prompts = {
        "contrato": """Transcribí EXACTAMENTE todo el contenido de este Formulario 001/12 (Contrato de Cultivo de Viñas).
Incluí: nombre del empleador, CUIT, domicilio, nombre del contratista, DNI, fecha de ingreso, superficie, porcentaje pactado, ubicación de la finca, y todos los artículos del contrato.""",
        "declaracion": """Transcribí EXACTAMENTE todo el contenido de este Formulario 002/12 (Declaración Jurada).
Incluí: nombre del empleador, CUIT, domicilio, nombre del contratista, superficie total, superficie en producción, detalles de cultivo, condiciones de vivienda, estado sindical, y datos de riego.""",
        "recibo": """Transcribí EXACTAMENTE todos los conceptos y montos de este recibo de sueldo.
Incluí: nombre del trabajador, nombre del empleador, período, CUIL, cada concepto con su monto (remunerativo y no remunerativo), cada descuento con su monto, total bruto, total descuentos y neto a cobrar.""",
        "riego": """Transcribí EXACTAMENTE todo el contenido de esta boleta/aviso de riego.
Incluí: nombre del titular, fecha del turno, horario, superficie en hectáreas, tiempo de agua, y cualquier otro dato."""
    }
    
    prompt = prompts.get(tipo_doc, "Transcribí exactamente todo el contenido de este documento.")
    
    for intento in range(3):
        try:
            imagen_part = Part.from_data(imagen_bytes, mime_type="image/jpeg")
            res = model.generate_content([prompt, imagen_part])
            return res.text
        except Exception as e:
            if "429" in str(e) and intento < 2:
                import time
                time.sleep(30)
            else:
                return f"No se pudo leer el documento: {str(e)[:100]}"
    return "Error al leer el documento"


async def generar_informe_integral(textos: dict, sindicalizado: str) -> str:
    """Genera el informe completo con el prompt de Manus"""
    
    contrato = textos.get("contrato", "No proporcionado")
    declaracion = textos.get("declaracion", "No proporcionado")
    recibo = textos.get("recibo", "No proporcionado")
    riego = textos.get("riego", "No proporcionado")
    
    # Buscar escala salarial del RAG
    escala = buscar_contexto_relevante("escala salarial contratista viñas 2026 remunerativo", n_resultados=3)
    
    prompt = f"""Sos un auditor laboral experto en el Estatuto del Contratista de Viñas y Frutales (Leyes 20.589, 23.154 y 27.644).

Generá un informe final completo que unifique y cruce los documentos proporcionados.

REGLAS ABSOLUTAS:
- SOLO usá información que esté en los documentos proporcionados abajo
- NUNCA inventes montos, porcentajes ni artículos
- Si un dato no está en los documentos escribí "Ver documento original"
- Para el cálculo de indemnizaciones usar Art. 12 Ley 23.154, NO el Art. 245 LCT

DOCUMENTOS ANALIZADOS:

=== CONTRATO 001/12 ===
{contrato}

=== DECLARACIÓN JURADA 002/12 ===
{declaracion}

=== RECIBO DE SUELDO ===
{recibo}

=== BOLETA DE RIEGO ===
{riego}

=== ESCALA SALARIAL OFICIAL ===
{escala}

=== DATO ADICIONAL ===
Sindicalizado: {sindicalizado}

Generá el informe con estas secciones EXACTAS:

## 1. RESUMEN EJECUTIVO
Un párrafo con el estado general del contrato y situación del contratista.

## 2. DATOS IDENTIFICATORIOS CRUZADOS
Tabla comparando en todos los documentos:
| Dato | Contrato 001/12 | DJ 002/12 | Recibo | Boleta Riego | Estado |
[completar con datos reales de los documentos]
Marcar ✅ si coincide, ⚠️ si hay variación, 🔴 si hay contradicción grave

## 3. ANÁLISIS DEL CONTRATO (Formularios 001/12 y 002/12)
Explicar cada artículo del contrato y cómo se refleja en la realidad documentada.
Incluir implicaciones legales para el contratista.

## 4. ANÁLISIS DEL RECIBO DE SUELDO vs. ESCALA SALARIAL
| Concepto | Escala Oficial | Recibo | Valor/ha | Estado |
[completar con datos reales]
Marcar ✅ CORRECTO o 🔴 IRREGULAR con montos exactos

## 5. ANÁLISIS DE LA BOLETA DE RIEGO vs. CONTRATO
| Documento | Hectáreas Declaradas | Detalle |
[completar con datos reales]
Analizar discrepancias entre hectáreas de riego y contrato.

## 6. DISCREPANCIAS Y ALERTAS DETECTADAS

### 🔴 ALERTAS CRÍTICAS (Requieren Acción Inmediata)
Para cada alerta: descripción | impacto económico | causa probable | acción recomendada

### 🟡 ALERTAS IMPORTANTES (Requieren Atención)
[idem]

### 🔵 ALERTAS MENORES (Requieren Seguimiento)
[idem]

## 7. COSTO DE ACEPTAR EL MONOTRIBUTO
Calcular usando Art. 12 Ley 23.154 (NO Art. 245 LCT):
- Antigüedad desde fecha de ingreso hasta hoy
- Indemnización según estatuto específico del contratista
- SAC proporcional
- Preaviso
- Seguro Desempleo RENATRE (Res. 19/2026)
- **TOTAL QUE SE PIERDE AL ACEPTAR MONOTRIBUTO**
⚠️ "No firme su propia renuncia disfrazada de contrato independiente"

## 8. RECOMENDACIONES PARA EL CONTRATISTA

### Acciones Inmediatas (Esta Semana)
[lista numerada con pasos concretos]

### Acciones de Mediano Plazo (Este Mes)
[lista numerada]

### Acciones de Largo Plazo
[lista numerada]

## 9. ORGANISMOS DONDE DENUNCIAR
| Organismo | Teléfono | Dirección | Asunto |
| Subsecretaría de Trabajo Delegación Este | 0263-4433021 | Aguado 556, San Martín | Irregularidades laborales |
| Departamento General de Irrigación | 0263-4420678 | Alem 1217, San Martín | Verificación superficie |
| SUTCVyF Sindicato | 0261-4239650 | Pedro Vargas 523, Mendoza | Asesoramiento |
| AFIP | 0810-999-2347 | — | Verificación datos empleador |
| OSPRERA (Obra Social) | — | — | Consultas obra social |

## 10. BASE LEGAL APLICABLE
[Citar SOLO artículos que estén en los documentos proporcionados]

---
*Informe generado por Bot Legal Viñas | Leyes 20.589, 23.154 y 27.644*
*Este informe es orientativo. No reemplaza asesoramiento de abogado o contador matriculado.*"""

    for intento in range(3):
        try:
            res = model.generate_content(prompt)
            return res.text
        except Exception as e:
            if "429" in str(e) and intento < 2:
                import time
                time.sleep(30)
            else:
                return f"Error al generar el informe: {str(e)[:200]}"
    return "No se pudo generar el informe. Intentá de nuevo."


def convertir_informe_a_pdf(texto: str, titulo: str = "Informe de Auditoría Laboral") -> bytes:
    """Convierte el texto del informe a PDF profesional con ReportLab"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io as io_mod
    from datetime import datetime
    import re

    buffer = io_mod.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=1.2*cm, leftMargin=1.2*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()
    PAGE_WIDTH = A4[0] - 2.4*cm

    estilo_titulo = ParagraphStyle("Titulo", parent=styles["Heading1"],
        fontSize=13, textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica-Bold")
    estilo_subtitulo = ParagraphStyle("Subtitulo", parent=styles["Heading1"],
        fontSize=11, textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=4, spaceBefore=8, fontName="Helvetica-Bold")
    estilo_h3_rojo = ParagraphStyle("H3Rojo", parent=styles["Heading2"],
        fontSize=10, textColor=colors.HexColor("#c0392b"),
        spaceAfter=3, spaceBefore=6, fontName="Helvetica-Bold")
    estilo_h3_amarillo = ParagraphStyle("H3Amarillo", parent=styles["Heading2"],
        fontSize=10, textColor=colors.HexColor("#e67e22"),
        spaceAfter=3, spaceBefore=6, fontName="Helvetica-Bold")
    estilo_h3_azul = ParagraphStyle("H3Azul", parent=styles["Heading2"],
        fontSize=10, textColor=colors.HexColor("#2980b9"),
        spaceAfter=3, spaceBefore=6, fontName="Helvetica-Bold")
    estilo_h3 = ParagraphStyle("H3", parent=styles["Heading2"],
        fontSize=10, textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=3, spaceBefore=6, fontName="Helvetica-Bold")
    estilo_normal = ParagraphStyle("Normal2", parent=styles["Normal"],
        fontSize=8.5, spaceAfter=3, leading=12)
    estilo_tabla = ParagraphStyle("Tabla", parent=styles["Normal"],
        fontSize=7.5, leading=10, wordWrap="CJK")
    estilo_footer = ParagraphStyle("Footer", parent=styles["Normal"],
        fontSize=7, textColor=colors.grey, alignment=TA_CENTER)

    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    elementos = []

    elementos.append(Paragraph("INFORME INTEGRAL DE AUDITORÍA LABORAL", estilo_titulo))
    elementos.append(Paragraph("Estatuto del Contratista de Viñas y Frutales", estilo_titulo))
    elementos.append(Paragraph("Leyes 20.589 · 23.154 · 27.644", estilo_h3))
    elementos.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#c0392b")))
    elementos.append(Paragraph(f"Generado: {fecha} | Bot Legal Viñas", estilo_footer))
    elementos.append(Spacer(1, 0.3*cm))

    def limpiar_md(txt):
        txt = re.sub(r"\*\*(.*?)\*\*", r"\1", txt)
        txt = re.sub(r"\*(.*?)\*", r"\1", txt)
        txt = txt.replace("`", "").strip()
        return txt

    def hacer_parrafo(txt, estilo):
        try:
            return Paragraph(txt, estilo)
        except:
            try:
                return Paragraph(txt.encode("ascii","ignore").decode(), estilo)
            except:
                return None

    def procesar_tabla(filas):
        if not filas:
            return None
        # Calcular anchos proporcionales según contenido
        num_cols = max(len(f) for f in filas)
        if num_cols == 0:
            return None
        ancho_total = PAGE_WIDTH
        ancho_col = ancho_total / num_cols
        col_widths = [ancho_col] * num_cols
        
        # Convertir celdas a Paragraphs
        tabla_data = []
        for fila in filas:
            row = []
            for celda in fila:
                p = hacer_parrafo(limpiar_md(celda), estilo_tabla)
                row.append(p if p else "")
            # Rellenar si faltan columnas
            while len(row) < num_cols:
                row.append("")
            tabla_data.append(row[:num_cols])
        
        try:
            t = Table(tabla_data, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("FONTSIZE", (0,0), (-1,-1), 7.5),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#f0f4f8"), colors.white]),
                ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#cccccc")),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("TOPPADDING", (0,0), (-1,-1), 3),
                ("BOTTOMPADDING", (0,0), (-1,-1), 3),
                ("LEFTPADDING", (0,0), (-1,-1), 4),
                ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ]))
            return t
        except Exception as e:
            print(f"Error tabla: {e}")
            return None

    lineas = texto.split("\n")
    tabla_filas = []
    en_tabla = False

    for linea in lineas:
        linea_strip = linea.strip()

        # Detectar fila de tabla
        if linea_strip.startswith("|"):
            if re.match(r"^\|[-:\s|]+\|$", linea_strip):
                # Es la fila separadora, ignorar
                pass
            else:
                celdas = [c.strip() for c in linea_strip.split("|")[1:-1]]
                if celdas:
                    tabla_filas.append(celdas)
                    en_tabla = True
            continue

        # Fin de tabla
        if en_tabla:
            t = procesar_tabla(tabla_filas)
            if t:
                elementos.append(t)
                elementos.append(Spacer(1, 0.2*cm))
            tabla_filas = []
            en_tabla = False

        if not linea_strip:
            elementos.append(Spacer(1, 0.1*cm))
            continue

        if linea_strip.startswith("## "):
            elementos.append(Spacer(1, 0.2*cm))
            elementos.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
            p = hacer_parrafo(limpiar_md(linea_strip[3:]), estilo_subtitulo)
            if p: elementos.append(p)
        elif linea_strip.startswith("### "):
            txt = limpiar_md(linea_strip[4:])
            if "🔴" in linea_strip:
                p = hacer_parrafo(txt, estilo_h3_rojo)
            elif "🟡" in linea_strip:
                p = hacer_parrafo(txt, estilo_h3_amarillo)
            elif "🔵" in linea_strip:
                p = hacer_parrafo(txt, estilo_h3_azul)
            else:
                p = hacer_parrafo(txt, estilo_h3)
            if p: elementos.append(p)
        elif linea_strip.startswith(("* ", "- ", "*   ")):
            txt = limpiar_md(linea_strip.lstrip("*- ").strip())
            p = hacer_parrafo(f"• {txt}", estilo_normal)
            if p: elementos.append(p)
        elif re.match(r"^\d+\.\s", linea_strip):
            p = hacer_parrafo(limpiar_md(linea_strip), estilo_normal)
            if p: elementos.append(p)
        else:
            p = hacer_parrafo(limpiar_md(linea_strip), estilo_normal)
            if p: elementos.append(p)

    # Procesar tabla pendiente
    if tabla_filas:
        t = procesar_tabla(tabla_filas)
        if t:
            elementos.append(t)

    elementos.append(Spacer(1, 0.5*cm))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")))
    elementos.append(Spacer(1, 0.2*cm))
    elementos.append(Paragraph(
        "Bot Legal Viñas · Leyes 20.589, 23.154 y 27.644 · "
        "Informe orientativo - No reemplaza asesoramiento profesional matriculado.",
        estilo_footer))

    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()





def generar_registro_tareas_pdf(datos: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io as io_mod

    AZUL = colors.HexColor("#1a3a6e")
    AZUL_CLARO = colors.HexColor("#e8edf5")
    VERDE = colors.HexColor("#1a5e1a")
    VERDE_CLARO = colors.HexColor("#e8f5e9")
    ROJO = colors.HexColor("#c0392b")
    ROJO_CLARO = colors.HexColor("#fdecea")
    NARANJA = colors.HexColor("#e67e22")
    NARANJA_CLARO = colors.HexColor("#fef5e7")
    GRIS = colors.HexColor("#555555")

    buffer = io_mod.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm)
    PAGE_W = A4[0] - 3*cm

    s_titulo = ParagraphStyle("T", fontSize=13, fontName="Helvetica-Bold", textColor=AZUL, alignment=TA_CENTER, spaceAfter=4)
    s_sub = ParagraphStyle("S", fontSize=9, fontName="Helvetica", textColor=GRIS, alignment=TA_CENTER, spaceAfter=6)
    s_normal = ParagraphStyle("N", fontSize=9, fontName="Helvetica", spaceAfter=4)
    s_footer = ParagraphStyle("F", fontSize=7, fontName="Helvetica", textColor=colors.grey, alignment=TA_CENTER)
    s_nota = ParagraphStyle("NOTA", fontSize=7.5, fontName="Helvetica", textColor=GRIS, spaceAfter=4)

    nc = datos.get("nombre_contratista", "_________________________")
    dni = datos.get("dni", "_____________")
    ne = datos.get("nombre_empleador", "_________________________")
    cuit = datos.get("cuit", "_____________")
    inv = datos.get("inv", "_______")
    ubic = datos.get("ubicacion", "_________________________")
    temp = datos.get("temporada", "2026")

    def campo(label, valor=""):
        return Paragraph(f"<b>{label}:</b>  {valor if valor else '_'*35}", s_normal)

    def seccion_elem(texto, color=AZUL):
        return [Spacer(1, 0.25*cm),
                Paragraph(texto, ParagraphStyle("SEC2", fontSize=10, fontName="Helvetica-Bold",
                    textColor=color, spaceAfter=4, spaceBefore=10)),
                HRFlowable(width="100%", thickness=1.5, color=color),
                Spacer(1, 0.15*cm)]

    def ch(texto, color=AZUL, size=7):
        return Paragraph(f"<b>{texto}</b>", ParagraphStyle("CH", fontSize=size, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=TA_CENTER, leading=9))

    def cd(texto="", bold=False, align=TA_LEFT, size=7.5):
        return Paragraph(texto, ParagraphStyle("CD", fontSize=size,
            fontName="Helvetica-Bold" if bold else "Helvetica", alignment=align))

    def enc():
        return [Paragraph("REGISTRO DE TAREAS Y LABORES - CONTRATISTA DE VIÑAS", s_titulo),
                Paragraph(f"Art. 6 y Art. 11 - Ley 20.589 - Temporada {temp}", s_sub),
                Paragraph("USO PERSONAL DEL CONTRATISTA - Documento de respaldo ante incumplimientos del empleador",
                    ParagraphStyle("AVE", fontSize=8, fontName="Helvetica-Bold", textColor=ROJO, alignment=TA_CENTER, spaceAfter=6)),
                HRFlowable(width="100%", thickness=2, color=AZUL), Spacer(1, 0.2*cm)]

    def tabla_t(tareas, color, col_w):
        hdr = [ch("TAREA", color), ch("Art.", color), ch("Fecha\nrealizacion", color),
               ch("Realizado\n(SI/NO)", color), ch("Observaciones", color)]
        td = [hdr]
        for tarea, art in tareas:
            td.append([cd(tarea, size=7), cd(art, align=TA_CENTER, size=7), cd(""), cd(""), cd("")])
        tc = Table(td, colWidths=col_w, repeatRows=1)
        tc.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),color),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTSIZE",(0,0),(-1,-1),7.5),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[VERDE_CLARO if color==VERDE else AZUL_CLARO, colors.white]),
            ("GRID",(0,0),(-1,-1),0.3,colors.grey),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
        ]))
        return tc

    col_c = [5.5*cm, 1.3*cm, 1.8*cm, 1.8*cm, 4.4*cm]
    col_p = [5.0*cm, 1.3*cm, 1.8*cm, 1.8*cm, 4.9*cm]

    el = []

    # PAGINA 1
    el += enc()
    el += seccion_elem("DATOS IDENTIFICATORIOS")
    dt = [
        [campo("Contratista", nc), campo("Empleador", ne)],
        [campo("DNI", dni), campo("CUIT / N° INV", f"{cuit} / {inv}")],
        [campo("Finca", ubic), campo("Temporada", temp)],
    ]
    t = Table(dt, colWidths=[PAGE_W/2, PAGE_W/2])
    t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),
        ("BACKGROUND",(0,0),(-1,0),AZUL_CLARO),("PADDING",(0,0),(-1,-1),5)]))
    el.append(t)
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph(
        "[C] = Obligacion CONTRATISTA | [P] = Obligacion PATRON | [E] = Extra que paga el patron",
        ParagraphStyle("REF", fontSize=7.5, fontName="Helvetica", textColor=AZUL,
            borderColor=AZUL, borderWidth=0.5, borderPadding=4, spaceAfter=8)))

    el += seccion_elem("ARADURAS [C] - Art. 6 a)", VERDE)
    el.append(Paragraph("4 araduras obligatorias: 2 abriendo y 2 tapando surcos.", s_nota))
    el.append(tabla_t([
        ("1° Aradura - ABRIENDO surcos", "Art. 6 a)"),
        ("2° Aradura - TAPANDO surcos", "Art. 6 a)"),
        ("3° Aradura - ABRIENDO surcos", "Art. 6 a)"),
        ("4° Aradura - TAPANDO surcos", "Art. 6 a)"),
        ("Pasada de RASTRA (si corresponde)", "Extra"),
        ("Pasada de DESMALEZADORA (si corresponde)", "Extra"),
        ("Arar y emparejar CALLEJONES", "Art. 6 i)"),
    ], VERDE, col_c))

    el += seccion_elem("PODA Y TRABAJOS EN VERDE [C] - Art. 6 b) y ll)", VERDE)
    el.append(tabla_t([
        ("PODA anual de la vid", "Art. 6 b)"),
        ("LIMPIEZA / desbrote - 1° pasada", "Art. 6 b)"),
        ("LIMPIEZA / desbrote - 2° pasada", "Art. 6 b)"),
        ("CRUZAR (atado cruzado de cargadores)", "Art. 6 b)"),
        ("ENVOLVER (atado de brotes al alambre)", "Art. 6 b)"),
        ("ESTIRAR ALAMBRES", "Art. 6 b)"),
        ("ATAR (atado de brotes y sarmientos)", "Art. 6 b)"),
        ("MUGRONES - dejar sarmiento atado en 2° alambre", "Art. 6 ll)"),
        ("DESHOJE (si lo indica el empleador - Extra)", "Extra"),
        ("RALEO DE RACIMOS (si lo indica el empleador - Extra)", "Extra"),
        ("RETIRO DE SARMIENTOS - dejar callejones libres", "Art. 6 d)"),
        ("VIGILANCIA VENDIMIA - recorrer hileras", "Art. 6 j)"),
    ], VERDE, col_c))

    # PAGINA 2
    el.append(PageBreak())
    el += enc()

    el += seccion_elem("FUMIGACIONES / CURACIONES [C] - Art. 6 e)", VERDE)
    el.append(Paragraph("2 fumigaciones obligatorias del contratista. La 3° en adelante paga el patron.", s_nota))
    el.append(tabla_t([
        ("1° CURACIÓN / Fumigacion obligatoria", "Art. 6 e)"),
        ("2° CURACIÓN / Fumigacion obligatoria", "Art. 6 e)"),
        ("3° Curación en adelante → PAGA EL PATRON", "Art. 11 i)"),
        ("4° Curación → PAGA EL PATRON", "Art. 11 i)"),
        ("5° Curación → PAGA EL PATRON", "Art. 11 i)"),
    ], VERDE, col_c))

    el += seccion_elem("OTROS TRABAJOS OBLIGATORIOS DEL CONTRATISTA [C]", VERDE)
    el.append(tabla_t([
        ("DESTRUIR HORMIGUEROS (hormiguicida lo provee el patron)", "Art. 6 c)"),
        ("LIMPIEZA DE ACEQUIAS Y DESAGUES", "Art. 6 f)"),
        ("REEMPLAZO rodrigones (hasta 10 por ha/año)", "Art. 6 g)"),
        ("REEMPLAZO postes cabeceros (hasta 5 por ha/año)", "Art. 6 g)"),
        ("ARREGLO alambrados exteriores proporcional al contrato", "Art. 6 h)"),
        ("MANTENIMIENTO puentes y callejones", "Art. 6 h)"),
        ("RIEGO - atender turno (cualquier dia y hora)", "Art. 6 l)"),
        ("ULTIMO RIEGO al finalizar la cosecha", "Art. 6 l)"),
        ("CUIDADO Y ALIMENTACION de animales de trabajo", "Art. 6 k)"),
        ("CUIDADO de herramientas y maquinarias entregadas", "Art. 6 m)"),
    ], VERDE, col_c))

    # PAGINA 3
    el.append(PageBreak())
    el += enc()

    el += seccion_elem("OBLIGACIONES DEL EMPLEADOR [P] - Art. 11 Ley 20.589", NARANJA)
    el.append(Paragraph("Si el patron no cumple estas obligaciones es incumplimiento denunciable.", s_nota))
    hdr_p = [ch("OBLIGACION DEL PATRON [P]", NARANJA), ch("Art.", NARANJA),
             ch("Cumplida\n(SI/NO)", NARANJA), ch("Fecha", NARANJA),
             ch("Observaciones / Incumplimiento", NARANJA)]
    td_p = [hdr_p]
    for tarea, art in [
        ("VIVIENDA adecuada para contratista y familia", "Art. 11 a)"),
        ("PRODUCTOS QUIMICOS preparados en el callejón", "Art. 11 b)"),
        ("MAQUINAS para combatir plagas y enfermedades", "Art. 11 b)"),
        ("ELEMENTOS PROTECTORES para productos peligrosos", "Art. 11 b)"),
        ("BOTIQUIN de primeros auxilios", "Art. 11 b)"),
        ("ANIMALES de trabajo bajo inventario", "Art. 11 c)"),
        ("HERRAMIENTAS y elementos para cultivos bajo inventario", "Art. 11 c)"),
        ("HORMIGUICIDA para destruir hormigueros", "Art. 6 c)"),
        ("AGUA para riego en la toma de la propiedad", "Art. 11 h)"),
        ("3° FUMIGACION en adelante (mas de 2 por año)", "Art. 11 i)"),
        ("REPODA por heladas o granizo", "Art. 11 g)"),
        ("MUGRONES PRENDIDOS - paga por cada mugrón prendido, atado y abonado", "Art. 23"),
        ("RODRIGONES extras (mas de 10 por ha/año)", "Art. 6 g)"),
        ("POSTES CABECEROS extras (mas de 5 por ha/año)", "Art. 6 g)"),
        ("PAGO mensualidad en tiempo y forma", "Art. 11 f)"),
        ("COMPROBANTE de peso y variedad en cosecha", "Art. 20"),
        ("MECANIZACION - ajustar remuneracion si mecaniza labores", "Art. 27"),
    ]:
        td_p.append([cd(tarea, size=7), cd(art, align=TA_CENTER, size=7), cd(""), cd(""), cd("")])
    tp = Table(td_p, colWidths=col_p, repeatRows=1)
    tp.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),NARANJA),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTSIZE",(0,0),(-1,-1),7.5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[NARANJA_CLARO,colors.white]),
        ("GRID",(0,0),(-1,-1),0.3,colors.grey),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))
    el.append(tp)

    # PAGINA 4
    el.append(PageBreak())
    el += enc()

    el += seccion_elem("LABORES EXTRAS REALIZADAS POR EL CONTRATISTA - PAGA EL PATRON [E]", ROJO)
    el.append(Paragraph("Registrar cada tarea que NO era obligacion del contratista y el patron debe pagar.", s_nota))
    col_e = [1.4*cm, 4.2*cm, 1.5*cm, 1.5*cm, 2.0*cm, 1.5*cm, 3.2*cm]
    hdr_e = [ch("Fecha", ROJO), ch("Tarea realizada", ROJO), ch("Horas\no dias", ROJO),
             ch("Cant.\npersonal", ROJO), ch("Precio\nunitario $", ROJO),
             ch("Total\n$", ROJO), ch("Estado\nPAGADO/DEBE", ROJO)]
    td_e = [hdr_e]
    for i in range(15):
        td_e.append([cd("") for _ in range(7)])
    td_e.append([cd("TOTAL PENDIENTE", bold=True), cd(""), cd(""), cd(""), cd(""),
                 cd("$", bold=True), cd("")])
    te = Table(td_e, colWidths=col_e, repeatRows=1)
    te.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),ROJO),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTSIZE",(0,0),(-1,-1),7.5),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[ROJO_CLARO,colors.white]),
        ("BACKGROUND",(0,-1),(-1,-1),ROJO_CLARO),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.3,colors.grey),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
        ("SPAN",(0,-1),(4,-1)),
    ]))
    el.append(te)
    el.append(Spacer(1, 0.3*cm))
    el += seccion_elem("OBSERVACIONES GENERALES")
    el.append(Table([[" "],[" "],[" "],[" "]], colWidths=[PAGE_W],
        rowHeights=[0.7*cm,0.7*cm,0.7*cm,0.7*cm],
        style=[("GRID",(0,0),(-1,-1),0.5,colors.lightgrey)]))
    el.append(Spacer(1, 0.3*cm))
    el.append(HRFlowable(width="100%", thickness=1, color=ROJO))
    el.append(Spacer(1, 0.15*cm))
    el.append(Paragraph(
        "Art. 13: si el patron no cumple el contratista puede rescindir con culpa del empleador. "
        "Art. 34: puede abandonar y reclamar indemnizacion si no paga 2 cuotas o no provee herramientas. "
        "Denuncias: SUTCVyF 0261-4239650 | Subsec. Trabajo San Martin 0263-4420100 | RENATEA 0800-222-7638",
        ParagraphStyle("NL", fontSize=7.5, fontName="Helvetica", textColor=ROJO, spaceAfter=6)))
    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    el.append(Paragraph("Registro de Tareas | Ley 20.589 Art. 6, 11 y 23 | Contratistas de Vinas y Frutales | Mendoza", s_footer))

    doc.build(el)
    buffer.seek(0)
    return buffer.getvalue()

def generar_registro_ventas_pdf(datos: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io as io_mod

    AZUL = colors.HexColor("#1a3a6e")
    AZUL_CLARO = colors.HexColor("#e8edf5")
    ROJO = colors.HexColor("#c0392b")
    GRIS = colors.HexColor("#555555")

    buffer = io_mod.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm)
    PAGE_W = A4[0] - 3*cm

    s_titulo = ParagraphStyle("T", fontSize=13, fontName="Helvetica-Bold", textColor=AZUL, alignment=TA_CENTER, spaceAfter=4)
    s_sub = ParagraphStyle("S", fontSize=9, fontName="Helvetica", textColor=GRIS, alignment=TA_CENTER, spaceAfter=6)
    s_seccion = ParagraphStyle("SEC", fontSize=10, fontName="Helvetica-Bold", textColor=AZUL, spaceAfter=4, spaceBefore=10)
    s_normal = ParagraphStyle("N", fontSize=9, fontName="Helvetica", spaceAfter=4)
    s_footer = ParagraphStyle("F", fontSize=7, fontName="Helvetica", textColor=colors.grey, alignment=TA_CENTER)
    s_nota = ParagraphStyle("NOTA", fontSize=7.5, fontName="Helvetica", textColor=GRIS, spaceAfter=4)

    nc = datos.get("nombre_contratista", "_________________________")
    dni = datos.get("dni", "_____________")
    ne = datos.get("nombre_empleador", "_________________________")
    cuit = datos.get("cuit", "_____________")
    inv = datos.get("inv", "_______")
    per = datos.get("periodo", "2026")
    porc = datos.get("porcentaje", "18")

    def campo(label, valor=""):
        return Paragraph(f"<b>{label}:</b>  {valor if valor else '_'*35}", s_normal)

    def seccion_elem(texto):
        return [Spacer(1, 0.25*cm), Paragraph(texto, s_seccion),
                HRFlowable(width="100%", thickness=1.5, color=AZUL), Spacer(1, 0.15*cm)]

    def ch(texto, size=7):
        return Paragraph(f"<b>{texto}</b>", ParagraphStyle("CH", fontSize=size, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=TA_CENTER, leading=9))

    def cd(texto="", bold=False, align=TA_CENTER, size=7.5):
        return Paragraph(texto, ParagraphStyle("CD", fontSize=size,
            fontName="Helvetica-Bold" if bold else "Helvetica", alignment=align))

    el = []
    el.append(Paragraph("REGISTRO DE VENTAS DE PRODUCCION", s_titulo))
    el.append(Paragraph(f"Control del porcentaje del contratista - Art. 16 Ley 23.154 - Temporada {per}", s_sub))
    el.append(Paragraph("USO PERSONAL DEL CONTRATISTA - Documento de respaldo para verificacion de haberes",
        ParagraphStyle("AVE", fontSize=8, fontName="Helvetica-Bold", textColor=ROJO, alignment=TA_CENTER, spaceAfter=6)))
    el.append(HRFlowable(width="100%", thickness=2, color=AZUL))
    el.append(Spacer(1, 0.25*cm))

    el += seccion_elem("DATOS IDENTIFICATORIOS")
    dt = [
        [campo("Contratista", nc), campo("Empleador", ne)],
        [campo("DNI", dni), campo("CUIT", cuit)],
        [campo("N° INV", inv), campo("Porcentaje pactado", f"{porc}%")],
    ]
    t = Table(dt, colWidths=[PAGE_W/2, PAGE_W/2])
    t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),
        ("BACKGROUND",(0,0),(-1,0),AZUL_CLARO),("PADDING",(0,0),(-1,-1),5)]))
    el.append(t)

    el += seccion_elem("REGISTRO DETALLADO DE VENTAS")
    el.append(Paragraph("Instruccion: Completar cada venta. En Estado escribir PAGADO o NO PAGADO.", s_nota))

    col_w = [1.3*cm, 2.2*cm, 2.0*cm, 1.3*cm, 1.5*cm, 1.5*cm, 2.0*cm, 1.8*cm, 1.8*cm]
    hdrs = ["Fecha", "Producto\n(variedad)", "Tipo\nventa", "Cant.\ncajas", "Peso\nkg/caja",
            "Precio\n$/kg", "Total\nventa $", f"Mi {porc}%\n$", "Estado\nPAG/NO PAG"]
    td = [[ch(h) for h in hdrs]]
    for i in range(25):
        td.append([cd("") for _ in range(9)])
    td.append([cd("TOTAL", bold=True), cd(""), cd(""), cd(""), cd(""), cd(""),
               cd("$", bold=True), cd("$", bold=True), cd("")])
    tc = Table(td, colWidths=col_w, repeatRows=1)
    tc.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),AZUL),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTSIZE",(0,0),(-1,-1),7.5),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[AZUL_CLARO,colors.white]),
        ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#d5e8f5")),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.3,colors.grey),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
        ("SPAN",(0,-1),(5,-1)),
    ]))
    el.append(tc)

    el += seccion_elem("RESUMEN")
    res = [
        [ch("CONCEPTO", size=8), ch("IMPORTE ($)", size=8)],
        [cd("Total ventas registradas ($):", align=TA_LEFT), cd("")],
        [cd("Total porcentaje que me corresponde ($):", align=TA_LEFT), cd("")],
        [cd("(-) Total ya cobrado/pagado ($):", align=TA_LEFT), cd("")],
        [Paragraph("<b>TOTAL PENDIENTE DE COBRO ($):</b>",
                   ParagraphStyle("RP", fontSize=9, fontName="Helvetica-Bold", textColor=colors.white)),
         Paragraph("<b>$</b>", ParagraphStyle("RP2", fontSize=9, fontName="Helvetica-Bold",
                   textColor=colors.white, alignment=TA_CENTER))],
    ]
    tr = Table(res, colWidths=[PAGE_W*0.72, PAGE_W*0.28])
    tr.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),AZUL),("BACKGROUND",(0,4),(-1,4),ROJO),
        ("ROWBACKGROUNDS",(0,1),(-1,3),[AZUL_CLARO,colors.white,AZUL_CLARO]),
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
        ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
    ]))
    el.append(tr)

    el += seccion_elem("OBSERVACIONES Y TESTIGOS")
    el.append(Table([[" "],[" "],[" "]], colWidths=[PAGE_W], rowHeights=[0.7*cm,0.7*cm,0.7*cm],
        style=[("GRID",(0,0),(-1,-1),0.5,colors.lightgrey)]))
    el.append(Spacer(1, 0.3*cm))
    el.append(HRFlowable(width="100%", thickness=1, color=ROJO))
    el.append(Spacer(1, 0.15*cm))
    el.append(Paragraph(
        "NOTA LEGAL: Registro de uso personal del contratista. Los datos podran cotejarse con registros del INV, "
        "declaraciones de cosecha y comprobantes de venta ante la Subsecretaria de Trabajo (Ley 8114). "
        "Asesoramiento: SUTCVyF 0261-4239650 | Subsec. Trabajo San Martin 0263-4420100 | RENATEA 0800-222-7638",
        ParagraphStyle("NL", fontSize=7.5, fontName="Helvetica", textColor=ROJO, spaceAfter=6)))
    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    el.append(Paragraph("Registro personal del contratista | Ley 23.154 - Art. 16 | Mendoza", s_footer))

    doc.build(el)
    buffer.seek(0)
    return buffer.getvalue()


def generar_formulario_cosecha_pdf(datos: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io as io_mod

    VERDE = colors.HexColor("#1a5e1a")
    VERDE_CLARO = colors.HexColor("#e8f5e9")
    GRIS = colors.HexColor("#555555")
    ROJO = colors.HexColor("#c0392b")

    buffer = io_mod.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm)

    PAGE_W = A4[0] - 3*cm

    s_titulo = ParagraphStyle("T", fontSize=14, fontName="Helvetica-Bold", textColor=VERDE, alignment=TA_CENTER, spaceAfter=4)
    s_sub = ParagraphStyle("S", fontSize=10, fontName="Helvetica", textColor=GRIS, alignment=TA_CENTER, spaceAfter=8)
    s_seccion = ParagraphStyle("SEC", fontSize=11, fontName="Helvetica-Bold", textColor=VERDE, spaceAfter=6, spaceBefore=12)
    s_normal = ParagraphStyle("N", fontSize=9, fontName="Helvetica", spaceAfter=4)
    s_bold = ParagraphStyle("B", fontSize=9, fontName="Helvetica-Bold", spaceAfter=4)
    s_footer = ParagraphStyle("F", fontSize=7, fontName="Helvetica", textColor=colors.grey, alignment=TA_CENTER)
    s_nota = ParagraphStyle("NOTA", fontSize=8, fontName="Helvetica", textColor=GRIS, spaceAfter=4)

    nc = datos.get("nombre_contratista", "_________________________")
    dni = datos.get("dni", "_____________")
    ne = datos.get("nombre_empleador", "_________________________")
    cuit = datos.get("cuit", "_____________")
    ubic = datos.get("ubicacion", "_________________________")
    inv = datos.get("inv", "_______")
    hect = datos.get("hectareas", "____")
    porc = datos.get("porcentaje", "18")
    per = datos.get("periodo", "2026")

    def campo(label, valor=""):
        linea = valor if valor else "_" * 35
        return Paragraph(f"<b>{label}:</b>  {linea}", s_normal)

    def seccion_elem(texto):
        return [Spacer(1, 0.3*cm), Paragraph(texto, s_seccion),
                HRFlowable(width="100%", thickness=1.5, color=VERDE), Spacer(1, 0.2*cm)]

    def ch(texto):
        return Paragraph(f"<b>{texto}</b>", ParagraphStyle("CH", fontSize=7, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=TA_CENTER, leading=9))

    def cd(texto="", bold=False, align=TA_CENTER):
        return Paragraph(texto, ParagraphStyle("CD", fontSize=7.5,
            fontName="Helvetica-Bold" if bold else "Helvetica", alignment=align))

    col_w = [0.5*cm, 1.6*cm, 3.0*cm, 1.7*cm, 1.5*cm, 1.2*cm, 1.6*cm, 1.7*cm, 1.5*cm]
    hdrs = ["N°\n(o X)", "Fecha", "Bodega Destino", "Patente\nCamion", "N° Ticket\nPesada",
            "Total\nTachos", "Kg\nEntregados", "Precio\nx Kg $", "Total $"]

    def tabla_cam(desde, hasta):
        td = [[ch(h) for h in hdrs]]
        for i in range(desde, hasta+1):
            td.append([cd(str(i))] + [cd("") for _ in range(8)])
        td.append([cd(f"SUBTOTAL {desde}-{hasta}", bold=True),
            cd(""), cd(""), cd(""), cd(""), cd(""), cd(""), cd(""), cd("$", bold=True)])
        tc = Table(td, colWidths=col_w, repeatRows=1)
        tc.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),VERDE),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTSIZE",(0,0),(-1,-1),7.5),
            ("ROWBACKGROUNDS",(0,1),(-1,-2),[VERDE_CLARO,colors.white]),
            ("BACKGROUND",(0,-1),(-1,-1),VERDE_CLARO),
            ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
            ("GRID",(0,0),(-1,-1),0.3,colors.grey),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
            ("SPAN",(0,-1),(4,-1)),
        ]))
        return tc

    def enc():
        return [Paragraph("FORMULARIO DE RELEVAMIENTO DE COSECHA", s_titulo),
                Paragraph(f"Ley 23.154 - Mendoza - Temporada {per}", s_sub),
                Paragraph("ATENCION: Solo para recopilacion de datos. No implica conformidad ni renuncia a derechos.",
                    ParagraphStyle("AVE", fontSize=8, fontName="Helvetica-Bold", textColor=ROJO, alignment=TA_CENTER, spaceAfter=6)),
                HRFlowable(width="100%", thickness=2, color=VERDE), Spacer(1, 0.3*cm)]

    el = []
    el += enc()
    el += seccion_elem("1. DATOS IDENTIFICATORIOS")
    dt = [
        [Paragraph("<b>EMPLEADOR</b>", s_bold), Paragraph("<b>CONTRATISTA</b>", s_bold)],
        [campo("Nombre", ne), campo("Nombre", nc)],
        [campo("CUIT", cuit), campo("DNI", dni)],
        [campo("Domicilio"), campo("Domicilio")],
    ]
    t = Table(dt, colWidths=[PAGE_W/2, PAGE_W/2])
    t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),
        ("BACKGROUND",(0,0),(-1,0),VERDE_CLARO),("PADDING",(0,0),(-1,-1),5)]))
    el.append(t)
    el.append(Spacer(1, 0.2*cm))
    df = [
        [Paragraph("<b>DATOS DE LA FINCA</b>", s_bold), "", ""],
        [campo("Ubicacion", ubic), campo("N° INV", inv), campo("Hectareas", hect)],
        [campo("Porcentaje", f"{porc}% (Art. 16 Ley 23.154)"), campo("Periodo", per), ""],
    ]
    tf = Table(df, colWidths=[PAGE_W*0.5, PAGE_W*0.25, PAGE_W*0.25])
    tf.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),
        ("BACKGROUND",(0,0),(-1,0),VERDE_CLARO),("SPAN",(0,0),(-1,0)),("PADDING",(0,0),(-1,-1),5)]))
    el.append(tf)
    el += seccion_elem("2. CAMIONADAS - BLOQUE 1 (Viajes 1 al 15)")
    el.append(Paragraph("Marcar con X si la fila no se utilizo.", s_nota))
    el.append(tabla_cam(1, 15))
    el.append(PageBreak())
    el += enc()
    el += seccion_elem("2. CAMIONADAS - BLOQUE 2 (Viajes 16 al 35)")
    el.append(Paragraph("Marcar con X si la fila no se utilizo.", s_nota))
    el.append(tabla_cam(16, 35))
    el.append(Spacer(1, 0.3*cm))
    el += seccion_elem("3. CALCULO DEL PORCENTAJE DE COSECHA")
    liq = [
        [Paragraph("<b>CONCEPTO</b>", ParagraphStyle("LH", fontSize=9, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_CENTER)),
         Paragraph("<b>IMPORTE ($)</b>", ParagraphStyle("LH2", fontSize=9, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_CENTER))],
        [cd("Total kilos cosechados (segun declaracion INV):", align=TA_LEFT), cd("")],
        [cd("Precio promedio por kilo ($):", align=TA_LEFT), cd("")],
        [cd("Total produccion en pesos ($):", align=TA_LEFT), cd("")],
        [Paragraph(f"<b>{porc}% correspondiente al contratista (Art. 16 Ley 23.154):</b>",
                   ParagraphStyle("LV", fontSize=9.5, fontName="Helvetica-Bold", textColor=VERDE)),
         Paragraph("<b>$</b>", ParagraphStyle("LV2", fontSize=9.5, fontName="Helvetica-Bold", textColor=VERDE, alignment=TA_CENTER))],
        [cd("(-) Gastos cosecha y acarreo:", align=TA_LEFT), cd("")],
        [Paragraph("<b>TOTAL NETO A PAGAR AL CONTRATISTA:</b>",
                   ParagraphStyle("LT", fontSize=10, fontName="Helvetica-Bold", textColor=colors.white)),
         Paragraph("<b>$</b>", ParagraphStyle("LT2", fontSize=10, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_CENTER))],
    ]
    tl = Table(liq, colWidths=[PAGE_W*0.72, PAGE_W*0.28])
    tl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),VERDE),("BACKGROUND",(0,6),(-1,6),VERDE),
        ("BACKGROUND",(0,4),(-1,4),VERDE_CLARO),("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),6),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8)]))
    el.append(tl)
    el += seccion_elem("4. OBSERVACIONES")
    el.append(Table([[" "],[" "],[" "]], colWidths=[PAGE_W], rowHeights=[0.8*cm,0.8*cm,0.8*cm],
        style=[("GRID",(0,0),(-1,-1),0.5,colors.lightgrey)]))
    el.append(Spacer(1, 0.3*cm))
    el.append(HRFlowable(width="100%", thickness=1, color=ROJO))
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph(
        "IMPORTANTE: Formulario de recopilacion de datos. Puede cotejarse con declaracion INV y registros de bodegas. "
        "El contratista se reserva derecho de reclamo ante Subsecretaria Trabajo (Ley 8114) e INV. "
        "Asesoramiento: SUTCVyF 0261-4239650 | Subsec. Trabajo SM 0263-4420100 | RENATEA 0800-222-7638",
        ParagraphStyle("AV", fontSize=7.5, fontName="Helvetica", textColor=ROJO, spaceAfter=8)))
    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    el.append(Paragraph("Formulario para Contratistas de Vinas y Frutales | Ley 23.154 | Mendoza", s_footer))

    doc.build(el)
    buffer.seek(0)
    return buffer.getvalue()

def main():
    app = Application.builder().token(TOKEN_TELEGRAM).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("nueva", nueva_consulta))
    app.add_handler(CommandHandler("fin", comando_fin))
    app.add_handler(CommandHandler("informe", iniciar_formulario_informe))
    app.add_handler(CommandHandler("terminos", terminos_cmd))
    app.add_handler(CommandHandler("usuarios", usuarios_cmd))  # Solo admin
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, procesar_voz))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, procesar_video))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, procesar_archivo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_texto))

    print("🚀 Bot Abogado/Contador v13 - Audio, Video, Experto en Vid!")
    app.run_polling()

if __name__ == '__main__':
    main()
