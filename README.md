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

## Tests
`pip install -r requirements-dev.txt && pytest` – Intervals.icu wird nur simuliert.

## Grenzen
Kein FIT/HRV/DFA-Import.
Windows-Start und echte Browser-Darstellung sind nur im Linux-Test nicht geprüft.
