# -*- coding: utf-8 -*-
def generar_cosecha_inv_pdf(datos: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io

    BORDO = colors.HexColor("#8B1538")
    GRIS = colors.HexColor("#555555")
    GRIS_CLARO = colors.HexColor("#f5f5f5")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=1.3*cm, leftMargin=1.3*cm, topMargin=1.3*cm, bottomMargin=1.3*cm)
    PAGE_W = A4[0] - 2.6*cm

    s_inv = ParagraphStyle("INV", fontSize=12, fontName="Helvetica-Bold", textColor=BORDO, alignment=TA_CENTER, leading=14)
    s_titulo = ParagraphStyle("T", fontSize=11, fontName="Helvetica-Bold", textColor=colors.black, alignment=TA_CENTER, spaceAfter=2)
    s_sub = ParagraphStyle("S", fontSize=8, fontName="Helvetica-Bold", textColor=GRIS, alignment=TA_CENTER, spaceAfter=2)
    s_seccion = ParagraphStyle("SEC", fontSize=9, fontName="Helvetica-Bold", textColor=colors.black, spaceAfter=4, spaceBefore=8)
    s_campo = ParagraphStyle("C", fontSize=9.5, fontName="Helvetica", spaceAfter=5, leading=14)
    s_cell = ParagraphStyle("CELL", fontSize=9, fontName="Helvetica", alignment=TA_LEFT)
    s_cellh = ParagraphStyle("CELLH", fontSize=8.5, fontName="Helvetica-Bold", alignment=TA_LEFT, textColor=colors.black)
    s_footer = ParagraphStyle("F", fontSize=7, fontName="Helvetica", textColor=colors.grey, alignment=TA_CENTER)
    s_firma = ParagraphStyle("FIRMA", fontSize=8, fontName="Helvetica-Bold", textColor=colors.black, alignment=TA_CENTER)

    def g(k, d=""):
        return str(datos.get(k, d)) if datos.get(k, d) else d

    el = []

    # Encabezado con logo INV
    hdr_data = [[
        Paragraph("INV", ParagraphStyle("L", fontSize=16, fontName="Helvetica-Bold", textColor=BORDO, alignment=TA_CENTER)),
        Paragraph("INSTITUTO NACIONAL DE VITIVINICULTURA", s_inv),
        Paragraph(f"FECHA:<br/>{g('fecha','___/___/20___')}", ParagraphStyle("FE", fontSize=8, fontName="Helvetica-Bold", alignment=TA_CENTER, leading=11)),
    ]]
    t_hdr = Table(hdr_data, colWidths=[2*cm, PAGE_W-5*cm, 3*cm])
    t_hdr.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BOX",(0,0),(0,0),2,BORDO),
        ("LINEBELOW",(0,0),(-1,-1),0,colors.white),
    ]))
    el.append(t_hdr)
    el.append(Spacer(1, 0.15*cm))
    el.append(HRFlowable(width="100%", thickness=2.5, color=BORDO))
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph("INFORME DE FINALIZACION DE COSECHA (CONTRATISTAS)", s_titulo))
    el.append(Paragraph("Unidad Ejecutora de los Convenios de Corresponsabilidad Gremial", s_sub))
    el.append(Spacer(1, 0.3*cm))

    # Datos del viñedo
    el.append(Paragraph(f"<b>N° de Viñedo:</b>  {g('vinedo','________________')}", s_campo))
    el.append(Paragraph(f"<b>Razón Social:</b>  {g('razon_social','________________')}", s_campo))
    el.append(Paragraph(f"<b>CUIT:</b>  {g('cuit','________________')}", s_campo))
    el.append(Spacer(1, 0.15*cm))

    def tabla(titulo, headers, filas, col_widths):
        el.append(Paragraph(titulo, s_seccion))
        data = [[Paragraph(h, s_cellh) for h in headers]]
        for fila in filas:
            data.append([Paragraph(str(c), s_cell) for c in fila])
        if not filas:
            data.append([Paragraph("", s_cell) for _ in headers])
        t = Table(data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),GRIS_CLARO),
            ("GRID",(0,0),(-1,-1),0.7,colors.black),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),
        ]))
        el.append(t)
        el.append(Spacer(1, 0.2*cm))

    # Hectareas y porcentaje
    tabla("CANTIDAD DE HECTÁREAS COSECHADAS Y PORCENTAJE SEGÚN CONTRATO",
          ["Hectáreas (ha)", "Porcentaje (%)"],
          [[g('hectareas','____'), g('porcentaje','____')]],
          [PAGE_W*0.5, PAGE_W*0.5])

    # Variedades (dinamico)
    variedades = datos.get('variedades', [])
    filas_var = [[v.get('variedad',''), v.get('quintales','')] for v in variedades] if variedades else []
    tabla("VARIEDAD DE UVA Y SUS QUINTALES COSECHADOS",
          ["Variedad", "Quintales"], filas_var,
          [PAGE_W*0.5, PAGE_W*0.5])

    # Contratista
    tabla("NOMBRE Y APELLIDO DE CONTRATISTA Y DNI",
          ["Contratista", "DNI - LC - LE"],
          [[g('contratista','________________'), g('dni','____________')]],
          [PAGE_W*0.6, PAGE_W*0.4])

    # Quintales totales
    tabla("QUINTALES TOTALES COSECHADOS POR CONTRATISTA",
          ["Quintales totales"],
          [[g('quintales_totales','________________')]],
          [PAGE_W])

    # Bodegas (dinamico)
    bodegas = datos.get('bodegas', [])
    filas_bod = [[b.get('bodega',''), b.get('quintales','')] for b in bodegas] if bodegas else []
    tabla("BODEGAS DONDE LLEVÓ LA UVA (razón social y N° de INV)",
          ["Bodega (razón social y N° INV)", "Quintales"], filas_bod,
          [PAGE_W*0.7, PAGE_W*0.3])

    # Contacto
    tabla("CONTACTO",
          ["Teléfono", "Domicilio", "Mail"],
          [[g('telefono',''), g('domicilio',''), g('mail','')]],
          [PAGE_W*0.3, PAGE_W*0.37, PAGE_W*0.33])

    # Firmas
    el.append(Spacer(1, 0.8*cm))
    firma_data = [[
        Paragraph("_______________________<br/>REVISADO POR<br/>(Firma y Sello)", s_firma),
        Paragraph("_______________________<br/>RESPONSABLE<br/>(Firma y Aclaración)", s_firma),
    ]]
    t_firma = Table(firma_data, colWidths=[PAGE_W*0.5, PAGE_W*0.5])
    t_firma.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),10)]))
    el.append(t_firma)

    el.append(Spacer(1, 0.5*cm))
    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    el.append(Paragraph("Generado por Bot Contratistas | INV - Convenio de Corresponsabilidad Gremial", s_footer))

    doc.build(el)
    buffer.seek(0)
    return buffer.read()
