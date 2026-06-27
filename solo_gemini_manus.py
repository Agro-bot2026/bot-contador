with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

# Contar cuántas veces aparece claude
count_claude = codigo.count("cliente_claude")
print(f"Referencias a Claude encontradas: {count_claude}")

# Reemplazar todas las llamadas a Claude con Gemini
import re

# Patron para encontrar bloques try con claude
patron = r'try:\s*mensaje = cliente_claude\.messages\.create\(.*?\).*?except Exception as e:.*?res = model\.generate_content\(prompt_completo\)\s*respuesta = res\.text'

matches = re.findall(patron, codigo, re.DOTALL)
print(f"Bloques Claude+Gemini encontrados: {len(matches)}")

for match in matches:
    codigo = codigo.replace(match, 
        'res = model.generate_content(prompt_completo)\n        respuesta = res.text\n        print("✅ Respondió Gemini")'
    )

with open("/root/BotContador/bot.py", "w") as f:
    f.write(codigo)

print("✅ Claude completamente deshabilitado")
