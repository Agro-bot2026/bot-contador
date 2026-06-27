with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

# PASO 1: Sacar botones de informe de cada respuesta
codigo = codigo.replace(
    '''        keyboard.append([
            InlineKeyboardButton("📋 Generar Informe", callback_data=f"informe_{user_id}"),
            InlineKeyboardButton("❌ No por ahora", callback_data="cerrar_informe")
        ])''',
    ''
)
print("✅ Botones de informe removidos de cada respuesta")

# PASO 2: Agregar comando /fin
COMANDO_FIN = '''
async def comando_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if not es_autorizado(user_id):
        await update.message.reply_text("No tenés acceso.")
        return
    
    historial = obtener_historial(user_id)
    if not historial:
        await update.message.reply_text(
            "No hay consultas registradas todavía.\\n"
            "Haceme tus preguntas primero y después usá /fin."
        )
        return
    
    keyboard = [[
        InlineKeyboardButton("📋 Sí, generar informe", callback_data=f"informe_{user_id}"),
        InlineKeyboardButton("❌ No, gracias", callback_data="cerrar_informe")
    ]]
    
    await update.message.reply_text(
        "✅ *Consulta finalizada.*\\n\\n"
        "Registré toda la información que me contaste.\\n"
        "¿Querés que genere un informe completo de irregularidades "
        "para enviarle a un abogado?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
'''

if "async def comando_fin" not in codigo:
    codigo = codigo.replace(
        "# ============================================================\n# 12. MAIN",
        COMANDO_FIN + "\n# ============================================================\n# 12. MAIN"
    )
    print("✅ Comando /fin agregado")

# PASO 3: Registrar /fin en el main
if 'CommandHandler("fin"' not in codigo:
    codigo = codigo.replace(
        'app.add_handler(CommandHandler("nueva", nueva_consulta))',
        'app.add_handler(CommandHandler("nueva", nueva_consulta))\n    app.add_handler(CommandHandler("fin", comando_fin))'
    )
    print("✅ Comando /fin registrado en el main")

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Flujo de finalizar consulta implementado")
print("Ejecutá: pm2 restart bot-contador")
