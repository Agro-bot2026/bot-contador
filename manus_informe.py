import requests
import time
import json

with open("/root/BotContador/manus_key.json", "r") as f:
    config = json.load(f)
MANUS_API_KEY = config["MANUS_API_KEY"]

def buscar_info_actualizada_manus() -> str:
    """Usa Manus para buscar información actualizada sin datos sensibles"""
    headers = {"x-manus-api-key": MANUS_API_KEY, "Content-Type": "application/json"}
    
    prompt = """Buscá en internet la siguiente información actualizada para Argentina 2026:
1. Escala salarial vigente del contratista de viñas y frutales de Mendoza
2. Resoluciones recientes sobre el Estatuto del Contratista (Ley 20.589/23.154)
3. Precio actual de la uva en Mendoza (por quintal o kg)
4. Novedades del Boletín Oficial sobre trabajadores rurales 2026
Respondé solo con los datos encontrados, sin inventar."""

    try:
        resp = requests.post(
            "https://api.manus.ai/v2/task.create",
            headers=headers,
            json={"message": {"content": prompt}, "share_visibility": "public"}
        )
        data = resp.json()
        if not data.get("ok"):
            return "No se pudo obtener información actualizada de Manus."
        
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
                                contenido = m.get("assistant_message", {}).get("content", "")
                                return str(contenido)[:3000]
                    elif status == "waiting":
                        event_type = msg.get("status_update", {}).get("status_detail", {}).get("waiting_for_event_type", "")
                        if event_type == "messageAskUser":
                            event_id = msg.get("status_update", {}).get("status_detail", {}).get("waiting_for_event_id", "")
                            requests.post(
                                "https://api.manus.ai/v2/task.sendMessage",
                                headers=headers,
                                json={"task_id": task_id, "message": {"content": "Buscá esa información ahora y respondé con los datos encontrados."}}
                            )
        return "Manus tardó demasiado."
    except Exception as e:
        return f"Error: {str(e)}"

with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

# Agregar import y función al bot
if "buscar_info_actualizada_manus" not in codigo:
    codigo = codigo.replace(
        "import requests\nimport time\nimport json",
        "import requests\nimport time\nimport json\nfrom manus_informe import buscar_info_actualizada_manus"
    )
    print("✅ Import de Manus agregado")

# Actualizar función generar_informe_pdf_completo para incluir info de Manus
NUEVA_FUNCION = '''async def generar_informe_pdf_completo(historial: list, datos: dict) -> bytes:
    """Genera PDF con datos del formulario, análisis de Gemini e info actualizada de Manus"""
    import asyncio
    
    resumen_historial = "\\n".join([
        f"{m[\'role\'].upper()}: {m[\'texto\'][:600]}"
        for m in historial[-15:]
    ])
    
    nombre = datos.get("nombre", "No especificado")
    empleador = datos.get("empleador", "No especificado")
    direccion = datos.get("direccion", "No especificada")
    hectareas = datos.get("hectareas", "No especificadas")
    fecha_inicio = datos.get("fecha_inicio", "No especificada")
    extra = datos.get("extra", datos.get("irregularidades_extra", ""))

    # Buscar info actualizada con Manus en background
    try:
        info_manus = await asyncio.to_thread(buscar_info_actualizada_manus)
    except Exception:
        info_manus = "Información actualizada no disponible."

    prompt = f"""Analizá esta conversación y generá un informe estructurado de irregularidades laborales.

REGLAS ESTRICTAS:
- Solo citá leyes que existen: Ley 20.589, Ley 23.154, Ley 27.644, Ley 27.643, Ley 25.191
- NUNCA inventes artículos ni leyes
- Si no hay suficiente información para un punto, escribí "Sin datos suficientes"
- No inventes irregularidades que no surjan de la conversación
- La ley correcta es 20.589 NO 20.520

INFORMACIÓN ACTUALIZADA (obtenida de internet):
{info_manus}

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
    from reportlab.lib.enums import TA_CENTER
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
    estilo_campo = ParagraphStyle("Campo", parent=styles["Normal"],
        fontSize=10, spaceAfter=3, leading=13,
        textColor=colors.HexColor("#c0392b"), fontName="Helvetica-Bold")
    estilo_linea = ParagraphStyle("Linea", parent=styles["Normal"],
        fontSize=10, spaceAfter=3, leading=16,
        borderPadding=2)
    estilo_footer = ParagraphStyle("Footer2", parent=styles["Normal"],
        fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
    
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    elementos = []
    
    elementos.append(Paragraph("⚖️ INFORME DE IRREGULARIDADES LABORALES", estilo_titulo))
    elementos.append(Paragraph("Estatuto del Contratista de Viñas y Frutales", estilo_titulo))
    elementos.append(Paragraph("Leyes 20.589 · 23.154 · 27.644", estilo_subtitulo))
    elementos.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#c0392b")))
    elementos.append(Spacer(1, 0.3*cm))
    
    elementos.append(Paragraph("DATOS DEL CONTRATISTA", estilo_subtitulo))
    elementos.append(Paragraph("Nombre y Apellido:", estilo_campo))
    elementos.append(Paragraph("_" * 60, estilo_linea))
    elementos.append(Paragraph("Empleador / Razón Social:", estilo_campo))
    elementos.append(Paragraph("_" * 60, estilo_linea))
    elementos.append(Paragraph("Dirección de la Finca:", estilo_campo))
    elementos.append(Paragraph("_" * 60, estilo_linea))
    elementos.append(Paragraph("Hectáreas trabajadas:", estilo_campo))
    elementos.append(Paragraph("_" * 30, estilo_linea))
    elementos.append(Paragraph("Fecha de inicio de la relación laboral:", estilo_campo))
    elementos.append(Paragraph("_" * 30, estilo_linea))
    elementos.append(Paragraph("DNI del Contratista:", estilo_campo))
    elementos.append(Paragraph("_" * 30, estilo_linea))
    elementos.append(Paragraph("CUIL/CUIT del Empleador:", estilo_campo))
    elementos.append(Paragraph("_" * 30, estilo_linea))
    elementos.append(Spacer(1, 0.3*cm))
    elementos.append(Paragraph(f"Informe generado: {fecha}", estilo_footer))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    elementos.append(Spacer(1, 0.3*cm))
    
    secciones = [
        "DATOS DEL CASO:",
        "IRREGULARIDADES DETECTADAS:",
        "DAÑO ECONÓMICO ESTIMADO:",
        "BASE LEGAL APLICABLE:",
        "ACCIONES RECOMENDADAS:",
        "ORGANISMOS DONDE DENUNCIAR:",
        "NOTA IMPORTANTE:"
    ]
    
    for linea in contenido.split("\\n"):
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
    
    elementos.append(Spacer(1, 0.5*cm))
    elementos.append(Paragraph("FIRMA DEL CONTRATISTA:", estilo_campo))
    elementos.append(Spacer(1, 1.5*cm))
    elementos.append(HRFlowable(width="50%", thickness=1, color=colors.black))
    elementos.append(Paragraph("Aclaración y DNI", estilo_footer))
    elementos.append(Spacer(1, 0.8*cm))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")))
    elementos.append(Spacer(1, 0.2*cm))
    elementos.append(Paragraph(
        "Bot Legal Viñas · Leyes 20.589, 23.154 y 27.644 · "
        "Informe orientativo - No reemplaza asesoramiento profesional matriculado. · "
        f"Información actualizada via Manus AI · {fecha}",
        estilo_footer))
    
    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()
'''

# Reemplazar función existente
if "async def generar_informe_pdf_completo" in codigo:
    inicio = codigo.find("async def generar_informe_pdf_completo")
    fin = codigo.find("\nasync def ", inicio + 1)
    if fin == -1:
        fin = codigo.find("\n# ====", inicio + 1)
    if inicio != -1 and fin != -1:
        codigo = codigo[:inicio] + NUEVA_FUNCION + "\n\n" + codigo[fin:]
        print("✅ Función PDF con Manus actualizada")

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Integración completa de Manus lista")
print("Ejecutá: pm2 restart bot-contador")
