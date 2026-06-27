with open("/root/BotContador/bot.py", "r") as f:
    codigo = f.read()

REGLA = (
    '"REGLA JURISPRUDENCIAL - DECRETOS Y AUMENTOS GENERALES: "'
    '"Si el contratista pregunta si le corresponden aumentos por decretos del gobierno, "'
    '"doble indemnizacion (Ley 25.561) u otras leyes generales, responder siempre: "'
    '"Los aumentos salariales por decretos generales NO se aplican al contratista de vinas. "'
    '"El estatuto es autonomo y cerrado (Art. 1 Ley 20.589). "'
    '"Tus remuneraciones SOLO las fija la Comision Paritaria Provincial (Art. 36 Ley 23.154). "'
    '"Fuente: Fallo Cotifane c/ Galarraga, Expte 35.641, 2da Camara Trabajo Mendoza, 31/08/2006. "'
)

if "REGLA JURISPRUDENCIAL" not in codigo:
    codigo = codigo.replace(
        '"Sos un asistente especializado',
        '"REGLA JURISPRUDENCIAL - DECRETOS Y AUMENTOS GENERALES: "\n    '
        '"Los aumentos salariales por decretos generales NO se aplican al contratista de vinas. "\n    '
        '"El estatuto es autonomo y cerrado (Art. 1 Ley 20.589). "\n    '
        '"Las remuneraciones SOLO las fija la Comision Paritaria Provincial (Art. 36 Ley 23.154). "\n    '
        '"Fuente: Fallo Cotifane c/ Galarraga, Expte 35.641, 2da Camara Trabajo Mendoza 2006. "\n    '
        '"Sos un asistente especializado'
    )
    with open("/root/BotContador/bot.py", "w") as f:
        f.write(codigo)
    print("✅ Regla de decretos agregada correctamente")
else:
    print("⚠️ La regla ya existe en el bot")
