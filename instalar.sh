#!/bin/bash
# ============================================================
# Instalador automático - BotContador
# Código desde GitHub + credenciales desde tu Google Drive.
# Deja el bot corriendo con pm2.
# ============================================================
set -e

REPO="https://github.com/Agro-bot2026/bot-contador.git"
DIR="/root/BotContador"

echo "============================================"
echo "   INSTALADOR BOTCONTADOR"
echo "============================================"
echo ""

echo "[1/7] Instalando dependencias del sistema..."
apt update -qq
apt install -y python3 python3-venv python3-pip git curl tar nodejs npm >/dev/null 2>&1
if ! command -v pm2 >/dev/null 2>&1; then
    npm install -g pm2 >/dev/null 2>&1
fi
echo "      Listo."

echo "[2/7] Clonando el código desde GitHub..."
if [ -d "$DIR" ]; then
    echo "      ATENCION: $DIR ya existe. Respaldala y borrala antes de reinstalar."
    exit 1
fi
git clone "$REPO" "$DIR"
cd "$DIR"
echo "      Codigo descargado."

echo "[3/7] Creando entorno virtual e instalando librerias (tarda unos minutos)..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip >/dev/null 2>&1
./venv/bin/pip install -r requirements.txt >/dev/null 2>&1
echo "      Librerias instaladas."

echo "[4/7] Necesito tu backup de credenciales (.env, llave.json, vectordb)."
echo "      Esta en tu Drive: Backups_VPS/BotContador/"
echo ""
echo "      Pega el ENLACE NORMAL de Drive (el de compartir)."
echo ""
read -p "      Enlace de Drive: " ENLACE_DRIVE

if [ -z "$ENLACE_DRIVE" ]; then
    echo "      No pegaste enlace. El bot queda instalado SIN credenciales."
    echo "      Subi a mano .env, llave.json y vectordb/ a $DIR y arranca con pm2."
    exit 0
fi

FILE_ID=$(echo "$ENLACE_DRIVE" | grep -oE '[-_a-zA-Z0-9]{25,}' | head -1)
if [ -z "$FILE_ID" ]; then
    echo "      No pude extraer el ID del enlace. Revisa que sea un enlace de Drive valido."
    exit 1
fi
echo "      ID detectado: $FILE_ID"

echo "[5/7] Descargando credenciales desde Drive..."
DL="https://drive.google.com/uc?export=download&id=${FILE_ID}"
curl -L -c /tmp/gdrive_cookie.txt "$DL" -o /tmp/credenciales.tar.gz
if file /tmp/credenciales.tar.gz | grep -qi "html"; then
    CONFIRM=$(grep -oE 'confirm=[a-zA-Z0-9_-]+' /tmp/credenciales.tar.gz | head -1 | cut -d= -f2)
    curl -L -b /tmp/gdrive_cookie.txt \
        "https://drive.google.com/uc?export=download&confirm=${CONFIRM}&id=${FILE_ID}" \
        -o /tmp/credenciales.tar.gz
fi
rm -f /tmp/gdrive_cookie.txt
echo "      Descargado."

echo "[6/7] Extrayendo credenciales y base vectorial..."
tar xzf /tmp/credenciales.tar.gz -C "$DIR"
rm -f /tmp/credenciales.tar.gz
if [ ! -f "$DIR/.env" ] || [ ! -f "$DIR/llave.json" ]; then
    echo "      ATENCION: no encuentro .env o llave.json tras extraer."
    echo "      Revisa el backup antes de arrancar el bot."
    exit 1
fi
echo "      Credenciales en su lugar."

echo "[7/7] Arrancando el bot con pm2..."
cd "$DIR"
pm2 start bot.py --name bot-contador --interpreter "$DIR/venv/bin/python3"
pm2 save
echo ""
echo "============================================"
echo "   INSTALACION COMPLETA - el bot esta corriendo"
echo "============================================"
echo "   pm2 list              -> ver estado"
echo "   pm2 logs bot-contador -> ver logs"
echo ""
echo "   IMPORTANTE: Volve a tu Drive y pone el"
echo "   archivo de credenciales como PRIVADO de nuevo."
echo "============================================"
