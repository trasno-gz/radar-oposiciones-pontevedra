import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DATA_PATH = "docs/data.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RadarEmpleoPontevedra/1.0)"
}

ENTIDADES_PONTEVEDRA_GALICIA = [
    "xunta de galicia", "deputacion de pontevedra", "diputacion provincial de pontevedra",
    "agolada", "arbo", "baiona", "barro", "bueu", "caldas de reis", "cambados",
    "campo lameiro", "cangas", "caniza", "catoira", "cerdedo", "cotobade", "covelo",
    "crecente", "cuntis", "dozon", "estrada", "forcarei", "fornelos de montes",
    "gondomar", "grove", "guarda", "illa de arousa", "lalin", "lama", "marin",
    "meano", "meis", "moana", "mondariz", "morana", "mos", "neves", "nigran",
    "oia", "pazos de borben", "poio", "ponte caldelas", "ponteareas", "pontecesures",
    "pontevedra", "porrino", "portas", "redondela", "ribadumia", "rodeiro", "rosal",
    "salceda de caselas", "salvaterra de mino", "sanxenxo", "silleda", "soutomaior",
    "tomino", "tui", "valga", "vigo", "vila de cruces", "vilaboa", "vilagarcia de arousa",
    "vilanova de arousa"
]

PALABRAS_EMPLEO_ESTRICTO = [
    "oposic", "concurso", "convocatoria", "bases", "bolsa", "listaxe", "lista de espera",
    "prazas", "praza", "funcionario", "laboral", "interin", "seleccion", "tribunal",
    "admitidos", "exclu", "estabilizacion", "oferta de emprego", "oep", "subgrupo",
    "grupo a1", "grupo a2", "grupo c1", "grupo c2", "escala", "cuerpo", "corpo", "promocion interna"
]

def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")

def es_convocatoria_real(texto: str) -> bool:
    norm = normalizar(texto)
    prohibidas = [
        "sancionador", "multa", "notificar", "comparecencia", "expropiacion", 
        "cultivos mariños", "autorizacion ambiental", "aguas", "impacto ambiental",
        "concesion", "patente", "subvencion", "notificacion"
    ]
    if any(p in norm for p in prohibidas):
        return False
    return any(p in norm for p in PALABRAS_EMPLEO_ESTRICTO)

def detectar_destacado(texto: str) -> str:
    norm = normalizar(texto)
    if not es_convocatoria_real(texto):
        return ""
    if any(p in norm for p in ["auxiliar administrativo", "auxiliar administrativa", "auxiliares", "auxiliar de administracion", "subgrupo c2", "grupo c2"]):
        return "C2 · Aux. Admin"
    if any(p in norm for p in ["subgrupo c1", "grupo c1", "cuerpo administrativo", "corpo administrativo", "escala administrativa", "administrativo", "administrativa"]):
        if "procedimiento administrativo" not in norm and "procedemento administrativo" not in norm:
            return "C1 · Administrativo"
    return ""

def detectar_organismo(texto: str) -> str:
    norm = normalizar(texto)
    if "xunta de galicia" in norm or "conselleria" in norm or "sergas" in norm:
        return "Xunta de Galicia"
    if "deputacion" in norm or "diputacion" in norm:
        return "Deputación de Pontevedra"
    for entidad in ENTIDADES_PONTEVEDRA_GALICIA:
        if entidad not in ("xunta de galicia", "deputacion de pontevedra", "diputacion provincial de pontevedra"):
            if re.search(rf"\b{re.escape(entidad)}\b", norm):
                return f"Concello de {entidad.title()}"
    return "Administración Pública"

def cargar_historico() -> dict:
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            datos = json.load(f)
            items = datos.get("items", [])
            # Usar un diccionario con clave única basada en URL o título normalizado para evitar duplicados absolutos
            return {item.get("url", item["id"]): item for item in items}
    return {}

def fetch_boe(fecha: datetime) -> list:
    fecha_str = fecha.strftime("%Y%m%d")
    url = f"https://boe.es/datosabiertos/api/boe/sumario/{fecha_str}"
    resultados = []
    try:
        r = requests.get(url, headers={"Accept": "application/json", **HEADERS}, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        diarios = data.get("data", {}).get("sumario", {}).get("diario", [])
        if isinstance(diarios, dict):
            diarios = [diarios]

        for diario in diarios:
            secciones = diario.get("seccion", [])
            if isinstance(secciones, dict):
                secciones = [secciones]
            for sec in secciones:
                if sec.get("codigo") != "2B":
                    continue
                departamentos = sec.get("departamento", [])
                if isinstance(departamentos, dict):
                    departamentos = [departamentos]
                for dept in departamentos:
                    epigrafes = dept.get("epigrafe", [])
                    if isinstance(epigrafes, dict):
                        epigrafes = [epigrafes]
                    for epi in epigrafes:
                        items = epi.get("item", [])
                        if isinstance(items, dict):
                            items = [items]
                        for item in items:
                            titulo = item.get("titulo", "")
                            norm = normalizar(titulo)
                            if any(re.search(rf"\b{re.escape(ent)}\b", norm) for ent in ENTIDADES_PONTEVEDRA_GALICIA):
                                if es_convocatoria_real(titulo):
                                    doc_id = item.get("identificador", "")
                                    enlace = item.get("url_html", {})
                                    if isinstance(enlace, dict):
                                        enlace = enlace.get("#text", f"https://www.boe.es/diario_boe/txt.php?id={doc_id}")
                                    resultados.append({
                                        "id": f"BOE-{doc_id}",
                                        "fecha": fecha.strftime("%Y-%m-%d"),
                                        "boletin": "BOE",
                                        "organismo": detectar_organismo(titulo),
                                        "titulo": titulo.strip(),
                                        "url": enlace,
                                        "etiqueta_destacada": detectar_destacado(titulo)
                                    })
    except Exception as e:
        print(f"[BOE {fecha_str}] Error: {e}")
    return resultados

def fetch_dog(fecha: datetime) -> list:
    fecha_str = fecha.strftime("%Y%m%d")
    url = f"https://www.xunta.gal/diario-oficial-galicia/mostrarContenido.do?paginaCompleta=false&idEstado=5&rutaRelativa=true&ruta=/{fecha.year}/{fecha_str}/Secciones4_gl.html"
    resultados = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200 and "No existe" not in r.text and "Non existe" not in r.text:
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                titulo = " ".join(a.get_text().split())
                if len(titulo) < 25 or ".html" not in href:
                    continue
                if es_convocatoria_real(titulo):
                    full_url = urljoin("https://www.xunta.gal/diario-oficial-galicia/", href)
                    uid = f"DOG-{fecha_str}-{abs(hash(titulo)) % 10**8}"
                    resultados.append({
                        "id": uid,
                        "fecha": fecha.strftime("%Y-%m-%d"),
                        "boletin": "DOG",
                        "organismo": detectar_organismo(titulo),
                        "titulo": titulo,
                        "url": full_url,
                        "etiqueta_destacada": detectar_destacado(titulo)
                    })
    except Exception as e:
        print(f"[DOG {fecha_str}] Error: {e}")
    return resultados

def fetch_boppo(fecha: datetime) -> list:
    fecha_str = fecha.strftime("%Y-%m-%d")
    url = f"https://boppo.depo.gal/es?p_p_id=es_depo_boppo_web_portlet_BoppoPortlet&fecha={fecha_str}"
    resultados = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            titulo = " ".join(a.get_text().split())
            href = a["href"]
            if len(titulo) < 25:
                continue
            if es_convocatoria_real(titulo):
                full_url = urljoin("https://boppo.depo.gal", href)
                uid = f"BOPPO-{fecha_str}-{abs(hash(titulo)) % 10**8}"
                resultados.append({
                    "id": uid,
                    "fecha": fecha_str,
                    "boletin": "BOPPO",
                    "organismo": detectar_organismo(titulo),
                    "titulo": titulo,
                    "url": full_url,
                    "etiqueta_destacada": detectar_destacado(titulo)
                })
    except Exception as e:
        print(f"[BOPPO {fecha_str}] Error: {e}")
    return resultados

def main():
    existentes = cargar_historico()
    hoy = datetime.now()

    # Escanear los últimos 5 días
    for offset in range(5):
        dia = hoy - timedelta(days=offset)
        for item in fetch_boe(dia) + fetch_dog(dia) + fetch_boppo(dia):
            # Usar la URL como clave única para evitar duplicados exactos
            clave_unica = item["url"]
            if clave_unica not in existentes or existentes[clave_unica]["fecha"] < item["fecha"]:
                existentes[clave_unica] = item

    limite = (hoy - timedelta(days=45)).strftime("%Y-%m-%d")
    
    # Filtrar por fecha límite y asegurar que sean de empleo real
    filtrados = [
        v for v in existentes.values() 
        if v["fecha"] >= limite and (v.get("etiqueta_destacada") or es_convocatoria_real(v["titulo"]))
    ]
    
    # Ordenar por fecha descendente
    filtrados.sort(key=lambda x: (x["fecha"], bool(x.get("etiqueta_destacada"))), reverse=True)

    os.makedirs("docs", exist_ok=True)
    salida = {
        "actualizado": hoy.strftime("%d/%m/%Y %H:%M"),
        "total": len(filtrados),
        "items": filtrados
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print(f"Guardados {len(filtrados)} anuncios únicos y limpios de empleo.")

if __name__ == "__main__":
    main()
