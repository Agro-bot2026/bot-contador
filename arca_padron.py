"""
Módulo de consulta al padrón de ARCA (ex-AFIP).
Autentica con certificado digital (WSAA) y consulta datos fiscales de un CUIT
usando el web service ws_sr_constancia_inscripcion.
"""
import os
import datetime
from lxml import etree
from zeep import Client
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7

# Rutas de los certificados
_DIR = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(_DIR, "arca_cert", "botcontador_arca.crt")
KEY = os.path.join(_DIR, "arca_cert", "clave_privada.key")

# URLs de PRODUCCIÓN de ARCA
WSAA_URL = "https://wsaa.afip.gov.ar/ws/services/LoginCms?wsdl"
PADRON_URL = "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5?wsdl"
SERVICE = "ws_sr_constancia_inscripcion"

# Cache del ticket de acceso (dura 12hs, lo guardamos para no re-autenticar cada vez)
_TA_CACHE = {"token": None, "sign": None, "expira": None}


def _crear_tra():
    """Crea el Ticket de Requerimiento de Acceso (TRA) en XML. Usa hora argentina (UTC-3)."""
    # ARCA espera hora argentina. Forzamos UTC-3 sin importar la zona del VPS.
    utc = datetime.datetime.now(datetime.timezone.utc)
    ar = datetime.timezone(datetime.timedelta(hours=-3))
    ahora = utc.astimezone(ar)
    desde = ahora - datetime.timedelta(minutes=10)
    hasta = ahora + datetime.timedelta(hours=12)
    tra = etree.Element("loginTicketRequest", version="1.0")
    cab = etree.SubElement(tra, "header")
    etree.SubElement(cab, "uniqueId").text = str(int(ahora.timestamp()))
    etree.SubElement(cab, "generationTime").text = desde.strftime("%Y-%m-%dT%H:%M:%S")
    etree.SubElement(cab, "expirationTime").text = hasta.strftime("%Y-%m-%dT%H:%M:%S")
    etree.SubElement(tra, "service").text = SERVICE
    return etree.tostring(tra, encoding="UTF-8")


def _firmar_tra(tra):
    """Firma el TRA con el certificado (CMS/PKCS7) y devuelve el CMS en base64."""
    with open(CERT, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    with open(KEY, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    cms = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(tra)
        .add_signer(cert, key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    )
    import base64
    return base64.b64encode(cms).decode()


def _autenticar():
    """Obtiene el Ticket de Acceso (token y sign) de ARCA. Lo cachea 12hs."""
    ahora = datetime.datetime.now()
    if _TA_CACHE["token"] and _TA_CACHE["expira"] and _TA_CACHE["expira"] > ahora:
        return _TA_CACHE["token"], _TA_CACHE["sign"]

    tra = _crear_tra()
    cms = _firmar_tra(tra)
    client = Client(WSAA_URL)
    respuesta = client.service.loginCms(in0=cms)

    root = etree.fromstring(respuesta.encode("utf-8"))
    token = root.findtext("credentials/token")
    sign = root.findtext("credentials/sign")
    _TA_CACHE["token"] = token
    _TA_CACHE["sign"] = sign
    _TA_CACHE["expira"] = ahora + datetime.timedelta(hours=11)
    return token, sign


def consultar(cuit, cuit_representada="20274081024"):
    """
    Consulta los datos fiscales de un CUIT en ARCA.
    Devuelve un dict con nombre, condición, actividad y domicilio, o error.
    """
    cuit = "".join(filter(str.isdigit, str(cuit)))
    if len(cuit) != 11:
        return {"ok": False, "error": "El CUIT debe tener 11 dígitos."}
    try:
        token, sign = _autenticar()
        client = Client(PADRON_URL)
        res = client.service.getPersona_v2(
            token=token, sign=sign,
            cuitRepresentada=cuit_representada, idPersona=cuit
        )
        dg = res.datosGenerales
        # Nombre / razón social
        if getattr(dg, "razonSocial", None):
            nombre = dg.razonSocial
        else:
            ape = getattr(dg, "apellido", "") or ""
            nom = getattr(dg, "nombre", "") or ""
            nombre = f"{ape} {nom}".strip()
        # Domicilio
        dom = ""
        d = getattr(dg, "domicilioFiscal", None)
        if d:
            partes = [getattr(d, "direccion", ""), getattr(d, "localidad", ""),
                      getattr(d, "descripcionProvincia", "")]
            dom = ", ".join(p for p in partes if p)
        # Condición: monotributo / régimen general / consulta
        condicion = "No inscripto / Consulta"
        if getattr(res, "datosMonotributo", None):
            condicion = "Monotributista"
        elif getattr(res, "datosRegimenGeneral", None):
            condicion = "Responsable Inscripto / Régimen General"
        return {
            "ok": True,
            "cuit": cuit,
            "nombre": nombre or "No identificado",
            "estado": getattr(dg, "estadoClave", "") or "",
            "tipo_persona": getattr(dg, "tipoPersona", "") or "",
            "condicion": condicion,
            "domicilio": dom,
        }
    except Exception as e:
        return {"ok": False, "error": f"Error consultando ARCA: {str(e)[:120]}"}


if __name__ == "__main__":
    import sys, json
    cuit = sys.argv[1] if len(sys.argv) > 1 else "20274081024"
    print(json.dumps(consultar(cuit), indent=2, ensure_ascii=False))
