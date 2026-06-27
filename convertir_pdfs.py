import PyPDF2
import os

docs_dir = "/root/BotContador/documentos"

# PDFs más importantes para convertir
pdfs_importantes = [
    "Ley 23154.pdf",
    "ESTATUTO DEL CONTRATISTA DE VIÑAS Y FRUTALES..pdf",
    "ccg-_texto_ordenado_ccgv_07-2020ccg.pdf",
    "Disposición 1 2020.pdf",
    "ley_26.377_0.pdf",
    "Ley 8114.pdf",
    "Resolución 41 2015.pdf",
    "resol-2017-112-apn-inv-ma.pdf"
]

for archivo in pdfs_importantes:
    ruta = os.path.join(docs_dir, archivo)
    if not os.path.exists(ruta):
        print(f"⚠️ No encontrado: {archivo}")
        continue
    
    try:
        with open(ruta, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            texto = ""
            for pag in reader.pages:
                texto += pag.extract_text() or ""
        
        if len(texto.strip()) < 100:
            print(f"⚠️ Texto muy corto en: {archivo}")
            continue
        
        nombre_txt = archivo.replace(".pdf", ".txt").replace(" ", "_")
        ruta_txt = os.path.join(docs_dir, nombre_txt)
        
        with open(ruta_txt, "w", encoding="utf-8") as f:
            f.write(texto)
        
        print(f"✅ Convertido: {nombre_txt} ({len(texto)} chars)")
    except Exception as e:
        print(f"❌ Error en {archivo}: {e}")

print("\n✅ Conversión completada")
