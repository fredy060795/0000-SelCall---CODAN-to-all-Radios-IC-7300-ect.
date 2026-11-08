========================================================================
                      SelCall Terminal - README
========================================================================

ÜBERSICHT
---------
SelCall für CODAN (CCIR 493-4, 4- und 6-stellig), ZVEI, CCIR, DTMF,
Necode und CTCSS. Die Verbindung zum Funkgerät wird wie in HFChat
eingestellt: Funkgerät, Modem/PTC, CAT/RIG, TNC/PTT.

Wie der Selcall gesendet wird:

  CODAN-Funkgerät (Envoy, NGT, 2110, 93xx ...):
    Das Funkgerät sendet seinen Codan-Selcall SELBST. Das Programm gibt
    nur den CICS-Befehl, z.B. "selcall 435299":
      - PTT Methode TNC  (Codan hängt am PACTOR-Modem):
        über das Modem mit "TRX T selcall 435299"
      - PTT Methode CAT  (Codan direkt am PC, CICS-Kabel):
        "selcall 435299" + CR am RIG COM Port
    "Kanaltest (Beacon)" sendet "beacon 435299".

  Andere Funkgeräte (IC-7300, Yaesu, Kenwood ...):
    Der PC erzeugt das Signal (CCIR 493-4: 100 Baud FSK 1700/1870 Hz,
    bzw. ZVEI/CCIR/DTMF Töne) auf der Soundkarte und schaltet die PTT
    über CAT (CI-V / TX1; / TX;), RTS oder DTR am RIG COM Port.

VORAUSSETZUNGEN
---------------
- Windows 10/11, Python 3
- py -m pip install -r requirements.txt
  (pyserial, sounddevice, numpy)

STARTEN
-------
    cd C:\SelCallApp
    py selcall.py

Beim ersten Start öffnen sich die Einstellungen. Eine settings.json der
alten Version wird übernommen.

EINSTELLUNGEN (Datei → Einstellungen)
-------------------------------------
Funkgerät     Modell aus der Liste. Füllt Protokoll, CI-V Adresse und
              Baudrate. Weitere Geräte in "radios.txt" (siehe
              radio_models.py).
Modem / PTC   PTC COM Port, PTC Baudrate, Modemtyp (AUTO erkennt DR-9400 /
              DR-7800 / PTC-II). Nur bei PTT Methode TNC benutzt.
CAT / RIG     RIG COM Port, RIG Baudrate, CI-V Adresse, Protokoll.
TNC / PTT     PTT Methode: CAT, TNC, RTS, DTR, VOX; PTT Vorlauf in ms.
Audio         Soundkarte für Selcall vom PC (IC-7300: "USB Audio CODEC").
CODAN         Eigene ID (4 oder 6 Ziffern, z.B. 435299), wie der Selcall
              erzeugt wird (AUTO / CICS / AUDIO), die CICS-Befehle
              ({to} = gerufene Station, {self} = eigene ID).

Im Hauptfenster: "Verbinden" öffnet die Ports. Das Protokoll zeigt alles,
was an Funkgerät/Modem geht (←) und was zurückkommt (→), z.B. "ERROR ..."
vom Codan. Unter "Befehl an Funkgerät/Modem" kann man Befehle von Hand
schicken (z.B. "ver" an den Codan, "VER" an das Modem).

TYPISCHE AUFBAUTEN
------------------
1) Codan NGT/Envoy am PACTOR-Modem:
     Funkgerät = CODAN NGT (bzw. ENVOY)
     PTC COM Port / Baudrate wie in HFChat, Modemtyp AUTO
     PTT Methode = TNC
   WICHTIG: HFChat vorher beenden - ein COM Port kann nur von einem
   Programm benutzt werden. Einen Hostmode, den ein anderes Programm offen
   gelassen hat, beendet SelCall selbst (JHOST0).

2) Codan direkt am PC (CICS-Kabel):
     Funkgerät = CODAN ..., RIG COM Port, RIG Baudrate (meist 9600)
     PTT Methode = CAT
   Am Codan muss CICS eingeschaltet sein.

3) Icom IC-7300 per USB:
     Funkgerät = IC-7300, RIG COM Port = CP210x Port, RIG Baudrate 115200
     PTT Methode = CAT, Audio Ausgang = "USB Audio CODEC"
   Am IC-7300:
     - Betriebsart USB-D (DATA-Taste)
     - MENU > SET > Connectors > MOD Input > DATA MOD = USB
     - USB MOD Level ca. 50 % (ALC kaum Ausschlag), 10-30 W
     - CI-V Address 94h, CI-V USB Baud Rate 115200 (oder Auto)

CODAN SELCALL VOM PC (Audio, CCIR 493-4)
----------------------------------------
- Call ID und eigene ID: 4 oder 6 Ziffern, beide gleich lang.
  6-stellig = 3 Ziffernpaare (43 52 99).
- Vorspann: 2 s wenn die Gegenstation auf dem Kanal steht, 6-12 s wenn
  sie scannt.
- Funkgerät in USB.

TESTS
-----
    py -m unittest discover -s tests

========================================================================
Autor: Frederic Tartarone © 2026
========================================================================
