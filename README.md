========================================================================
                      SelCall Software - README
========================================================================

ÜBERSICHT:
----------
Diese Software generiert SelCall-Töne (ZVEI, CCIR, DTMF, CODAN, NECODE etc.)
und bietet eine Steuerung für Transceiver wie den Icom IC-7300 (CAT/CI-V, PTT).

VORAUSSETZUNGEN:
----------------
- Betriebssystem: Windows 10
- Python (installiert und über 'py' erreichbar)

BENÖTIGTE PYTHON-MODULE:
------------------------
Für den vollständigen Betrieb (serielle Schnittstelle, Audio-Geräte-Steuerung)
müssen folgende Module installiert werden:

1. pyserial     - Für die COM-Port Steuerung (CAT / CI-V und RTS-PTT)
2. sounddevice  - Für die Auswahl und Steuerung der Audio-Ein- und Ausgänge

INSTALLATIONSBEFEHLE:
---------------------
Öffnen Sie die Eingabeaufforderung (CMD) oder PowerShell und führen Sie
folgenden Befehl aus:

py -m pip install pyserial sounddevice

STARTEN DER ANWENDUNG:
----------------------
Navigieren Sie in das Verzeichnis der Anwendung und starten Sie 'selcall.py':

cd C:\SelCallApp
py selcall.py

EINSTELLUNGEN IN DER SOFTWARE:
------------------------------
Über das Menü "Edit -> Settings" können Sie:
1. Den COM-Port Ihres Transceivers auswählen und die Verbindung herstellen.
2. Die bevorzugten Audio-Eingangs- (Listen) und Ausgangs-Geräte (TX) festlegen.

========================================================================
Autor: Frederic Tartarone © 2026
========================================================================
