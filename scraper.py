"""
Scraper de alquileres — ZonaProp, Argenprop y MercadoLibre
------------------------------------------------------------
Busca departamentos/casas nuevos que matcheen tus filtros y avisa por
WhatsApp (vía CallMeBot) solo cuando aparece una publicación que no
vio antes. Pensado para correr cada pocas horas con GitHub Actions.

CONFIGURÁ TUS FILTROS ACÁ ABAJO (sección CONFIG).
"""

import json
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ============================== CONFIG ==============================

# Barrios que te interesan (en minúscula, sin tildes). El scraper busca
# estas palabras en el título/dirección de cada publicación.
BARRIOS = ["echesortu", "centro", "abasto"]

# Precio máximo en pesos argentinos
PRECIO_MAXIMO = 600_000

# Dormitorios buscados
DORMITORIOS = 2

# URLs base de búsqueda (ya configuradas con dormitorios=2 y ciudad=Rosario).
# Si cambiás DORMITORIOS arriba, actualizá también estos links a mano
# (cada sitio arma la URL distinto).
SEARCH_URLS = {
    "ZonaProp": "https://www.zonaprop.com.ar/departamentos-alquiler-rosario-2-habitaciones.html",
    "Argenprop": "https://www.argenprop.com/departamentos/alquiler/rosario/2-dormitorios",
    "MercadoLibre": "https://inmuebles.mercadolibre.com.ar/departamentos-alquiler-rosario-2-dormitorios",
}

# Archivo donde se guardan los IDs de publicaciones ya vistas (no tocar)
SEEN_FILE = Path(__file__).parent / "data" / "seen.json"

# ============================== EMAIL =================================
# Notificaciones por email vía Gmail SMTP. Necesitás las variables de
# entorno EMAIL_USER, EMAIL_PASS (contraseña de aplicación de Gmail,
# no tu contraseña normal) y EMAIL_TO (a quién le llega el aviso).
# Ver README para cómo generar la contraseña de aplicación.

def send_email(asunto: str, mensaje: str) -> None:
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    destinatario = os.environ.get("EMAIL_TO", user)

    if not user or not password:
        print("[WARN] Faltan EMAIL_USER / EMAIL_PASS, no se envía email.")
        print(mensaje)
        return

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = user
    msg["To"] = destinatario
    msg.set_content(mensaje)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        print("[Email] enviado a", destinatario)
    except Exception as e:
        print("[ERROR] No se pudo enviar el email:", e)


# ============================ HELPERS ================================

def matches_barrio(texto: str) -> bool:
    texto = texto.lower()
    return any(barrio in texto for barrio in BARRIOS)


def parse_precio(texto: str) -> int | None:
    """Extrae un número de precio en pesos de un string tipo '$ 450.000'."""
    match = re.search(r"\$\s?([\d.]+)", texto.replace("\xa0", " "))
    if not match:
        return None
    try:
        return int(match.group(1).replace(".", ""))
    except ValueError:
        return None


def fetch(url: str) -> str | None:
    """Intenta traer la página con un pedido simple (rápido). Si el sitio
    lo bloquea (403, contenido vacío/muy corto), reintenta con un
    navegador headless (Playwright), que es más lento pero más difícil
    de bloquear porque ejecuta JavaScript como un navegador real."""
    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Referer": "https://www.google.com/",
    }
    try:
        r = requests.get(url, headers=browser_headers, timeout=25)
        if r.status_code == 200 and len(r.text) > 3000:
            return r.text
        print(f"[WARN] {url} devolvió status {r.status_code} / {len(r.text)} bytes — probando con navegador headless")
    except Exception as e:
        print(f"[WARN] fallo pedido simple a {url}: {e} — probando con navegador headless")

    return fetch_with_playwright(url)


def fetch_with_playwright(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] Playwright no está instalado, no se pudo usar como respaldo.")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="es-AR",
            )
            page.goto(url, timeout=35000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  # deja que termine de cargar contenido dinámico
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"[ERROR] Playwright también falló para {url}: {e}")
        return None


# ======================== PARSERS POR SITIO ==========================
# NOTA: estos sitios cambian su HTML seguido y algunos usan JavaScript
# para renderizar resultados. Si un sitio deja de devolver resultados,
# probá abrirlo en el navegador -> "Ver código fuente" -> buscar cómo
# están armadas las tarjetas de resultado, y ajustá el selector acá.
# Ver README, sección "Si un sitio deja de andar".

def extraer_por_patron_de_link(html: str, base_url: str, patron_id: str) -> list[dict]:
    """Busca todos los <a> cuyo href matchee patron_id (identifica una
    publicación individual) y arma el resultado con el texto de un
    contenedor cercano (para sacar precio/título aproximados)."""
    soup = BeautifulSoup(html, "html.parser")
    vistos = set()
    resultados = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(patron_id, href):
            continue
        url = href if href.startswith("http") else urljoin(base_url, href)
        clave = url.split("?")[0].rstrip("/")
        if clave in vistos:
            continue
        vistos.add(clave)

        # Subimos un par de niveles en el árbol HTML para capturar la
        # tarjeta completa (con precio, dirección, etc.), no solo el link.
        contenedor = a
        for _ in range(3):
            if contenedor.parent is not None:
                contenedor = contenedor.parent
        titulo = contenedor.get_text(" ", strip=True)

        resultados.append({
            "id": clave.split("/")[-1],
            "url": url,
            "titulo": titulo[:200],
            "precio": parse_precio(titulo),
        })
    return resultados


def parse_zonaprop(html: str) -> list[dict]:
    # Los links de publicaciones de ZonaProp terminan en un número de
    # aviso largo seguido de ".html", ej: .../pieza-en-alquiler-45123456.html
    return extraer_por_patron_de_link(html, "https://www.zonaprop.com.ar", r"-\d{6,}\.html")


def parse_argenprop(html: str) -> list[dict]:
    # Los links de publicaciones de Argenprop terminan en "--" seguido
    # de un número de aviso, ej: .../departamento-en-alquiler--12345678
    return extraer_por_patron_de_link(html, "https://www.argenprop.com", r"--\d{5,}")


def parse_mercadolibre(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    resultados = []
    for card in soup.select("li.ui-search-layout__item, div.ui-search-result__wrapper"):
        link_tag = card.find("a", href=True)
        if not link_tag:
            continue
        url = link_tag["href"]
        titulo = card.get_text(" ", strip=True)
        precio = parse_precio(titulo)
        resultados.append({
            "id": url.split("?")[0].rstrip("/").split("/")[-1],
            "url": url,
            "titulo": titulo[:150],
            "precio": precio,
        })
    return resultados


PARSERS = {
    "ZonaProp": parse_zonaprop,
    "Argenprop": parse_argenprop,
    "MercadoLibre": parse_mercadolibre,
}


# ============================ MAIN LOGIC ==============================

def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2))


def main() -> None:
    seen = load_seen()
    nuevos_avisos = []

    for sitio, url in SEARCH_URLS.items():
        print(f"--- Revisando {sitio} ---")
        html = fetch(url)
        if not html:
            continue

        parser = PARSERS[sitio]
        listings = parser(html)
        print(f"  {len(listings)} publicaciones encontradas en la búsqueda")

        for item in listings:
            uid = f"{sitio}:{item['id']}"
            if uid in seen:
                continue

            # Filtro de barrio (si no matchea ninguno de tus barrios, se ignora)
            if not matches_barrio(item["titulo"]):
                seen.add(uid)  # lo marcamos visto igual para no re-chequearlo
                continue

            # Filtro de precio (si no se pudo leer el precio, lo dejamos pasar
            # para que lo revises vos manualmente)
            if item["precio"] and item["precio"] > PRECIO_MAXIMO:
                seen.add(uid)
                continue

            seen.add(uid)
            nuevos_avisos.append((sitio, item))

    if nuevos_avisos:
        lineas = [f"🏠 {len(nuevos_avisos)} publicación(es) nueva(s) que matchean tu búsqueda:\n"]
        for sitio, item in nuevos_avisos:
            precio_txt = f"${item['precio']:,}".replace(",", ".") if item["precio"] else "precio no detectado"
            lineas.append(f"[{sitio}] {precio_txt}\n{item['url']}\n")
        mensaje = "\n".join(lineas)
        print(mensaje)
        send_email(f"🏠 {len(nuevos_avisos)} alquiler(es) nuevo(s) encontrado(s)", mensaje)
    else:
        print("Sin novedades esta vez.")

    save_seen(seen)


if __name__ == "__main__":
    main()
