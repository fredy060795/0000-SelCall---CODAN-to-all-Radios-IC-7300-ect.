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

FUNKTIONEN IM CODAN-TAB (wie am Envoy)
--------------------------------------
  📞 Anpagern (Selcall)   normaler Selcall an die Station
  ✉ Nachricht senden     SMS/Pagecall, Text im Feld "Nachricht"
  ❓ Status abfragen      Get Status der Station
  📍 GPS abfragen         Position der Station anfordern
  Kanaltest               Beacon / Channel Test
  Auflegen                (nur Codan per CICS)

  Codan-Funkgerät (CICS):  selcall / pagecall {to} "{msg}" / statuscall /
                           gpscall / beacon / hangup. Der Codan sendet
                           selbst; was er zurückmeldet (Antworten,
                           eingehende Rufe/Nachrichten) erscheint im
                           "Eingang". Die Befehle sind in den
                           Einstellungen änderbar.
  IC-7300 & Co. (Audio):   der PC sendet im offenen Selcall-Format
                           (Nachricht = 116 + max. 32 Zeichen, Status =
                           103 103, GPS = 125 125) und hört danach mit:
                           der RX Decoder erkennt CCIR 493-4 Rufe,
                           Nachrichten und Antworten und trägt sie in den
                           "Eingang" ein. Rufe an die eigene ID werden
                           gelb markiert. Doppelklick übernimmt die
                           Station als Ziel (zum Antworten).
  Nachrichten: keine Umlaute (ä ö ü ß), Audio max. 32 Zeichen,
  CICS max. 64 Zeichen.

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

AUTOMATISCH EINRICHTEN (empfohlen)
----------------------------------
1. Datei → Einstellungen → Funkgerät wählen (z.B. IC-7300 oder CODAN NGT)
   und PTT Methode (IC-7300: CAT, Codan am Modem: TNC).
2. "🔍 Automatisch erkennen" klicken. Das Programm
     - fragt jeden COM Port bei allen Baudraten nach der Frequenz
       (CI-V / FA; / CICS FREQ) bzw. nach dem Modem-Prompt "cmd:" –
       es wird dabei NICHT gesendet,
     - lernt dabei auch die CI-V Adresse,
     - sucht die Soundkarte, die im selben USB-Gerät steckt wie der
       COM Port des Funkgeräts (Windows Geräte-Baum), sonst nach Namen
       ("USB Audio CODEC", "USB PnP Sound Device", ...).
3. Speichern. Danach "🔊 Testton 2 s (mit PTT)": das Funkgerät muss
   senden und die ALC/Leistung ausschlagen.
Vorher HFChat und andere Programme schließen, die die COM Ports benutzen.
Fehlt beim Start die eingestellte Soundkarte, sucht das Programm sie
selbst. In der Liste steht jede Soundkarte nur einmal (Windows MME).

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
     - DATA MOD: stellt SelCall selbst kurz auf USB (siehe unten),
       am Gerät auf ACC lassen, wenn ein PACTOR-Modem an ACC hängt
     - USB MOD Level ca. 50 % (ALC kaum Ausschlag), 10-30 W
     - CI-V Address 94h, CI-V USB Baud Rate 115200 (oder Auto)

WARUM GEHT DER TON NICHT ÜBER DEN COM PORT?
-------------------------------------------
Der COM Port ist eine reine Daten-/Befehlsleitung (CAT/CI-V: Frequenz,
PTT, ...). Ton kann darüber nicht übertragen werden. Beim IC-7300 läuft
der Ton über die eingebaute USB-Soundkarte ("USB Audio CODEC") - im
selben USB-Kabel, aber als eigenes Gerät. Deshalb braucht der Audio-Weg
COM Port (PTT) UND Soundkarte (Ton).
Ausnahme Codan: Der Codan erzeugt den Selcall selbst, das Programm
schickt nur den Befehl über den COM Port - keine Soundkarte nötig.

WENN DIE PTT NICHT AUF SENDEN GEHT (IC-7300, PTT Methode CAT)
------------------------------------------------------------
"PTT-Test 1 s" in den Einstellungen drücken und ins Protokoll schauen:
  "Funkgerät bestätigt"  -> PTT geht, Problem liegt beim Ton
  "lehnt ab (FA)"        -> das Funkgerät verweigert das Senden. Der
                            IC-7300 sendet NUR in den Amateurbändern -
                            auf Codan-Kanälen (z.B. 4947 kHz) geht er
                            nicht auf TX.
  "KEINE Antwort"        -> falscher COM Port / falsche Baudrate /
                            falsche CI-V Adresse: "Automatisch erkennen".
                            IC-7300: MENU > SET > Connectors > CI-V >
                            CI-V USB Baud Rate = 115200, CI-V Address = 94h.

SOUNDKARTE WIRD NICHT ERKANNT / TON KOMMT AM PC HERAUS
------------------------------------------------------
Das Programm spielt NIE mehr auf dem Windows-Standardgerät (PC-Lautsprecher):
fehlt die Funkgeräte-Soundkarte, wird nicht gesendet und die Suche angeboten.
"Microsoft Sound Mapper" / "Primärer Soundtreiber" stehen nicht mehr in der
Liste - das ist immer der PC-Lautsprecher.

Sicherster Weg (Icom, PTT Methode CAT):
  Einstellungen → Audio → "🎯 Per Sendetest finden (Icom)"
  Das Funkgerät geht nacheinander je 1 s auf Senden, auf jeder Soundkarte
  wird ein Ton gespielt und über CI-V die Leistung/ALC gelesen. Die Karte,
  bei der Leistung herauskommt, ist die des Funkgeräts - sie wird
  gespeichert (Eingang passend dazu). Vorher stellt das Programm das
  Funkgerät auf USB-D. Kommt bei keiner Karte Leistung: am IC-7300
  DATA MOD = USB und USB MOD Level prüfen.
Bei jedem Senden liest das Programm Leistung/ALC und warnt, wenn kein Ton
am Funkgerät ankommt.
"Ton ohne PTT abspielen": hörst du den Ton am PC, ist es die falsche Karte.

- Ist die Liste leer: "py -m pip install sounddevice" fehlt.
- IC-7300 per USB anschließen und EINSCHALTEN, bevor das Programm startet
  (sonst gibt es den "USB Audio CODEC" nicht). Treiber: Icom USB Driver.
- "Alle Audiogeräte ins Protokoll" drücken und die Liste schicken.

IC-7300 MIT PACTOR-MODEM AN ACC (DATA MOD)
------------------------------------------
DATA MOD am IC-7300 kann nur EINE Quelle haben: ACC (PACTOR-Modem) oder USB
(SelCall vom PC). Darum: am Funkgerät DATA MOD auf ACC lassen.
SelCall stellt vor jedem Ruf über CI-V um (Menü 1A 05 00 67):
  DATA MOD → USB, Betriebsart → USB-D
und danach wieder zurück auf genau das, was vorher eingestellt war
(z.B. ACC, USB, DATA aus). Im Protokoll steht "DATA MOD ACC → USB (nur für
diesen Ruf)" und "DATA MOD zurück auf ACC".
Abschaltbar in Einstellungen → CAT / RIG. IC-7300MK2: Menü-Nr. 0085.
Kann DATA MOD nicht gelesen werden, fasst das Programm das Menü nicht an.

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
