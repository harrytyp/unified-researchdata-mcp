# GUI Bundle Override (NOMAD Startseite: TGA-Karte)

## Was ist das?

Ein Patch auf dem minifizierten NOMAD-GUI-Bundle
`main.d7847511.chunk.js` (React/Webpack, aus `ghcr.io/fairmat-nfdi/nomad-distro-template:main`).
Er fügt auf der NOMAD-Startseite (About-Seite, `/nomad-oasis/gui/`) **ganz oben**,
direkt unter dem `meta.description`-Markdown, eine TGA-Karte ein:

- Indigo-Gradient (NOMAD-Primärfarbe), Titel **TGA Measurement Requests**
- Link auf das TGA-Request-Formular: https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/
- Eingefügt als weiteres Grid-Item (`Object(ve.jsx)(Xs.a,...)`) zwischen dem
  Markdown-Item und der InfoCard „Interactive Search" im `children`-Array
  der Home-Komponente.

## Warum?

`meta.description` wird von react-markdown gerendert, das HTML escapt.
Die Home-Karten („Interactive Search" usw.) sind hartkodierte InfoCards im
minifizierten Bundle. Eine eigene hübsche Karte gibt es nur per Bundle-Patch.

## Dateien

- `main.d7847511.chunk.js` - gepatchtes Bundle (aktiv im Container via bind-mount)
- `patch_gui3.py` - reproduzierbares Patch-Skript (liest Original, schreibt Patch)
- Dieses README

## Wie ist es verdrahtet?

`nomad/docker-compose.yaml`, Service `app`, volumes:
bind-mount der gepatchten Datei auf
`/opt/venv/lib/python3.12/site-packages/nomad/app/static/gui/static/js/main.d7847511.chunk.js`
(read-only). NOMAD generiert beim App-Start das Laufzeit-Verzeichnis
`/app/run/gui_configured/` aus diesen Statics; daraus serviert der App-Server.
Nach einem `docker compose up -d`/`restart` wird `gui_configured` automatisch
aus der gemounteten (gepatchten) Datei neu erzeugt.

## Wichtig bei NOMAD-Update (neues Distro-Image)

- Der Hash im Dateinamen (`d7847511`) ändert sich bei GUI-Neubauten.
  Dann: neuen Dateinamen im Compose-Mount und hier eintragen, Patch neu erzeugen:
  1. Original aus dem neuen Image holen:
     `docker cp nomad_oasis_app:/opt/venv/lib/python3.12/site-packages/nomad/app/static/gui/static/js/main.<NEUERHASH>.chunk.js ./main.<NEUERHASH>.chunk.js`
  2. `GUI_JS=main.<NEUERHASH>.chunk.js GUI_JS_OUT=main.<NEUERHASH>.chunk.js python3 patch_gui3.py`
     (Skript nimmt den Hash nicht hart, nur der Einfüge-Marker muss noch existieren;
     falls die Home-Komponente umgebaut wurde, Marker in patch_gui3.py anpassen)
  3. Syntax lokal pruefen: `node --check main.<NEUERHASH>.chunk.js`
  4. Datei einspielen, Compose-Mount + README aktualisieren.

## Verifikation

- `node --check main.d7847511.chunk.js` => valide
- Playwright gegen https://researchmcp.duckdns.org/nomad-oasis/gui/:
  Karte „TGA Measurement Requests" vorhanden, kein JS-Fehler, Link ok.
- GUI-Startseite inhaltlich identisch bis auf die neue Karte (kein weiterer Eingriff).
