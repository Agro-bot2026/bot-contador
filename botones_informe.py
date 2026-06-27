with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

# Agregar botón de informe al teclado de respuestas
viejo_keyboard = '''        keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]'''

nuevo_keyboard = '''        keyboard = [
            [InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]
        ]
        if len(respuesta) > 200:
            keyboard.append([
                InlineKeyboardButton("📋 Generar Informe", callback_data=f"informe_{user_id}"),
                InlineKeyboardButton("❌ No por ahora", callback_data="cerrar_informe")
            ])'''

viejo_keyboard_2partes = '''        if len(respuesta) > 4500:
            keyboard = [
                [InlineKeyboardButton("🔊 Escuchar parte 1", callback_data=f"audio_{user_id}_1")],
                [InlineKeyboardButton("🔊 Escuchar parte 2", callback_data=f"audio_{user_id}_2")]
            ]
        else:
            keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]'''

nuevo_keyboard_2partes = '''        if len(respuesta) > 4500:
            keyboard = [
                [InlineKeyboardButton("🔊 Escuchar parte 1", callback_data=f"audio_{user_id}_1")],
                [InlineKeyboardButton("🔊 Escuchar parte 2", callback_data=f"audio_{user_id}_2")]
            ]
        else:
            keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]
        keyboard.append([
            InlineKeyboardButton("📋 Generar Informe", callback_data=f"informe_{user_id}"),
            InlineKeyboardButton("❌ No por ahora", callback_data="cerrar_informe")
        ])'''

if viejo_keyboard_2partes in codigo:
    codigo = codigo.replace(viejo_keyboard_2partes, nuevo_keyboard_2partes)
    print("✅ Botones agregados al teclado de 2 partes")
elif viejo_keyboard in codigo:
    codigo = codigo.replace(viejo_keyboard, nuevo_keyboard)
    print("✅ Botones agregados al teclado simple")

# Agregar handler para el botón de informe
HANDLER_INFORME = '''
    if data.startswith("informe_"):
        if not es_autorizado(user_id):
            await query.answer("No tenés acceso.")
            return
        await query.answer()
        historial = obtener_historial(user_id)
        if not historial:
            await query.message.reply_text("⚠️ No hay conversación para generar el informe.")
            return
        context.user_data["formulario_informe"] = {}
        context.user_data["formulario_paso"] = 0
        context.user_data["modo"] = "formulario_informe"
        await query.message.reply_text(
            "📋 *Vamos a completar el informe de irregularidades.*\\n"
            "Te voy a hacer algunas preguntas para personalizar el documento.\\n\\n"
            "Podés escribir /cancelar en cualquier momento para salir.",
            parse_mode="Markdown"
        )
        _, pregunta = PREGUNTAS_INFORME[0]
        await query.message.reply_text(pregunta)
        return

    if data == "cerrar_informe":
        await query.answer("Podés pedirlo cuando quieras con /informe")
        await query.message.edit_reply_markup(reply_markup=None)
        return
'''

if 'data.startswith("informe_")' not in codigo:
    codigo = codigo.replace(
        '    if data.startswith("audio_"):',
        HANDLER_INFORME + '    if data.startswith("audio_"):'
    )
    print("✅ Handler de botón informe agregado")

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Botones de informe implementados")
print("Ejecutá: pm2 restart bot-contador")
