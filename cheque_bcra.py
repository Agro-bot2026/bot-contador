"""
Módulo de verificación de cheques vía API del BCRA (Central de Deudores).
"""
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
_BASE = "https://api.bcra.gob.ar/centraldedeudores/v1.0/Deudas"

SITUACIONES = {
    1: "Normal", 2: "Riesgo bajo", 3: "Riesgo medio / Con problemas",
    4: "Alto riesgo de insolvencia", 5: "Irrecuperable",
    6: "Irrecuperable por disposición técnica",
}

def _limpiar_cuit(cuit):
    return "".join(filter(str.isdigit, str(cuit)))

def _get(url):
    """GET con reintentos. Devuelve (status, json|None, error|None)."""
    import time
    ultimo_error = None
    for intento in range(4):
        try:
            r = requests.get(url, timeout=25, verify=False, headers=_HEADERS)
            if r.status_code == 404:
                return 404, None, None
            if r.status_code != 200:
                ultimo_error = f"El BCRA respondió código {r.status_code}"
                time.sleep(2)
                continue
            return 200, r.json(), None
        except Exception as e:
            ultimo_error = f"No se pudo conectar al BCRA: {str(e)[:60]}"
            time.sleep(2)
    return None, None, ultimo_error


def consultar_cheques(cuit):
    cuit = _limpiar_cuit(cuit)
    if len(cuit) != 11:
        return {"ok": False, "error": "El CUIT/CUIL debe tener 11 dígitos."}
    status, data, error = _get(f"{_BASE}/ChequesRechazados/{cuit}")
    if error:
        return {"ok": False, "error": error}
    if status == 404 or not data:
        return {"ok": True, "nombre": None, "total": 0, "monto_total": 0.0, "cheques": []}
    results = data.get("results", {})
    nombre = results.get("denominacion")
    cheques = []
    monto_total = 0.0
    for c in results.get("causales", []):
        causal = c.get("causal", "—")
        for ent in c.get("entidades", []):
            for d in ent.get("detalle", []):
                m = d.get("monto", 0) or 0
                monto_total += m
                cheques.append({"nro": d.get("nroCheque"), "fecha": d.get("fechaRechazo"),
                    "monto": m, "causal": causal, "multa": d.get("estadoMulta", "—"),
                    "fecha_pago": d.get("fechaPago"),
                    "proceso_jud": d.get("procesoJud", False)})
    return {"ok": True, "nombre": nombre, "total": len(cheques),
            "monto_total": monto_total, "cheques": cheques}

def consultar_deudas(cuit):
    cuit = _limpiar_cuit(cuit)
    if len(cuit) != 11:
        return {"ok": False, "error": "El CUIT/CUIL debe tener 11 dígitos."}
    status, data, error = _get(f"{_BASE}/{cuit}")
    if error:
        return {"ok": False, "error": error}
    if status == 404 or not data:
        return {"ok": True, "nombre": None, "entidades": [], "peor_situacion": 0}
    results = data.get("results", {})
    nombre = results.get("denominacion")
    entidades = []
    peor = 0
    for periodo in results.get("periodos", []):
        for ent in periodo.get("entidades", []):
            sit = ent.get("situacion", 0) or 0
            peor = max(peor, sit)
            entidades.append({"entidad": ent.get("entidad", "—"), "situacion": sit,
                "monto": ent.get("monto", 0) or 0, "dias_atraso": ent.get("diasAtrasoPago", 0)})
    return {"ok": True, "nombre": nombre, "entidades": entidades, "peor_situacion": peor}

def verificar_cuit(cuit):
    cuit = _limpiar_cuit(cuit)
    if len(cuit) != 11:
        return {"ok": False, "error": "El CUIT/CUIL debe tener 11 dígitos. Revisá el número."}
    cheques = consultar_cheques(cuit)
    if not cheques["ok"]:
        return {"ok": False, "error": cheques["error"]}
    deudas = consultar_deudas(cuit)
    if not deudas["ok"]:
        deudas = {"ok": True, "nombre": None, "entidades": [], "peor_situacion": 0}
    nombre = cheques.get("nombre") or deudas.get("nombre") or "No identificado"
    n_cheques = cheques["total"]
    peor_sit = deudas["peor_situacion"]
    if n_cheques > 0:
        nivel, emoji = "PELIGROSO", "🔴"
        resumen = f"Tiene {n_cheques} cheque(s) rechazado(s) por un total de ${cheques['monto_total']:,.0f}."
    elif peor_sit >= 3:
        nivel, emoji = "PRECAUCIÓN", "🟡"
        resumen = f"No tiene cheques rechazados, pero su situación crediticia es {SITUACIONES.get(peor_sit, peor_sit)}."
    else:
        nivel, emoji = "SIN ANTECEDENTES", "🟢"
        resumen = "No registra cheques rechazados ni problemas crediticios graves."
    hay_juicio = any(c.get("proceso_jud") for c in cheques["cheques"])
    return {"ok": True, "cuit": cuit, "nombre": nombre, "nivel": nivel, "emoji": emoji,
            "resumen": resumen, "cheques": cheques, "deudas": deudas,
            "hay_juicio": hay_juicio,
            "fecha_consulta": datetime.now().strftime("%d/%m/%Y %H:%M")}

if __name__ == "__main__":
    import sys, json
    cuit = sys.argv[1] if len(sys.argv) > 1 else "23200753569"
    print(json.dumps(verificar_cuit(cuit), indent=2, ensure_ascii=False))


def generar_pdf(reporte: dict) -> bytes:
    """Genera el PDF de verificación de cheque a partir del reporte de verificar_cuit()."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable)

    # Color del veredicto
    colores_nivel = {
        "PELIGROSO": colors.HexColor("#c0392b"),
        "PRECAUCIÓN": colors.HexColor("#d68910"),
        "SIN ANTECEDENTES": colors.HexColor("#1e8449"),
    }
    color_v = colores_nivel.get(reporte["nivel"], colors.grey)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1.5*cm,
                            bottomMargin=1.5*cm, leftMargin=2*cm, rightMargin=2*cm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=16, textColor=colors.HexColor("#1a2b4a"))
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER)
    vstyle = ParagraphStyle("v", parent=styles["Title"], fontSize=22, textColor=colors.white, alignment=TA_CENTER)
    normal = styles["Normal"]
    bold = ParagraphStyle("b", parent=styles["Normal"], fontName="Helvetica-Bold")
    seccion = ParagraphStyle("sec", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#1a2b4a"))

    el = []
    el.append(Paragraph("Verificación de Cheque - BotContador", h1))
    el.append(Paragraph("Datos oficiales de la Central de Deudores del BCRA", sub))
    el.append(Spacer(1, 0.4*cm))
    el.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a2b4a")))
    el.append(Spacer(1, 0.4*cm))

    # Bloque del veredicto (banda de color)
    veredicto_tbl = Table([[Paragraph(f"{reporte['nivel']}", vstyle)]], colWidths=[17*cm])
    veredicto_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), color_v),
        ("TOPPADDING", (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
    ]))
    el.append(veredicto_tbl)
    el.append(Spacer(1, 0.3*cm))
    el.append(Paragraph(reporte["resumen"], ParagraphStyle("res", parent=normal, alignment=TA_CENTER, fontSize=11)))
    if reporte.get("hay_juicio"):
        el.append(Spacer(1, 0.2*cm))
        el.append(Paragraph("ATENCION: Hay cheques con proceso judicial en curso.",
            ParagraphStyle("juicio", parent=normal, alignment=TA_CENTER, fontSize=11,
                           textColor=colors.HexColor("#c0392b"), fontName="Helvetica-Bold")))
    el.append(Spacer(1, 0.5*cm))

    # Datos del emisor
    el.append(Paragraph("Datos del emisor", seccion))
    datos_tbl = Table([
        ["Nombre / Razón social:", reporte["nombre"]],
        ["CUIT / CUIL:", reporte["cuit"]],
        ["Fecha de consulta:", reporte["fecha_consulta"]],
    ], colWidths=[5*cm, 12*cm])
    datos_tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LINEBELOW", (0,0), (-1,-1), 0.3, colors.HexColor("#dddddd")),
    ]))
    el.append(datos_tbl)
    el.append(Spacer(1, 0.5*cm))

    # Datos fiscales de ARCA (si están disponibles)
    arca = reporte.get("arca")
    if arca and arca.get("ok"):
        el.append(Paragraph("Datos fiscales (ARCA)", seccion))
        filas_arca = []
        if arca.get("estado"):
            filas_arca.append(["Estado de la clave:", arca["estado"]])
        if arca.get("tipo_persona"):
            tp = "Persona física" if arca["tipo_persona"] == "FISICA" else "Persona jurídica"
            filas_arca.append(["Tipo:", tp])
        if arca.get("condicion"):
            filas_arca.append(["Condición:", arca["condicion"]])
        if arca.get("domicilio"):
            filas_arca.append(["Domicilio fiscal:", arca["domicilio"]])
        if filas_arca:
            arca_tbl = Table(filas_arca, colWidths=[5*cm, 12*cm])
            arca_tbl.setStyle(TableStyle([
                ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 10),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                ("LINEBELOW", (0,0), (-1,-1), 0.3, colors.HexColor("#dddddd")),
            ]))
            el.append(arca_tbl)
        el.append(Spacer(1, 0.5*cm))

    # Cheques rechazados
    cheques = reporte["cheques"]["cheques"]
    el.append(Paragraph(f"Cheques rechazados ({len(cheques)})", seccion))
    if cheques:
        filas = [["N° Cheque", "Fecha rechazo", "Monto", "Causal", "Estado"]]
        for c in cheques:
            if c.get("fecha_pago"):
                estado = f"Pagado {c['fecha_pago']}"
            elif c.get("proceso_jud"):
                estado = "EN JUICIO"
            else:
                estado = "Impago"
            filas.append([str(c["nro"]), c["fecha"], f"${c['monto']:,.0f}", c["causal"], estado])
        ch_tbl = Table(filas, colWidths=[3*cm, 3.5*cm, 3.5*cm, 4*cm, 3*cm])
        ch_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#c0392b")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#fdf2f2")]),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        el.append(ch_tbl)
    else:
        el.append(Paragraph("Sin cheques rechazados registrados.", normal))
    el.append(Spacer(1, 0.5*cm))

    # Estado del cheque (denuncia por robo/extravío)
    denuncia = reporte.get("denuncia")
    if denuncia and denuncia.get("ok") and denuncia.get("consultado"):
        el.append(Paragraph("Estado del cheque (denuncias BCRA)", seccion))
        if denuncia.get("denunciado"):
            causales = ", ".join(denuncia.get("causales", [])) or "Denunciado"
            txt = f"CHEQUE DENUNCIADO - {causales}. Banco: {denuncia.get('banco','—')}. Nº {denuncia.get('numero_cheque','—')}."
            el.append(Paragraph(txt, ParagraphStyle("den", parent=normal, fontSize=11,
                textColor=colors.HexColor("#c0392b"), fontName="Helvetica-Bold")))
        else:
            el.append(Paragraph(f"Cheque sin denuncias en el BCRA. Banco: {denuncia.get('banco','—')}. Nº {denuncia.get('numero_cheque','—')}.",
                ParagraphStyle("noden", parent=normal, fontSize=10,
                textColor=colors.HexColor("#1e8449"))))
        el.append(Spacer(1, 0.5*cm))

    # Situación crediticia
    entidades = reporte["deudas"]["entidades"]
    el.append(Paragraph("Situación crediticia (BCRA)", seccion))
    if entidades:
        filas = [["Entidad", "Situación", "Monto (miles $)"]]
        for e in entidades:
            sit_txt = f"{e['situacion']} - {SITUACIONES.get(e['situacion'], '')}"
            filas.append([e["entidad"], sit_txt, f"${e['monto']:,.0f}"])
        d_tbl = Table(filas, colWidths=[8*cm, 6*cm, 3*cm])
        d_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a2b4a")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        el.append(d_tbl)
        el.append(Spacer(1, 0.2*cm))
        el.append(Paragraph("Situación: 1=Normal, 2=Riesgo bajo, 3=Con problemas, 4=Alto riesgo, 5=Irrecuperable.",
                            ParagraphStyle("nota", parent=normal, fontSize=8, textColor=colors.grey)))
    else:
        el.append(Paragraph("Sin deudas registradas en el sistema financiero.", normal))
    el.append(Spacer(1, 0.6*cm))

    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    el.append(Spacer(1, 0.2*cm))
    el.append(Paragraph(
        "Informe orientativo generado con datos oficiales de la Central de Deudores del BCRA. "
        "La base del BCRA se actualiza mensualmente y puede tener semanas de demora. "
        "Este informe no constituye asesoramiento financiero ni garantía sobre el cheque consultado.",
        ParagraphStyle("pie", parent=normal, fontSize=8, textColor=colors.grey, alignment=TA_LEFT)))

    doc.build(el)
    buffer.seek(0)
    return buffer.read()


# Cache de entidades bancarias (se carga una vez)
_ENTIDADES_CACHE = None

def listar_entidades():
    """Devuelve la lista de bancos con su código. Cachea el resultado."""
    global _ENTIDADES_CACHE
    if _ENTIDADES_CACHE is not None:
        return _ENTIDADES_CACHE
    status, data, error = _get("https://api.bcra.gob.ar/cheques/v1.0/entidades")
    if error or not data:
        return []
    _ENTIDADES_CACHE = data.get("results", [])
    return _ENTIDADES_CACHE


def consultar_denunciado(codigo_entidad, numero_cheque):
    """Consulta si un cheque está denunciado. Devuelve dict con denunciado, causales, etc."""
    try:
        codigo_entidad = int(codigo_entidad)
        numero_cheque = int("".join(filter(str.isdigit, str(numero_cheque))))
    except (ValueError, TypeError):
        return {"ok": False, "error": "Código de banco o número de cheque inválido."}

    url = f"https://api.bcra.gob.ar/cheques/v1.0/denunciados/{codigo_entidad}/{numero_cheque}"
    status, data, error = _get(url)
    if error:
        return {"ok": False, "error": error}
    if status == 404 or not data:
        return {"ok": True, "consultado": False, "denunciado": False,
                "motivo": "No se encontró el banco o el cheque."}

    results = data.get("results", {})
    detalles = results.get("detalles", []) or []
    causales = list({d.get("causal", "—") for d in detalles})
    return {
        "ok": True,
        "consultado": True,
        "denunciado": results.get("denunciado", False),
        "numero_cheque": results.get("numeroCheque"),
        "banco": results.get("denominacionEntidad", "—"),
        "fecha": results.get("fechaProcesamiento", "—"),
        "causales": causales,
    }


def construir_prompt_ocr():
    """Arma el prompt para que Gemini extraiga todos los datos del cheque."""
    entidades = listar_entidades()
    lista_bancos = "\n".join(f"{e['codigoEntidad']}: {e['denominacion'].strip()}"
                             for e in entidades)
    return (
        "Mirá esta imagen de un cheque bancario argentino y extraé estos datos:\n"
        "1. CUIT o CUIL del librador (quien emite el cheque): 11 dígitos.\n"
        "2. Número del cheque (suele estar arriba a la derecha o en el código de barras inferior).\n"
        "3. El banco emisor. Identificá cuál es de esta lista y devolvé su CÓDIGO numérico:\n"
        f"{lista_bancos}\n\n"
        "Devolvé SOLO un JSON válido, sin explicaciones ni markdown, con este formato exacto:\n"
        '{"cuit": "20123456789", "codigo_banco": 11, "numero_cheque": "12345678"}\n'
        "Si algún dato no lo encontrás, poné null en ese campo. "
        "Para el CUIT devolvé solo los 11 dígitos sin guiones."
    )


def verificar_completo(cuit, codigo_banco=None, numero_cheque=None):
    """
    Verificación completa: antecedentes del emisor (por CUIT) +
    si el cheque está denunciado (por banco + número, si se proveen).
    """
    reporte = verificar_cuit(cuit)
    if not reporte.get("ok"):
        return reporte

    # Agregar consulta de denuncia si tenemos banco y número
    denuncia = None
    if codigo_banco and numero_cheque:
        denuncia = consultar_denunciado(codigo_banco, numero_cheque)
    reporte["denuncia"] = denuncia

    # Datos fiscales de ARCA (si está disponible; si falla, no rompe el reporte)
    reporte["arca"] = None
    try:
        import arca_padron
        datos_arca = arca_padron.consultar(cuit)
        if datos_arca.get("ok"):
            reporte["arca"] = datos_arca
    except Exception:
        reporte["arca"] = None

    # Si el cheque está denunciado, eleva el veredicto a lo máximo
    if denuncia and denuncia.get("ok") and denuncia.get("denunciado"):
        reporte["nivel"] = "PELIGROSO"
        reporte["emoji"] = "🔴"
        causales = ", ".join(denuncia.get("causales", [])) or "denunciado"
        reporte["resumen"] = f"CHEQUE DENUNCIADO ({causales}). " + reporte["resumen"]

    return reporte
