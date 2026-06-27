with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

viejo = '''    cache_respuestas[user_id] = respuesta

        keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]'''

nuevo = '''    cache_respuestas[user_id] = respuesta

        # Dividir en dos partes si la respuesta es larga
        if len(respuesta) > 4500:
            keyboard = [
                [InlineKeyboardButton("🔊 Escuchar parte 1", callback_data=f"audio_{user_id}_1")],
                [InlineKeyboardButton("🔊 Escuchar parte 2", callback_data=f"audio_{user_id}_2")]
            ]
        else:
            keyboard = [[InlineKeyboardButton("🔊 Escuchar respuesta", callback_data=f"audio_{user_id}")]]'''

codigo = codigo.replace(viejo, nuevo)

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Audio en dos partes configurado")
