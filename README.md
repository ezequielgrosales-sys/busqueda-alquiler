# Buscador automático de alquiler (ZonaProp + Argenprop + MercadoLibre)

Revisa cada 3 horas si hay publicaciones nuevas en Rosario (Echesortu,
Centro, Abasto), 2 dormitorios, hasta $600.000, y te avisa por WhatsApp.
Corre gratis en GitHub Actions, no necesitás dejar nada prendido.

## 1. Conseguir el API key de WhatsApp (CallMeBot, gratis)

1. Agregá el contacto **+34 644 51 95 23** a tu WhatsApp.
2. Mandale el mensaje exacto: `I allow callmebot to add me`
3. En unos segundos te responde con tu **apikey** (un número). Guardalo.

## 2. Subir este proyecto a GitHub

1. Creá un repo nuevo en GitHub (puede ser privado).
2. Subí todos estos archivos y carpetas tal cual están (incluyendo la
   carpeta oculta `.github/`).

## 3. Configurar los secrets

En el repo: **Settings → Secrets and variables → Actions → New repository secret**

- `CALLMEBOT_PHONE`: tu número con código de país, sin `+` ni espacios
  (ej. `5493411234567`)
- `CALLMEBOT_APIKEY`: el número que te dio CallMeBot en el paso 1

## 4. Activar el workflow

Andá a la pestaña **Actions** del repo y habilitalo si te lo pide. Con eso
ya queda corriendo solo cada 3 horas. También podés ir a **Actions →
Buscar alquileres nuevos → Run workflow** para probarlo manualmente ya
mismo, sin esperar.

## 5. Ajustar filtros

Todo se configura al principio de `scraper.py`:

```python
BARRIOS = ["echesortu", "centro", "abasto"]
PRECIO_MAXIMO = 600_000
DORMITORIOS = 2
```

Si cambiás `DORMITORIOS`, también tenés que actualizar a mano las URLs
en `SEARCH_URLS` (cada sitio arma el link distinto):

- **ZonaProp**: `departamentos-alquiler-rosario-N-habitaciones.html`
- **Argenprop**: `departamentos/alquiler/rosario/N-dormitorios`
- **MercadoLibre**: `departamentos-alquiler-rosario-N-dormitorios`

Podés armar esas URLs directamente buscando en cada sitio con los
filtros que quieras y copiando el link que te queda.

## Cómo funciona

- Cada corrida trae los resultados de la búsqueda en los 3 sitios.
- Filtra por barrio (que el título/dirección contenga alguno de tus
  barrios) y por precio.
- Guarda en `data/seen.json` los IDs de las publicaciones que ya
  procesó, así no te vuelve a avisar de las mismas.
- Solo te manda WhatsApp cuando hay algo **nuevo** que matchea tus
  filtros.

## Si un sitio deja de andar (importante)

ZonaProp y Argenprop cambian el HTML de su página de tanto en tanto, y
a veces bloquean pedidos que no vienen de un navegador real. Si notás
que un sitio en particular dejó de traer resultados (vas a ver "0
publicaciones encontradas" en los logs de Actions):

1. Abrí el link de búsqueda de ese sitio en tu navegador.
2. Click derecho → "Ver código fuente de la página" (o F12 → pestaña
   Elements).
3. Buscá cómo está armada cada tarjeta de resultado (una publicación).
4. Ajustá el selector correspondiente en `scraper.py`, en la función
   `parse_zonaprop`, `parse_argenprop` o `parse_mercadolibre`.

Si un sitio empieza a devolver página vacía incluso con el selector
bien puesto, es porque pasó a requerir JavaScript para mostrar los
resultados — en ese caso avisame y lo migramos a Playwright (navegador
headless), que corre igual gratis en GitHub Actions pero es un poco
más pesado de configurar.

## Ver el historial de corridas

Pestaña **Actions** del repo → click en cualquier corrida → **check**
→ ahí ves qué encontró cada vez, útil para debuggear.
