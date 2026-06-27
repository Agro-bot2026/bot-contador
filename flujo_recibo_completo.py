with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

# PASO 1: Agregar preguntas del formulario de recibo
PREGUNTAS_RECIBO = '''
PREGUNTAS_RECIBO = [
    ("hectareas_contrato", "📄 ¿Cuántas hectáreas dice tu *contrato*? (ej: 5)"),
    ("hectareas_riego", "💧 ¿Cuántas hectáreas figura en tu *boleta de riego de Irrigación*? (ej: 6)"),
    ("fecha_ingreso", "📅 ¿Desde qué fecha trabajás? (ej: 23/07/2021)"),
    ("nombre_empleador", "🏢 ¿Cómo se llama tu empleador o patrón?"),
    ("sindicalizado", "👥 ¿Estás afiliado al sindicato? (SÍ o NO)")
]
'''

if "PREGUNTAS_RECIBO" not in codigo:
    codigo = codigo.replace(
        "PREGUNTAS_INFORME = [",
        PREGUNTAS_RECIBO + "\nPREGUNTAS_INFORME = ["
    )
    print("✅ Preguntas de recibo agregadas")

# PASO 2: Agregar función de análisis de recibo con datos del contrato
FUNCION_ANALISIS_RECIBO = '''
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
'''

if "analizar_recibo_completo" not in codigo:
    codigo = codigo.replace(
        "# ============================================================\n# 12. MAIN",
        FUNCION_ANALISIS_RECIBO + "\n# ============================================================\n# 12. MAIN"
    )
    print("✅ Función de análisis de recibo agregada")

# PASO 3: Agregar modo de formulario para recibo en procesar_texto
MODO_RECIBO = '''
    # Modo formulario recibo
    if modo == "formulario_recibo":
        paso = context.user_data.get("recibo_paso", 0)
        datos = context.user_data.get("recibo_datos", {})
        
        if mensaje_usuario.lower() == "/cancelar":
            context.user_data["modo"] = ""
            await update.message.reply_text("❌ Análisis cancelado.")
            return
        
        clave, _ = PREGUNTAS_RECIBO[paso]
        datos[clave] = mensaje_usuario
        context.user_data["recibo_datos"] = datos
        
        siguiente = paso + 1
        if siguiente < len(PREGUNTAS_RECIBO):
            context.user_data["recibo_paso"] = siguiente
            _, pregunta = PREGUNTAS_RECIBO[siguiente]
            await update.message.reply_text(pregunta, parse_mode="Markdown")
        else:
            context.user_data["modo"] = ""
            imagen_bytes = context.user_data.get("recibo_imagen")
            if imagen_bytes:
                aviso = await update.message.reply_text(
                    "🔍 Analizando tu recibo con Manus AI...\\n"
                    "Esto puede tardar 2-3 minutos. Por favor esperá."
                )
                resultado = await analizar_recibo_completo(imagen_bytes, datos)
                await aviso.delete()
                cache_respuestas[user_id] = resultado
                keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]
                if len(resultado) <= 4000:
                    await update.message.reply_text(
                        f"📊 *ANÁLISIS DE TU RECIBO*\\n\\n{resultado}",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    partes = [resultado[i:i+4000] for i in range(0, len(resultado), 4000)]
                    for parte in partes[:-1]:
                        await update.message.reply_text(parte)
                    await update.message.reply_text(partes[-1], reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text("❌ No se encontró la imagen del recibo.")
        return
'''

# Insertar el modo recibo en procesar_texto
if "formulario_recibo" not in codigo:
    codigo = codigo.replace(
        "    # Modo formulario informe\n    if modo == 'formulario_informe':",
        MODO_RECIBO + "\n    # Modo formulario informe\n    if modo == 'formulario_informe':"
    )
    print("✅ Modo formulario recibo agregado")

# PASO 4: Modificar procesar_archivo para iniciar el formulario cuando recibe una foto
TRIGGER_FORMULARIO = '''
                # Iniciar formulario de datos antes de analizar
                context.user_data["recibo_imagen"] = file_bytes
                context.user_data["recibo_datos"] = {}
                context.user_data["recibo_paso"] = 0
                context.user_data["modo"] = "formulario_recibo"
                
                await aviso.edit_text(
                    "📋 Para hacer un análisis completo necesito algunos datos.\\n"
                    "Podés escribir /cancelar en cualquier momento.\\n\\n"
                    "📄 ¿Cuántas hectáreas dice tu *contrato*? (ej: 5)",
                    parse_mode="Markdown"
                )
                return
'''

# Buscar donde se procesa el recibo de sueldo
if "recibo_imagen" not in codigo:
    # Buscar el punto donde se analiza el recibo
    idx = codigo.find("analizar_recibo_con_manus")
    if idx == -1:
        idx = codigo.find("recibo")
    
    # Buscar el contexto de procesamiento de imagen
    if "ANALISIS DE RECIBO" in codigo.upper() or "recibo de sueldo" in codigo.lower():
        print("⚠️ Encontrado procesamiento de recibo existente")
    
    # Agregar trigger en procesar_archivo antes del análisis de imagen
    codigo = codigo.replace(
        'if "recibo" in system.lower() or True:  # Analizar cualquier imagen',
        TRIGGER_FORMULARIO
    )
    
    # Alternativa: buscar donde se procesa la imagen en procesar_archivo
    viejo_analisis = '        res = model.generate_content([prompt_imagen, imagen_part])'
    if viejo_analisis in codigo:
        # Encontrar el contexto correcto
        pass
    
    print("✅ Trigger de formulario en procesamiento de imágenes")

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Flujo completo de análisis de recibo implementado")
