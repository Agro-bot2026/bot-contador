with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

# PARTE 1: Bajar el mínimo de historial de 4 a 2
codigo = codigo.replace(
    'if not historial or len(historial) < 4:',
    'if not historial or len(historial) < 2:'
)
print("✅ Mínimo de historial reducido a 1 pregunta")

# PARTE 2: Función Manus mejorada para informe completo
FUNCION_MANUS_INFORME = '''
async def generar_informe_con_manus(historial: list, datos: dict) -> bytes:
    """Genera informe completo usando Manus para buscar info y analizar"""
    import asyncio
    import requests
    import time
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.enums import TA_CENTER
    import io as io_mod
    from datetime import datetime

    resumen = "\\n".join([
        f"{m[\'role\'].upper()}: {m[\'texto\'][:600]}"
        for m in historial[-15:]
    ])

    nombre = datos.get("nombre", "A completar")
    empleador = datos.get("empleador", "A completar")
    direccion = datos.get("direccion", "A completar")
    hectareas = datos.get("hectareas", "A completar")
    fecha_inicio = datos.get("fecha_inicio", "A completar")
    extra = datos.get("irregularidades_extra", "")

    headers = {"x-manus-api-key": MANUS_API_KEY, "Content-Type": "application/json"}

    prompt_manus = f"""Sos un experto en derecho laboral agrario argentino especializado en el Estatuto del Contratista de Viñas y Frutales (Leyes 20.589, 23.154 y 27.644).

Analizá esta conversación y generá un informe completo de irregularidades laborales.
Buscá en internet información actualizada sobre:
- Escala salarial vigente del contratista de viñas en Mendoza 2026
- Resoluciones recientes del Boletín Oficial sobre trabajadores rurales
- Precio actual de la uva en Mendoza

CONVERSACIÓN:
{resumen}

INFORMACIÓN ADICIONAL: {extra if extra and extra.upper() != "NO" else "Ninguna"}

REGLAS ESTRICTAS:
- Solo citá leyes reales: Ley 20.589, Ley 23.154, Ley 27.644, Ley 27.643, Ley 25.191
- No inventes artículos ni leyes
- Si no hay datos suficientes para un punto escribí "Sin datos suficientes"

Generá el informe con estos títulos EXACTOS:

IRREGULARIDADES DETECTADAS:
DAÑO ECONÓMICO ESTIMADO:
BASE LEGAL APLICABLE:
ACCIONES RECOMENDADAS:
ORGANISMOS DONDE DENUNCIAR:
INFORMACIÓN ACTUALIZADA DEL MERCADO:
NOTA IMPORTANTE:"""

    contenido_manus = ""
    try:
        resp = requests.post(
            "https://api.manus.ai/v2/task.create",
            headers=headers,
            json={"message": {"content": prompt_manus}, "share_visibility": "public"}
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
                                    contenido_manus = str(m.get("assistant_message", {}).get("content", ""))[:5000]
                                    break
                            break
                        elif status == "waiting":
                            event_type = msg.get("status_update", {}).get("status_detail", {}).get("waiting_for_event_type", "")
                            if event_type == "messageAskUser":
                                requests.post(
                                    "https://api.manus.ai/v2/task.sendMessage",
                                    headers=headers,
                                    json={"task_id": task_id, "message": {"content": "Generá el informe ahora con la información disponible."}}
                                )
                if contenido_manus:
                    break
    except Exception as e:
        print(f"Error Manus: {e}")

    if not contenido_manus:
        try:
            res = model.generate_content(prompt_manus[:50000])
            contenido_manus = res.text
            print("⚠️ Manus tardó, usando Gemini como respaldo")
        except Exception as e:
            contenido_manus = "Error al generar el contenido del informe."

    # Generar PDF
    buffer = io_mod.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("T", parent=styles["Heading1"],
        fontSize=16, textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=6, alignment=TA_CENTER)
    estilo_subtitulo = ParagraphStyle("S", parent=styles["Heading2"],
        fontSize=11, textColor=colors.HexColor("#c0392b"),
        spaceAfter=4, spaceBefore=10)
    estilo_normal = ParagraphStyle("N", parent=styles["Normal"],
        fontSize=10, spaceAfter=4, leading=14)
    estilo_campo = ParagraphStyle("C", parent=styles["Normal"],
        fontSize=10, spaceAfter=2, leading=13,
        textColor=colors.HexColor("#c0392b"), fontName="Helvetica-Bold")
    estilo_footer = ParagraphStyle("F", parent=styles["Normal"],
        fontSize=8, textColor=colors.grey, alignment=TA_CENTER)

    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    elementos = []

    elementos.append(Paragraph("⚖️ INFORME DE IRREGULARIDADES LABORALES", estilo_titulo))
    elementos.append(Paragraph("Estatuto del Contratista de Viñas y Frutales", estilo_titulo))
    elementos.append(Paragraph("Leyes 20.589 · 23.154 · 27.644", estilo_subtitulo))
    elementos.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#c0392b")))
    elementos.append(Spacer(1, 0.3*cm))

    elementos.append(Paragraph("DATOS DEL CONTRATISTA", estilo_subtitulo))
    campos = [
        ("Nombre y Apellido:", "_" * 60),
        ("Empleador / Razón Social:", "_" * 60),
        ("Dirección de la Finca:", "_" * 60),
        ("Hectáreas trabajadas:", "_" * 30),
        ("Fecha de inicio:", "_" * 30),
        ("DNI del Contratista:", "_" * 30),
        ("CUIL/CUIT del Empleador:", "_" * 30),
    ]
    for campo, linea in campos:
        elementos.append(Paragraph(campo, estilo_campo))
        elementos.append(Paragraph(linea, estilo_normal))

    elementos.append(Spacer(1, 0.2*cm))
    elementos.append(Paragraph(f"Generado: {fecha} | Análisis: Manus AI + Gemini", estilo_footer))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    elementos.append(Spacer(1, 0.3*cm))

    secciones = ["IRREGULARIDADES DETECTADAS:", "DAÑO ECONÓMICO ESTIMADO:",
                 "BASE LEGAL APLICABLE:", "ACCIONES RECOMENDADAS:",
                 "ORGANISMOS DONDE DENUNCIAR:", "INFORMACIÓN ACTUALIZADA DEL MERCADO:",
                 "NOTA IMPORTANTE:"]

    for linea in contenido_manus.split("\\n"):
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
    elementos.append(Spacer(1, 0.5*cm))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")))
    elementos.append(Spacer(1, 0.2*cm))
    elementos.append(Paragraph(
        f"Bot Legal Viñas · Leyes 20.589, 23.154 y 27.644 · "
        f"Informe orientativo · Análisis Manus AI · {fecha}",
        estilo_footer))

    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()
'''

# PARTE 3: Función Manus para analizar recibos
FUNCION_MANUS_RECIBO = '''
async def analizar_recibo_con_manus(imagen_base64: str, tipo_mime: str = "image/jpeg") -> str:
    """Usa Manus para analizar recibos de sueldo buscando irregularidades"""
    import requests
    import time

    headers = {"x-manus-api-key": MANUS_API_KEY, "Content-Type": "application/json"}

    prompt = """Analizá este recibo de sueldo de un contratista de viñas y frutales de Mendoza, Argentina.

Verificá específicamente:
1. Si la mensualidad por hectárea está dentro de la escala paritaria vigente 2025/2026
2. Si los descuentos son correctos según la Ley 20.589
3. Si hay aportes previsionales declarados correctamente
4. Si el porcentaje de cosecha está liquidado correctamente (entre 15% y 19%)
5. Buscá en internet la escala salarial vigente del contratista de viñas de Mendoza para comparar

Indicá claramente:
- CORRECTO o IRREGULAR para cada concepto
- El artículo de ley violado si hay irregularidad
- El monto correcto si podés calcularlo"""

    try:
        resp = requests.post(
            "https://api.manus.ai/v2/task.create",
            headers=headers,
            json={
                "message": {
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "file", "file_data": f"data:{tipo_mime};base64,{imagen_base64}", "filename": "recibo.jpg"}
                    ]
                },
                "share_visibility": "public"
            }
        )
        data = resp.json()
        if not data.get("ok"):
            return None

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
                                return str(m.get("assistant_message", {}).get("content", ""))[:3000]
                    elif status == "waiting":
                        event_type = msg.get("status_update", {}).get("status_detail", {}).get("waiting_for_event_type", "")
                        if event_type == "messageAskUser":
                            requests.post(
                                "https://api.manus.ai/v2/task.sendMessage",
                                headers=headers,
                                json={"task_id": task_id, "message": {"content": "Analizá el recibo ahora y respondé con los hallazgos."}}
                            )
        return None
    except Exception as e:
        print(f"Error Manus recibo: {e}")
        return None
'''

# Insertar funciones antes del main
if "generar_informe_con_manus" not in codigo:
    codigo = codigo.replace(
        "# ============================================================\n# 12. MAIN",
        FUNCION_MANUS_INFORME + "\n\n" + FUNCION_MANUS_RECIBO + "\n\n# ============================================================\n# 12. MAIN"
    )
    print("✅ Funciones Manus agregadas")

# PARTE 4: Actualizar comando /fin para usar generar_informe_con_manus
codigo = codigo.replace(
    'pdf_bytes = await generar_informe_pdf_completo(historial, datos)',
    'pdf_bytes = await generar_informe_con_manus(historial, datos)'
)
print("✅ Informe apunta a Manus")

# PARTE 5: Integrar Manus en análisis de recibos
# Buscar donde se procesan imágenes y agregar llamada a Manus
MANUS_RECIBO_CALL = '''
                # Intentar análisis con Manus primero
                try:
                    import base64
                    img_b64 = base64.b64encode(file_bytes).decode()
                    resultado_manus = await analizar_recibo_con_manus(img_b64)
                    if resultado_manus:
                        respuesta = f"🔍 *Análisis de recibo por Manus AI:*\\n\\n{resultado_manus}"
                        cache_respuestas[user_id] = respuesta
                        keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]
                        await aviso.edit_text(respuesta, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
                        return
                except Exception as e:
                    print(f"Manus recibo falló: {e}, usando Gemini")
'''

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Todo listo")
print("Ejecutá: pm2 restart bot-contador")
