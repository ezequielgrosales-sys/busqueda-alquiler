"""
Scraper de alquileres — ZonaProp, MercadoLibre, RE/MAX + inmobiliarias
------------------------------------------------------------
Busca departamentos/casas nuevos que matcheen tus filtros y avisa por
email solo cuando aparece una publicación que no vio antes. Pensado
para correr cada pocas horas con GitHub Actions.

CONFIGURÁ TUS FILTROS ACÁ ABAJO (sección CONFIG). Para sumar una
inmobiliaria nueva, ver SITIOS_INMOBILIARIAS más abajo.
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
    "MercadoLibre": "https://inmuebles.mercadolibre.com.ar/departamentos-alquiler-rosario-2-dormitorios",
    "RE/MAX": "https://www.remax.com.ar/listings/rent?page=0&pageSize=48&sort=-createdAt&in:operationId=2&in:eStageId=0,1,2,3,4&in:typeId=1,2,3,4,5,6,7,8&locations=in:::460@rosario",
    # "Argenprop": "https://www.argenprop.com/departamentos/alquiler/rosario/2-dormitorios",
    # ^ Desactivado: Argenprop bloquea tanto pedidos simples como el
    # navegador headless (protección anti-bot fuerte, tipo Cloudflare).
    # Descomentá esta línea si en algún momento querés reintentarlo.
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
    """Extrae un número de precio en pesos de un string tipo '$ 450.000'.
    Si detecta que el precio está en dólares (USD/u$s), devuelve None -
    no lo podemos comparar directo contra PRECIO_MAXIMO (que es en
    pesos), así que lo dejamos pasar sin filtrar por precio."""
    texto_limpio = texto.replace("\xa0", " ")
    if re.search(r"u\$s|usd", texto_limpio, re.IGNORECASE):
        return None
    match = re.search(r"\$\s?([\d.,]+)", texto_limpio)
    if not match:
        return None
    solo_digitos = re.sub(r"[^\d]", "", match.group(1))
    if not solo_digitos:
        return None
    try:
        return int(solo_digitos)
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
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="es-AR",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={"Accept-Language": "es-AR,es;q=0.9,en;q=0.8"},
            )
            # Camufla la señal más común que usan los sitios para detectar
            # navegadores automatizados (navigator.webdriver = true).
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            page.goto(url, timeout=35000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass  # algunos sitios nunca llegan a "networkidle", seguimos igual
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()

        # Diagnóstico: si el HTML es corto o tiene palabras típicas de una
        # pantalla anti-bot, probablemente el sitio también bloqueó al
        # navegador headless (no es un error nuestro, es protección del sitio).
        texto_lower = html.lower()
        señales_bloqueo = ["access denied", "attention required", "cloudflare", "are you human", "verificando"]
        if len(html) < 5000 or any(s in texto_lower for s in señales_bloqueo):
            print(f"[WARN] La página parece haber bloqueado también al navegador headless ({len(html)} bytes)")

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
        clave = url.split("?")[0].split("#")[0].rstrip("/")
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

        # El código MLA-xxxxxxx es el identificador real y estable de la
        # publicación. El resto del link trae un "tracking_id" que
        # MercadoLibre genera al azar en cada carga de página — si lo
        # usábamos como id, la misma publicación parecía "nueva" cada vez.
        match_id = re.search(r"MLA-\d+", url)
        id_estable = match_id.group(0) if match_id else url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]

        # Para el link que mandamos por mail, sacamos toda la basura de
        # tracking (todo lo que viene después de "?" o "#").
        url_limpia = url.split("?")[0].split("#")[0]

        resultados.append({
            "id": id_estable,
            "url": url_limpia,
            "titulo": titulo[:150],
            "precio": precio,
        })
    return resultados


def parse_remax(html: str) -> list[dict]:
    # Las publicaciones individuales de RE/MAX viven en /listings/<slug>
    # (sin "?", que es lo que usan las páginas de búsqueda como
    # /listings/rent?page=0&...). Ese "$" al final del patrón es lo que
    # separa una cosa de la otra.
    return extraer_por_patron_de_link(html, "https://www.remax.com.ar", r"/listings/[a-z0-9-]+$")


PARSERS = {
    "ZonaProp": parse_zonaprop,
    "Argenprop": parse_argenprop,
    "MercadoLibre": parse_mercadolibre,
    "RE/MAX": parse_remax,
}

# ==================== INMOBILIARIAS (patrón genérico) =================
# Estos sitios no necesitan una función de parser propia: alcanza con
# decirle al extractor genérico (a) la URL de la página de alquileres y
# (b) cómo reconocer el link de una publicación individual. Para sumar
# una inmobiliaria nueva, alcanza con agregar una entrada acá — no hace
# falta escribir código nuevo, salvo que el sitio sea un caso raro.
SITIOS_INMOBILIARIAS = {
    "Bertollo": {
        "url": "https://www.bertollo.com.ar/Alquiler",
        "base": "https://www.bertollo.com.ar",
        "patron": r"/p/\d+-",
    },
    "COSA Propiedades": {
        "url": "https://www.cosapropiedades.com/Alquiler",
        "base": "https://www.cosapropiedades.com",
        "patron": r"/p/\d+-",
    },
    "Dunod": {
        "url": "https://dunod.com.ar/inmuebles/?status%5B%5D=alquiler",
        "base": "https://dunod.com.ar",
        "patron": r"/inmueble/[a-z0-9-]+/?$",
    },
    "Eigen": {
        "url": "https://eigen.com.ar/alquiler/",
        "base": "https://eigen.com.ar",
        "patron": r"/property/[a-z0-9-]+/?$",
    },
    "Inmobiliaria Echesortu": {
        "url": "https://inmobiliariaechesortu.com/operacion/alquileres/",
        "base": "https://inmobiliariaechesortu.com",
        "patron": r"/propiedades/[a-z0-9-]+/?$",
    },
    "Escala Propiedades": {
        "url": "https://www.escalapropiedades.com.ar/Alquiler",
        "base": "https://www.escalapropiedades.com.ar",
        "patron": r"/p/\d+-",
    },
    "GANA Propiedades": {
        "url": "https://www.ganapropiedades.com.ar/Alquiler",
        "base": "https://www.ganapropiedades.com.ar",
        "patron": r"/p/\d+-",
    },
    "Imperia Propiedades": {
        "url": "https://imperiapropiedades.com/En-alquiler",
        "base": "https://imperiapropiedades.com",
        "patron": r"/propiedad-\d+-",
    },
    "EMA Bienes Raíces": {
        "url": "https://www.ema.ar/estado/en-alquiler/",
        "base": "https://www.ema.ar",
        "patron": r"/propiedad/\d+_[a-z0-9-]+/?$",
    },
    "Inmobiliaria M&M": {
        "url": "https://www.inmobiliariamym.com.ar/Alquiler",
        "base": "https://www.inmobiliariamym.com.ar",
        "patron": r"/p/\d+-",
    },
    "Enz Propiedades": {
        "url": "https://www.enzpropiedades.com.ar/Alquiler",
        "base": "https://www.enzpropiedades.com.ar",
        "patron": r"/p/\d+-",
    },
    "SIGMA": {
        "url": "https://www.sigmapropiedades.com.ar/Alquiler",
        "base": "https://www.sigmapropiedades.com.ar",
        "patron": r"/p/\d+-",
    },
    "Ideal Propiedades": {
        "url": "https://www.idealpropiedades.com.ar/Alquiler",
        "base": "https://www.idealpropiedades.com.ar",
        "patron": r"/p/\d+-",
    },
    "RCS Inmobiliaria": {
        "url": "https://rcsinmobiliaria.com.ar/site/properties/rental",
        "base": "https://rcsinmobiliaria.com.ar",
        "patron": r"/site/properties/\d+/[a-z0-9-]+",
    },
}

# RE/MAX no tiene filtro de dormitorios en la URL de búsqueda (a
# diferencia de los otros sitios), así que ese filtro se aplica acá,
# sobre el texto de cada publicación, como chequeo extra.
NUMEROS_TEXTO = {1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco"}


def matches_dormitorios(texto: str) -> bool:
    texto = texto.lower()
    if re.search(rf"{DORMITORIOS}\s*dorm", texto):
        return True
    palabra = NUMEROS_TEXTO.get(DORMITORIOS)
    return bool(palabra and f"{palabra} dormitorio" in texto)


SITIOS_CON_FILTRO_DORMITORIOS = {"RE/MAX"} | set(SITIOS_INMOBILIARIAS.keys())


# ============================ MAIN LOGIC ==============================

def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2))


def procesar_listings(sitio: str, listings: list[dict], seen: set, nuevos_avisos: list) -> None:
    """Aplica los filtros (barrio, dormitorios, precio) a los resultados
    de un sitio y agrega a nuevos_avisos los que matcheen y no se
    hayan visto antes. Modifica 'seen' y 'nuevos_avisos' in-place."""
    for item in listings:
        uid = f"{sitio}:{item['id']}"
        if uid in seen:
            continue

        # Filtro de barrio (si no matchea ninguno de tus barrios, se ignora)
        if not matches_barrio(item["titulo"]):
            seen.add(uid)  # lo marcamos visto igual para no re-chequearlo
            continue

        # Filtro extra de dormitorios, solo para sitios que no lo
        # soportan como parámetro de búsqueda (ver SITIOS_CON_FILTRO_DORMITORIOS)
        if sitio in SITIOS_CON_FILTRO_DORMITORIOS and not matches_dormitorios(item["titulo"]):
            seen.add(uid)
            continue

        # Filtro de precio (si no se pudo leer el precio, lo dejamos pasar
        # para que lo revises vos manualmente)
        if item["precio"] and item["precio"] > PRECIO_MAXIMO:
            seen.add(uid)
            continue

        seen.add(uid)
        nuevos_avisos.append((sitio, item))


def main() -> None:
    seen = load_seen()
    nuevos_avisos = []

    # --- Sitios con parser propio (portales grandes) ---
    for sitio, url in SEARCH_URLS.items():
        print(f"--- Revisando {sitio} ---")
        parser = PARSERS[sitio]
        html = fetch(url)
        listings = parser(html) if html else []

        if not listings:
            print("  0 resultados con pedido rápido, reintentando con navegador headless...")
            html = fetch_with_playwright(url)
            listings = parser(html) if html else []

        print(f"  {len(listings)} publicaciones encontradas en la búsqueda")
        procesar_listings(sitio, listings, seen, nuevos_avisos)

    # --- Inmobiliarias (patrón genérico) ---
    for sitio, cfg in SITIOS_INMOBILIARIAS.items():
        print(f"--- Revisando {sitio} ---")
        html = fetch(cfg["url"])
        listings = extraer_por_patron_de_link(html, cfg["base"], cfg["patron"]) if html else []

        if not listings:
            print("  0 resultados con pedido rápido, reintentando con navegador headless...")
            html = fetch_with_playwright(cfg["url"])
            listings = extraer_por_patron_de_link(html, cfg["base"], cfg["patron"]) if html else []

        print(f"  {len(listings)} publicaciones encontradas en la búsqueda")
        procesar_listings(sitio, listings, seen, nuevos_avisos)

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
