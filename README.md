# MSG PDF Converter

[![CI](https://github.com/sandavdesigns/pdf-convert/actions/workflows/ci.yml/badge.svg)](https://github.com/sandavdesigns/pdf-convert/actions/workflows/ci.yml)

Eine kostenlose, selbst gehostete Webanwendung, die Outlook-`.msg`-Dateien in lesbare PDFs umwandelt. Die ursprünglichen E-Mail-Anlagen werden als echte Dateianlagen in die PDF eingebettet.

## Funktionen

- Eine oder mehrere `.msg`-Dateien per Browser hochladen
- Mailkopf und formatierter Nachrichtentext als A4-PDF
- Originalanlagen unverändert in der PDF eingebettet
- Optionale Einbettung der ursprünglichen `.msg`
- Mehrfachkonvertierung als ZIP-Download
- Keine dauerhafte Speicherung und keine Cloud-Dienste
- Externe Bilder und Tracking-Inhalte werden beim Rendern blockiert
- Für Docker und Portainer vorbereitet

> Die erzeugten Dateien sind normale PDFs mit eingebetteten Anlagen. Eine formale PDF/A-3-Validierung findet nicht statt.

## Portainer

### Stack direkt aus diesem Repository

1. In Portainer **Stacks** und anschließend **Add stack** öffnen.
2. **Repository** als Build-Methode auswählen.
3. Repository-URL eintragen:

   ```text
   https://github.com/sandavdesigns/pdf-convert.git
   ```

4. Als Compose-Pfad `compose.yaml` eintragen.
5. Optional die Umgebungsvariablen anpassen:

   - `PDF_CONVERT_PORT=8080`
   - `MAX_UPLOAD_MB=100`

6. Stack deployen und anschließend `http://SERVER-IP:8080` öffnen.

Portainer muss das Image aus dem Repository bauen können. Falls die verwendete Portainer-Umgebung keine Compose-Builds unterstützt, das Image zunächst per CLI bauen oder in eine Registry veröffentlichen.

## Docker Compose

```bash
docker compose up -d --build
```

Danach ist die Anwendung unter [http://localhost:8080](http://localhost:8080) erreichbar.

Logs und Status:

```bash
docker compose logs -f
docker compose ps
```

## Konfiguration

| Variable | Standard | Bedeutung |
| --- | ---: | --- |
| `PDF_CONVERT_PORT` | `8080` | Veröffentlichter Host-Port |
| `MAX_UPLOAD_MB` | `100` | Maximale Gesamtgröße eines Uploads |

Die Anwendung benötigt kein Volume. Temporäre Dateien liegen ausschließlich im `/tmp`-Dateisystem des Containers und werden nach jeder Konvertierung entfernt.

## Lokale Entwicklung

Voraussetzungen: Python 3.11 oder neuer sowie die nativen WeasyPrint-Bibliotheken.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
flask --app wsgi run --debug --port 8080
```

Unter Windows wird die virtuelle Umgebung mit `.venv\Scripts\activate` aktiviert.

Tests:

```bash
pytest
```

## Technischer Ablauf

1. `extract-msg` liest Maildaten und Anlagen aus der MSG-Datei.
2. Aktive und externe Inhalte werden aus dem Mail-HTML entfernt.
3. WeasyPrint rendert Mailkopf und Nachricht als PDF.
4. `pikepdf` bettet die Originalanlagen und optional die MSG-Datei ein.
5. Der Browser lädt das Ergebnis direkt herunter.

## Hinweise

- Eingebettete Anlagen werden am zuverlässigsten in Adobe Acrobat Reader oder einem anderen PDF-Programm mit Anlagenbereich angezeigt. Manche Browser-PDF-Ansichten blenden diesen Bereich aus.
- Passwortgeschützte, beschädigte oder exotische MSG-Varianten können nicht in jedem Fall gelesen werden.
- Das Einbetten von Dateien in eine PDF macht deren Inhalt nicht automatisch sicher. Anlagen sollten weiterhin mit einem geeigneten Virenscanner geprüft werden.

## Lizenz

MIT
