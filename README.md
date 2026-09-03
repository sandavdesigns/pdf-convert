<p>
  <img src="app/static/brand/logo.svg" alt="PDF Werkzeuge" width="360">
</p>

[![CI](https://github.com/sandavdesigns/pdf-convert/actions/workflows/ci.yml/badge.svg)](https://github.com/sandavdesigns/pdf-convert/actions/workflows/ci.yml)

Eine kostenlose, selbst gehostete Werkzeugzentrale für interne PDF-Abläufe. Sie archiviert Outlook-`.msg`-Dateien, bringt zentral hinterlegte Kopfbögen auf PDFs auf und trennt Dokumente nach einer frei wählbaren Seitenzahl.

## Funktionen

- Eine oder mehrere `.msg`-Dateien per Browser hochladen
- Mailkopf und formatierter Nachrichtentext als A4-PDF
- Einzelne PDFs werden als `YYYY-MM-DD Absender Betreff.pdf` benannt; der Betreff ist auf 30 Zeichen begrenzt
- Sammeldownloads erhalten einen eindeutigen Namen wie `2026-02-05-154782.zip`
- Originalanlagen unverändert in der PDF eingebettet
- Optionaler Einzel-Download von PDF und zusätzlich separat abgelegten Originalanlagen
- Inline-Bilder aus Mailtext und Signaturen werden dargestellt, aber nicht zusätzlich als PDF-Anlage geführt
- Eingebettete Outlook-Nachrichten werden als `.msg` übernommen
- Microsoft-365-/SharePoint-Webanlagen bleiben als `.url`-Verknüpfung erhalten, wenn die MSG selbst keine Dateibytes enthält
- Optionale Einbettung der ursprünglichen `.msg`
- Mehrfachkonvertierung als ZIP-Download
- Keine dauerhafte Speicherung und keine Cloud-Dienste
- Externe Bilder und Tracking-Inhalte werden beim Rendern blockiert
- Für Docker und Portainer vorbereitet
- Sachliche Werkzeugnavigation für MSG-Konvertierung, Kopfbögen und PDF-Aufteilung
- Passwortgeschützte Kopfbogen-Verwaltung mit dauerhafter Speicherung im Docker-Volume
- Kopfbogen auf jeder Seite, nur auf Seite 1 oder alle frei wählbaren N Seiten
- PDF nach einer festgelegten Seitenanzahl trennen und als ZIP herunterladen

> Die erzeugten Dateien sind normale PDFs mit eingebetteten Anlagen. Eine formale PDF/A-3-Validierung findet nicht statt.

## Portainer

Portainer muss dieses Repository nicht selbst bauen. Der Stack verwendet das
fertige Image `ghcr.io/sandavdesigns/pdf-convert:latest`.

### Image einmalig veröffentlichen

1. In GitHub **Actions** öffnen.
2. Den Workflow **Build container image** auswählen.
3. **Run workflow** auf dem Branch `main` starten.
4. Nach erfolgreichem Lauf das Paket `pdf-convert` im GitHub-Profil öffnen und
   unter **Package settings → Change visibility** auf **Public** stellen.

Öffentliche GHCR-Images können von Portainer ohne Registry-Zugang geladen werden.

### Stack direkt aus diesem Repository

1. In Portainer **Stacks** und anschließend **Add stack** öffnen.
2. **Repository** als Build-Methode auswählen.
3. Repository-URL eintragen:

   ```text
   https://github.com/sandavdesigns/pdf-convert.git
   ```

4. Als Repository-Referenz `main` und als Compose-Pfad `docker-compose.yml` eintragen.
5. **Re-pull image** aktivieren.
6. Optional die Umgebungsvariablen anpassen:

   - `PDF_CONVERT_PORT=8080`
   - `MAX_UPLOAD_MB=100`
   - `LETTERHEAD_ADMIN_PASSWORD=ein-langes-sicheres-kennwort`
   - `APP_SECRET_KEY=ein-langer-zufaelliger-wert`

7. Stack deployen und anschließend `http://SERVER-IP:8080` öffnen.

## Docker Compose

```bash
docker compose up -d
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
| `LETTERHEAD_ADMIN_PASSWORD` | leer | Kennwort für die unauffällig verlinkte Kopfbogen-Verwaltung; leer deaktiviert die Anmeldung |
| `APP_SECRET_KEY` | aus dem Kennwort abgeleitet | Signiert die Verwaltungssitzung; ein eigener langer Zufallswert wird empfohlen |
| `DATA_DIR` | `/data` im Compose-Stack | Verzeichnis für Kopfbogen-Datenbank und PDF-Vorlagen |

Der Compose-Stack legt das benannte Volume `pdf-convert-data` an. Nur die administrativ hochgeladenen Kopfbögen und deren Datenbank bleiben dort dauerhaft gespeichert. Zu verarbeitende MSG- und PDF-Dateien liegen weiterhin ausschließlich im Arbeitsspeicher oder im temporären `/tmp`-Dateisystem und werden nach jeder Verarbeitung entfernt.

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
5. Auf Wunsch startet der Browser für PDF und Originalanlagen jeweils einen eigenen Download.
6. Das Kopfbogen-Werkzeug skaliert die erste Seite der gewählten Vorlage auf die Zielseite und bringt sie als sichtbare Ebene auf.
7. Das Trennwerkzeug erzeugt nummerierte PDF-Teile mit eindeutigen Seitenbereichen und fasst sie als ZIP zusammen.
8. Der Browser lädt das Ergebnis direkt herunter.

## Hinweise

- Eingebettete Anlagen werden am zuverlässigsten in Adobe Acrobat Reader oder einem anderen PDF-Programm mit Anlagenbereich angezeigt. Manche Browser-PDF-Ansichten blenden diesen Bereich aus.
- Beim separaten Herunterladen kann der Browser einmalig um Erlaubnis für mehrere Downloads bitten.
- Als Kopfbogen wird die erste Seite der administrativ hinterlegten PDF-Vorlage verwendet.
- Bei „Alle N Seiten“ beginnt die Folge immer auf Seite 1, beispielsweise bei N = 3 auf den Seiten 1, 4, 7 usw.
- Passwortgeschützte, beschädigte oder exotische MSG-Varianten können nicht in jedem Fall gelesen werden.
- Das Einbetten von Dateien in eine PDF macht deren Inhalt nicht automatisch sicher. Anlagen sollten weiterhin mit einem geeigneten Virenscanner geprüft werden.

## Lizenz

MIT
