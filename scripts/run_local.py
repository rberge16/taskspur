"""Startet Taktspur ausschließlich auf 127.0.0.1:8775 (Port 8765 gehört einer anderen App).
Gibt bei Problemen eine verständliche Meldung aus, statt still zu enden."""
import os
import socket
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def main() -> int:
    missing = []
    for module, package in (("uvicorn", "uvicorn"), ("fastapi", "fastapi"), ("httpx", "httpx"), ("cryptography", "cryptography"),
                            ("pydantic", "pydantic"), ("numpy", "numpy"), ("fitdecode", "fitdecode")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print(f"FEHLER: Es fehlen Python-Pakete: {', '.join(missing)}.")
        print("Bitte ausführen:  python -m pip install -r requirements.txt   (im Taktspur-Ordner, mit der .venv)")
        return 3

    import uvicorn

    from app import config

    port = config.PORT
    if port in config.FORBIDDEN_PORTS:
        print(f"FEHLER: Port {port} ist für Taktspur gesperrt.")
        return 2
    host = config.bind_host()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex((host, port)) == 0:
            print(f"FEHLER: Port {port} ist bereits belegt – läuft Taktspur schon in einem anderen Fenster?")
            print(f"Öffne http://{host}:{port} oder beende das andere Programm.")
            return 4
    print(f"Taktspur startet auf http://{host}:{port} – Datenordner: {config.data_dir()}")
    try:
        uvicorn.run("app.main:app", host=host, port=port, log_level="info")
    except Exception:                                   # Startfehler (z. B. Datenbank neuer als Programm) sichtbar machen
        traceback.print_exc()
        print("\nFEHLER: Taktspur konnte nicht starten (siehe oben).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
