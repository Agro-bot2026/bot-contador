import os
import chromadb
from sentence_transformers import SentenceTransformer
import PyPDF2

print("🔄 Iniciando creación de base vectorial...")

# Inicializar ChromaDB
cliente = chromadb.PersistentClient(path="/root/BotContador/vectordb")
try:
    cliente.delete_collection("documentos_legales")
except:
    pass
coleccion = cliente.create_collection("documentos_legales")

# Modelo de embeddings en español
print("🔄 Cargando modelo de embeddings...")
modelo = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

def extraer_texto_pdf(ruta):
    try:
        with open(ruta, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            return " ".join([p.extract_text() or "" for p in reader.pages])
    except:
        return ""

def extraer_texto_txt(ruta):
    try:
        with open(ruta, "r", errors="ignore") as f:
            return f.read()
    except:
        return ""

def chunk_semantico(texto, chunk_size=500, overlap=50):
    """Divide el texto en chunks con overlap"""
    palabras = texto.split()
    chunks = []
    i = 0
    while i < len(palabras):
        chunk = " ".join(palabras[i:i+chunk_size])
        if len(chunk.strip()) > 100:
            chunks.append(chunk)
        i += chunk_size - overlap
    return chunks

# Procesar todos los documentos
docs_dir = "/root/BotContador/documentos"
total_chunks = 0
archivos_procesados = 0

for archivo in sorted(os.listdir(docs_dir)):
    ruta = os.path.join(docs_dir, archivo)
    
    if archivo.endswith(".pdf"):
        texto = extraer_texto_pdf(ruta)
    elif archivo.endswith(".txt"):
        texto = extraer_texto_txt(ruta)
    else:
        continue
    
    if not texto or len(texto) < 100:
        print(f"⚠️ Saltando {archivo} (vacío o muy corto)")
        continue
    
    chunks = chunk_semantico(texto)
    if not chunks:
        continue
    
    # Crear embeddings
    embeddings = modelo.encode(chunks).tolist()
    
    # Guardar en ChromaDB
    ids = [f"{archivo}_{i}" for i in range(len(chunks))]
    metadatos = [{"fuente": archivo, "chunk": i} for i in range(len(chunks))]
    
    coleccion.add(
        documents=chunks,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatos
    )
    
    total_chunks += len(chunks)
    archivos_procesados += 1
    print(f"✅ {archivo}: {len(chunks)} chunks")

print(f"\n✅ Base vectorial creada")
print(f"📄 Archivos procesados: {archivos_procesados}")
print(f"🔢 Total chunks: {total_chunks}")
