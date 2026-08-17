# Buscador automático de alquiler (ZonaProp + Argenprop + MercadoLibre)

Revisa cada 3 horas si hay publicaciones nuevas en Rosario (Echesortu,
Centro, Abasto), 2 dormitorios, hasta $600.000, y te avisa por email.
Corre gratis en GitHub Actions, no necesitás dejar nada prendido.

## 1. Generar una contraseña de aplicación de Gmail

No se puede usar tu contraseña normal de Gmail para esto (Google no lo
permite), hay que generar una "contraseña de aplicación" específica:

1. Andá a **myaccount.google.com/security**.
2. Activá la **verificación en dos pasos** si todavía no la tenés
   activada (es un requisito para poder generar la contraseña de
   aplicación).
3. Buscá **"Contraseñas de aplicaciones"** (podés escribirlo en el
   buscador de arriba de esa misma página, o ir directo a
   myaccount.google.com/apppasswords).
4. Ponele un nombre cualquiera (ej. "scraper alquiler") y generala.
5. Google te muestra una contraseña de 16 letras (tipo `abcd efgh ijkl
   mnop`). Copiala sin espacios — es la que vas a usar, no la de tu
   cuenta.

Si no usás Gmail, decime qué proveedor de mail tenés y adapto el script
a su servidor SMTP (el de Gmail es el más simple de activar).

## 2. Subir este proyecto a GitHub

1. Creá un repo nuevo en GitHub (puede ser privado).
2. Subí todos estos archivos y carpetas tal cual están (incluyendo la
   carpeta oculta `.github/`).

## 3. Configurar los secrets

En el repo: **Settings → Secrets and variables → Actions → New repository secret**

- `EMAIL_USER`: tu dirección completa de Gmail (ej. `tucorreo@gmail.com`)
- `EMAIL_PASS`: la contraseña de aplicación de 16 letras del paso 1
- `EMAIL_TO`: a qué mail querés que lleguen los avisos (puede ser el
  mismo `EMAIL_USER` u otro distinto)

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
- Solo te manda un email cuando hay algo **nuevo** que matchea tus
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
