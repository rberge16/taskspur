# Taktspur (Neubau)

Lokale Trainingsplanung: Kalender, Pläne/Phasen, Workout-Editor, Koppeleinheiten, Intervals.icu-Export.
FastAPI + SQLite + Vanilla-JS (kein Build-Schritt). Läuft nur auf **http://127.0.0.1:8775**.

## Start
- Windows: `start-taktspur.bat`
- Linux/Raspberry Pi: `./start-taktspur.sh` (Dienst: `deploy/taktspur.service`)

## Daten
Eigene Datenbank `taktspur2.sqlite3` im Datenordner (`TAKTSPUR_DATA_DIR`, sonst Benutzer-Datenordner).
Die alte `taktspur.sqlite3` wird nie angefasst. Vor jeder Migration wird ein Backup angelegt (14 aufbewahrt).
API-Schlüssel liegen verschlüsselt in der DB, der Schlüssel dazu in `secret.key` – beides nicht in Git/ZIP.

## Geplante Workouts ↔ Intervals.icu
Nur in Taktspur geplante Workouts gehen an Intervals.icu: beim Speichern gesendet, bei Änderung aktualisiert, beim Löschen dort entfernt (Einstellungen › „automatisch abgleichen“, Standard an; ohne Verbindung passiert nichts). Ist die Option aus, werden bereits übertragene Workouts trotzdem nachgeführt. Importierte Workouts und absolvierte Aktivitäten sind schreibgeschützt.

## Aktivitäten von Intervals.icu
Unter Einstellungen › „Aktivitäten von Intervals.icu“ legst du fest, für wie viele zurückliegende Tage (1–730, Standard 30) absolvierte Aktivitäten geholt werden. Taktspur lädt – nur lesend – die FIT-Datei (mit Messdaten, RR-Intervallen, DFA a1) oder, wenn keine Datei verfügbar ist, die Kennzahlen. Das passiert beim Start automatisch (abschaltbar) und per Knopf „Jetzt abgleichen“. Vorhandene Aktivitäten werden nicht doppelt angelegt, in Taktspur gelöschte nicht erneut geholt. Die Aktivitäten erscheinen im Kalender (grünes Häkchen) und unter Aktivitäten. Es wird nichts an Intervals.icu gesendet.

## Tests
`pip install -r requirements-dev.txt && pytest` – Intervals.icu wird nur simuliert.

## Grenzen
Kein FIT/HRV/DFA-Import.
Windows-Start und echte Browser-Darstellung sind nur im Linux-Test nicht geprüft.

## Diagramme (FIT, HRV, DFA a1)
- Browser: uPlot (lokal in `web/vendor/uplot`, MIT), Wrapper `web/js/charts.js` → `lineChart(container, {title, x, series})`. Zoom per Ziehen, Doppelklick setzt zurück, passt sich der Breite an.
- Server: `app/downsample.py` (LTTB) reduziert lange Zeitreihen auf einige hundert Punkte, Lücken bleiben erhalten – der Raspberry Pi rendert nichts, er liefert nur reduzierte Daten.
- Tests: `tests/frontend/browser.js` (echter Chromium: Layout Handy/PC, CSP, Diagramm), `tests/frontend/smoke.js` (jsdom), `tests/frontend/calendar_browser.js` (Kalender mit Aktivität, Schlüsselfeld, Abgleich-Einstellungen).

## Aktivitäten, FIT-Import und HRV (DFA a1)
- Aktivitäten → „FIT-Dateien importieren“ (mehrere Dateien möglich, Dubletten werden erkannt). GPS-Koordinaten und Profildaten aus der Datei werden **nicht** gespeichert.
- Alle Kanäle der Datei werden als Diagramme gezeigt (Pace/Tempo, Herzfrequenz, Leistung, Höhe, Kadenz, Schrittlänge, Laufdynamik, Atmung, Temperatur, unbekannte Zusatzfelder), dazu Übersicht, alle Sitzungs- und Rundenwerte, eine Tabelle pro Zeitabschnitt (30 s bis 5 min) und der CSV-Export der Rohwerte.
- DFA a1 wird **nur aus echten RR-Intervallen** der Datei berechnet (Kubios-ähnlich: λ = 500, Boxgrößen 4–16, 120-s-Fenster, Artefakterkennung, ungültige Fenster bleiben leer). Ohne RR-Daten zeigt Taktspur das ausdrücklich an. Schwellen-Schätzung nur, wenn die Belastung den Bereich um a1 = 0,75 abdeckt.
- Neue Abhängigkeiten: `fitdecode`, `numpy` (auf dem Raspberry Pi per `pip` als fertiges Paket; 32-bit-OS über piwheels).
- Schema-Version 2 (additiv): vor der Migration entsteht automatisch ein Backup.
