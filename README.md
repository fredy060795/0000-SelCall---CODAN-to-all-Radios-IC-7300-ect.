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

py -m pip install pyserial sounddevice numpy

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

CODAN SELCALL (CCIR 493-4):
---------------------------
- Echtes CODAN-Format: 100 Baud FSK, 1700 Hz (0) / 1870 Hz (1),
  Punktmuster-Vorspann, Phasing, jedes Zeichen doppelt (DX/RX).
- Call ID und Our ID muessen GENAU 4 Ziffern haben (z.B. 1234).
- Vorspann ("Preamble"): 2 s wenn die Gegenstation auf dem Kanal steht,
  6-12 s wenn die Gegenstation scannt.
- "Channel Test": CODAN-Geraete antworten mit einer Tonfolge.
- Funkgeraet immer in USB betreiben (Frequenz = Kanalfrequenz).

ICOM IC-7300 EINSTELLUNGEN (WICHTIG):
-------------------------------------
Ohne diese Einstellungen wird das USB-Audio NICHT gesendet:
1. Betriebsart USB-D (DATA-Taste) waehlen.
2. MENU > SET > Connectors > MOD Input > DATA MOD = USB
3. MENU > SET > Connectors > USB MOD Level ca. 50 %  (ALC beobachten,
   Leistung 10-30 W fuer FSK, ALC soll kaum ausschlagen)
4. MENU > SET > Connectors > CI-V > CI-V USB Baud Rate = 115200 (oder Auto),
   CI-V Address = 94h, CI-V Transceive egal.
5. In der Software: COM-Port = "Silicon Labs CP210x" Port des IC-7300,
   Audio Output = "Lautsprecher (USB Audio CODEC)",
   Audio Input = "Mikrofon (USB Audio CODEC)".
6. Pruefen: Im RX-Log erscheint "PTT ON" / "PTT OFF" bei jedem Senden.
   Erscheint "no serial/CAT connection", ist der COM-Port nicht geoeffnet.

========================================================================
Autor: Frederic Tartarone © 2026
========================================================================
