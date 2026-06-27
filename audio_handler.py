with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

viejo = '''    if data.startswith("audio_"):
        user_id_str = data.replace("audio_", "")
        try:
            uid = int(user_id_str)
            texto = cache_respuestas.get(uid, "")
            if not texto:
                await query.answer("No hay respuesta para reproducir.")
                return
            await query.answer()
            msg = await query.message.reply_text("🎙️ Generando audio...")
            audio_bytes = generar_audio(texto)
            await msg.delete()
            await query.message.reply_audio(audio=io.BytesIO(audio_bytes), filename="respuesta.mp3")
        except Exception as e:
            await query.answer(f"Error: {str(e)[:100]}")'''

nuevo = '''    if data.startswith("audio_"):
        partes = data.replace("audio_", "").split("_")
        try:
            uid = int(partes[0])
            parte = int(partes[1]) if len(partes) > 1 else 0
            texto = cache_respuestas.get(uid, "")
            if not texto:
                await query.answer("No hay respuesta para reproducir.")
                return
            await query.answer()
            msg = await query.message.reply_text("🎙️ Generando audio...")
            if parte == 1:
                texto_audio = texto[:4500]
            elif parte == 2:
                texto_audio = texto[4500:]
            else:
                texto_audio = texto
            audio_bytes = generar_audio(texto_audio)
            await msg.delete()
            await query.message.reply_audio(audio=io.BytesIO(audio_bytes), filename="respuesta.mp3")
        except Exception as e:
            await query.answer(f"Error: {str(e)[:100]}")'''

codigo = codigo.replace(viejo, nuevo)

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Handler de audio actualizado")
