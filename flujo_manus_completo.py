with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

# PASO 1: Nuevas preguntas para recolectar documentos
PREGUNTAS_DOCUMENTOS = '''PREGUNTAS_RECIBO = [
    ("listo_contrato", "📄 Vamos a analizar tus documentos uno por uno para hacer un informe completo.\\n\\nPrimero enviame una *foto del contrato (Formulario 001/12)*\\nSi no lo tenés escribí NO TENGO."),
    ("listo_declaracion", "📋 Ahora enviame una *foto de la Declaración Jurada (Formulario 002/12)*\\nSi no la tenés escribí NO TENGO."),
    ("listo_recibo", "💰 Ahora enviame una *foto del recibo de sueldo más reciente*."),
    ("listo_riego", "💧 Ahora enviame una *foto de la boleta de riego de Irrigación*\\nSi no la tenés escribí NO TENGO."),
    ("sindicalizado", "👥 Por último: ¿Estás afiliado al sindicato? (SÍ o NO)")
]'''

if "PREGUNTAS_RECIBO = [" in codigo:
    inicio = codigo.find("PREGUNTAS_RECIBO = [")
    fin = codigo.find("]", inicio) + 1
    codigo = codigo[:inicio] + PREGUNTAS_DOCUMENTOS + codigo[fin:]
    print("✅ Preguntas de documentos actualizadas")

# PASO 2: Función para extraer texto de imagen con Gemini Vision
FUNCION_EXTRAER_TEXTO = '''
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
'''

if "extraer_texto_documento" not in codigo:
    codigo = codigo.replace(
        "# ============================================================\n# 12. MAIN",
        FUNCION_EXTRAER_TEXTO + "\n# ============================================================\n# 12. MAIN"
    )
    print("✅ Funciones de extracción e informe agregadas")

# PASO 3: Actualizar el modo esperando_recibo para manejar fotos
MODO_DOCS = '''
    # Modo esperando recibo - recolecta documentos uno por uno
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
                "⏳ Analizando todos tus documentos y generando el informe completo...\\n"
                "Esto puede tardar 2-3 minutos. Por favor esperá."
            )
            
            try:
                resultado = await generar_informe_integral(textos, mensaje_usuario)
                await aviso.delete()
                context.user_data['modo'] = ''
                cache_respuestas[user_id] = resultado
                
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
'''

# Reemplazar el modo esperando_recibo existente
if "if modo == 'esperando_recibo':" in codigo:
    inicio = codigo.find("    # Modo esperando recibo - recolecta datos antes de la foto\n    if modo == 'esperando_recibo':")
    if inicio == -1:
        inicio = codigo.find("    if modo == 'esperando_recibo':")
    fin = codigo.find("\n\n    # Modo formulario informe", inicio)
    if fin == -1:
        fin = codigo.find("\n\n    # Modo", inicio + 50)
    if inicio != -1 and fin != -1:
        codigo = codigo[:inicio] + MODO_DOCS + codigo[fin:]
        print("✅ Modo esperando_recibo actualizado")

# PASO 4: Actualizar procesar_archivo para capturar fotos de documentos
CAPTURA_FOTOS = '''
    # Capturar fotos de documentos cuando está en modo esperando_recibo
    modo_actual = context.user_data.get('modo', '')
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
                        f"✅ {tipo_doc.capitalize()} leído correctamente.\\n\\n{pregunta}",
                        parse_mode="Markdown"
                    )
                else:
                    context.user_data['modo'] = ''
            except Exception as e:
                await aviso.edit_text(f"❌ Error leyendo el documento: {str(e)[:100]}")
        return
'''

if "Capturar fotos de documentos cuando está en modo esperando_recibo" not in codigo:
    codigo = codigo.replace(
        "async def procesar_archivo(update: Update, context: ContextTypes.DEFAULT_TYPE):\n    user_id = update.message.from_user.id\n",
        "async def procesar_archivo(update: Update, context: ContextTypes.DEFAULT_TYPE):\n    user_id = update.message.from_user.id\n" + CAPTURA_FOTOS
    )
    print("✅ Captura de fotos en procesar_archivo agregada")

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Todo completado")
