with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

# Agregar el flujo del formulario antes del main
FORMULARIO = '''
# ============================================================
# FORMULARIO DE DATOS PARA INFORME PDF
# ============================================================
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
            "⚠️ No hay conversación para generar el informe.\\n"
            "Primero contame tu situación y después usá /informe."
        )
        return
    
    # Iniciar el formulario
    context.user_data["formulario_informe"] = {}
    context.user_data["formulario_paso"] = 0
    context.user_data["modo"] = "formulario_informe"
    
    await update.message.reply_text(
        "📋 *Vamos a completar el informe de irregularidades.*\\n"
        "Te voy a hacer algunas preguntas para personalizar el documento.\\n\\n"
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
            pdf_bytes = await generar_informe_pdf_completo(historial, datos)
            await aviso.delete()
            
            import io as io_mod
            await update.message.reply_document(
                document=io_mod.BytesIO(pdf_bytes),
                filename=f"Informe_Irregularidades_{nombre.replace(' ', '_')}.pdf",
                caption=(
                    f"📋 *Informe de Irregularidades Laborales*\\n"
                    f"👤 {nombre}\\n"
                    f"📅 Generado el {__import__('datetime').datetime.now().strftime('%d/%m/%Y')}\\n\\n"
                    f"✅ Listo para enviar a un abogado."
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            await aviso.edit_text(f"❌ Error al generar el informe: {str(e)[:200]}")
'''

# Agregar función PDF completa con datos del formulario
FUNCION_PDF_COMPLETA = '''
async def generar_informe_pdf_completo(historial: list, datos: dict) -> bytes:
    """Genera PDF con datos del formulario y análisis de Gemini"""
    
    resumen_historial = "\\n".join([
        f"{m["role"].upper()}: {m["texto"][:600]}"
        for m in historial[-15:]
    ])
    
    nombre = datos.get("nombre", "No especificado")
    empleador = datos.get("empleador", "No especificado")
    direccion = datos.get("direccion", "No especificada")
    hectareas = datos.get("hectareas", "No especificadas")
    fecha_inicio = datos.get("fecha_inicio", "No especificada")
    extra = datos.get("irregularidades_extra", "")
    
    prompt = f"""Analizá esta conversación y generá un informe estructurado de irregularidades laborales.

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
'''

# Insertar antes del main
if "iniciar_formulario_informe" not in codigo:
    codigo = codigo.replace(
        "# ============================================================\n# 12. MAIN",
        FORMULARIO + "\n" + FUNCION_PDF_COMPLETA + "\n# ============================================================\n# 12. MAIN"
    )
    print("✅ Formulario e informe PDF completo agregados")

# Reemplazar comando /informe para que inicie el formulario
codigo = codigo.replace(
    "async def comando_informe(update: Update, context: ContextTypes.DEFAULT_TYPE):",
    "async def comando_informe_viejo_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE):"
)

# Actualizar el handler en el main
codigo = codigo.replace(
    'app.add_handler(CommandHandler("informe", comando_informe))',
    'app.add_handler(CommandHandler("informe", iniciar_formulario_informe))'
)
print("✅ Handler /informe actualizado")

# Agregar procesamiento del formulario en procesar_texto
codigo = codigo.replace(
    "    modo = context.user_data.get('modo', '')\n\n    # Modo calculadora",
    "    modo = context.user_data.get('modo', '')\n\n    # Modo formulario informe\n    if modo == 'formulario_informe':\n        await procesar_formulario_informe(update, context)\n        return\n\n    # Modo calculadora"
)
print("✅ Procesamiento de formulario integrado")

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Todo listo")
print("Ejecutá: pm2 restart bot-contador")
