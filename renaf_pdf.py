# -*- coding: utf-8 -*-
def generar_renaf_pdf(datos: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.enums import TA_CENTER
    import io

    VERDE = colors.HexColor("#1a5e1a")
    GRIS = colors.HexColor("#555555")
    ROJO = colors.HexColor("#c0392b")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)

    s_titulo = ParagraphStyle("T", fontSize=14, fontName="Helvetica-Bold", textColor=VERDE, alignment=TA_CENTER, spaceAfter=4)
    s_sub = ParagraphStyle("S", fontSize=9, fontName="Helvetica", textColor=GRIS, alignment=TA_CENTER, spaceAfter=8)
    s_seccion = ParagraphStyle("SEC", fontSize=11, fontName="Helvetica-Bold", textColor=VERDE, spaceAfter=6, spaceBefore=10)
    s_normal = ParagraphStyle("N", fontSize=9, fontName="Helvetica", spaceAfter=4, leading=13)
    s_nota = ParagraphStyle("NOTA", fontSize=8, fontName="Helvetica", textColor=GRIS, spaceAfter=4, leading=11)
    s_footer = ParagraphStyle("F", fontSize=7, fontName="Helvetica", textColor=colors.grey, alignment=TA_CENTER)

    def campo(label, valor=""):
        v = valor if valor else "________________"
        return Paragraph(f"<b>{label}:</b>  {v}", s_normal)

    def seccion(texto):
        return [Spacer(1, 0.15*cm), Paragraph(texto, s_seccion),
                HRFlowable(width="100%", thickness=1.2, color=VERDE), Spacer(1, 0.1*cm)]

    def g(k, d=""):
        return datos.get(k, d)

    el = []
    el.append(Paragraph("GUIA DE LLENADO - FORMULARIO ReNAF", s_titulo))
    el.append(Paragraph("Registro Nacional de la Agricultura Familiar - Contratista de Viñas", s_sub))
    el.append(Paragraph("Este documento es una GUIA con tus datos. Copialos al formulario oficial en papel y firmalo.",
        ParagraphStyle("AV", fontSize=8, fontName="Helvetica-Bold", textColor=ROJO, alignment=TA_CENTER, spaceAfter=6)))
    el.append(HRFlowable(width="100%", thickness=2, color=VERDE))

    el += seccion("1. DATOS DE LA PERSONA")
    el.append(campo("Nombre", g("nombre")))
    el.append(campo("Apellido", g("apellido")))
    el.append(campo("Fecha de nacimiento", g("fecha_nac")))
    el.append(campo("DNI", g("dni")))
    el.append(campo("Sexo (segun DNI)", g("sexo")))
    el.append(campo("Genero", g("genero")))
    el.append(campo("Correo electronico", g("email")))
    el.append(campo("Telefono", g("telefono")))
    el.append(campo("Nivel educativo", g("educacion")))
    el.append(campo("Pertenece a pueblo originario", g("pueblo","No")))
    el.append(campo("Participa de organizacion", g("organizacion")))

    el += seccion("2. TRABAJO Y PRODUCCION")
    el.append(campo("Realiza tareas productivas", g("tareas_prod","Si")))
    el.append(campo("Toma decisiones sobre la actividad", g("decisiones","Si")))
    el.append(campo("Comercializa la produccion", g("comercializa","Si")))
    el.append(campo("Trabaja fuera del predio", g("trabajo_fuera","No")))
    el.append(campo("El trabajo en el predio es su actividad principal", g("actividad_principal","Si")))
    el.append(campo("La familia contrata trabajadores", g("contrata","No")))
    el.append(campo("Tiene RENSPA", g("renspa","No")))

    el += seccion("3. UBICACION DEL PREDIO")
    el.append(campo("Provincia", g("provincia","Mendoza")))
    el.append(campo("Departamento", g("departamento")))
    el.append(campo("Localidad", g("localidad")))
    el.append(campo("Calle o Ruta", g("calle")))
    el.append(campo("Numero o Km", g("numero","s/n")))
    el.append(campo("Codigo postal", g("cp")))
    el.append(campo("Latitud", g("latitud")))
    el.append(campo("Longitud", g("longitud")))

    el += seccion("4. INFRAESTRUCTURA Y VIVIENDA")
    el.append(campo("Acceso a agua potable", g("agua","Si")))
    el.append(campo("Energia electrica", g("luz","Si")))
    el.append(campo("Caminos transitables todo el año", g("caminos","Si")))
    el.append(campo("Telefono celular", g("celular","Si")))
    el.append(campo("Acceso a internet", g("internet","Si")))
    el.append(campo("Condicion frente a la vivienda", g("vivienda_condicion")))
    el.append(campo("Distancia vivienda-predio (km)", g("distancia","0")))

    el += seccion("5. ACTIVIDAD AGRICOLA (VID)")
    el.append(campo("Cultivo principal", g("cultivo","Vid")))
    el.append(campo("Superficie (hectareas)", g("superficie_ha")))
    el.append(campo("Utiliza agroquimicos", g("agroquimicos","Si")))
    el.append(campo("Utiliza bioinsumos", g("bioinsumos","Si")))
    el.append(campo("Tipo de labranza", g("labranza","Convencional")))

    el += seccion("6. RELACION CON LA TIERRA")
    el.append(campo("Desde que año produce aca", g("anio_produce")))
    el.append(campo("Condicion (tenencia)", g("tenencia","Mediero")))
    el.append(campo("Sufrio riesgo de desalojo", g("desalojo","No")))

    el += seccion("7. COBERTURA FINANCIERA Y VENTA")
    el.append(campo("Posee cuenta bancaria activa", g("cuenta_banco","Si")))
    el.append(campo("Accedio a credito alguna vez", g("credito","No")))
    el.append(campo("Destino de la produccion", g("destino","Venta")))
    el.append(campo("Posee vehiculo propio para traslado", g("vehiculo","No")))

    el += seccion("8. RIESGO Y PERSPECTIVAS")
    el.append(campo("Tuvo perdidas por adversidades climaticas", g("perdidas","Si")))
    el.append(campo("Posee cobertura de riesgo (seguro)", g("seguro","No")))
    el.append(campo("Perspectiva para el proximo año", g("perspectiva")))

    # Secciones que NO aplican
    el += seccion("SECCIONES QUE NO CORRESPONDEN A VIÑA")
    el.append(Paragraph("Las siguientes secciones del formulario NO se completan en tu caso (dejalas en blanco): "
        "Datos de otras personas del NAF (salvo que tengas familia trabajando con vos), Ganaderia, Agroindustria, "
        "Pesca artesanal, Acuicultura, Artesania, Caza/Recoleccion y Turismo rural.", s_nota))

    # Pasos para presentar
    el += seccion("COMO PRESENTAR EL FORMULARIO")
    el.append(Paragraph("1. Completa el formulario oficial en papel con estos datos y firmalo (es declaracion jurada).", s_nota))
    el.append(Paragraph("2. Adjunta copia del DNI (frente y dorso).", s_nota))
    el.append(Paragraph("3. Adjunta imagen satelital del predio (Google Maps) con la ubicacion (latitud y longitud) y la superficie.", s_nota))
    el.append(Paragraph("4. Presentalo en la delegacion correspondiente o consulta en: https://renaf.magyp.gob.ar", s_nota))

    el.append(Spacer(1, 0.4*cm))
    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    el.append(Paragraph("Guia generada por Bot Contratistas | ReNAF - renaf.magyp.gob.ar | Ley 27.118", s_footer))

    doc.build(el)
    buffer.seek(0)
    return buffer.read()
