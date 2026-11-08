"""Run with:  py -m unittest discover -s tests

Encoder tests need numpy; the port tests use a pseudo terminal (Linux/macOS)
as a stand-in for the Codan and the PACTOR modem.
"""

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

import radio_models  # noqa: E402
from selcall_codec import AudioGenerator, CCIR493Decoder, CodanSelcallEncoder, describe_call  # noqa: E402

try:
    import pty
    import serial  # noqa: F401
    import radio_link
except ImportError:  # pragma: no cover
    pty = None


def demodulate(pcm: bytes, sample_rate: int, preamble_bits: int):
    x = np.frombuffer(pcm, dtype="<i2").astype(float)
    n = sample_rate // 100
    t = np.arange(n) / sample_rate
    bits = []
    for i in range(len(x) // n):
        seg = x[i * n:(i + 1) * n]
        p0 = abs(np.dot(seg, np.exp(-2j * np.pi * 1700 * t)))
        p1 = abs(np.dot(seg, np.exp(-2j * np.pi * 1870 * t)))
        bits.append(1 if p1 > p0 else 0)
    body, words = bits[preamble_bits:], []
    for k in range(0, len(body) - 9, 10):
        b = body[k:k + 10]
        value = sum(b[i] << i for i in range(7))
        assert b[7] * 4 + b[8] * 2 + b[9] == 7 - sum(b[:7]), "check bits"
        words.append(value)
    return words


class CodecTest(unittest.TestCase):
    def test_4_digit_matches_reference(self):
        words = CodanSelcallEncoder().build_words("1882", "4351")
        self.assertEqual(words, [125, 109, 125, 108, 125, 107, 125, 106, 125, 105, 125, 104,
                                 120, 120, 18, 120, 82, 120, 100, 18, 43, 82, 51, 100,
                                 117, 43, 117, 51, 117, 117])

    def test_6_digit_on_air(self):
        enc, gen = CodanSelcallEncoder(), AudioGenerator()
        pcm = bytes(enc.generate(gen, "435201", "435299", preamble_s=2.0))
        self.assertEqual(demodulate(pcm, gen.sample_rate, 200), enc.build_words("435201", "435299"))

    def test_bad_ids(self):
        enc = CodanSelcallEncoder()
        with self.assertRaises(ValueError):
            enc.build_words("4351029", "435299")
        with self.assertRaises(ValueError):
            enc.build_words("1234", "435299")


class FakeDevice:
    """Other end of a pseudo terminal: records lines, answers like a PTC/Codan."""

    def __init__(self, answer, raw=None):
        self.raw = raw          # raw(data) -> reply, for binary protocols (CI-V)
        self.master, self.slave = pty.openpty()
        self.port = os.ttyname(self.slave)
        self.answer = answer
        self.received = b""
        self.lines = []
        self._stop = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        buf = b""
        while not self._stop:
            try:
                data = os.read(self.master, 1024)
            except OSError:
                return
            self.received += data
            if self.raw is not None:
                reply = self.raw(data)
                if reply:
                    os.write(self.master, reply)
                continue
            buf += data
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                self.lines.append(line)
                reply = self.answer(line)
                if reply:
                    os.write(self.master, reply)


@unittest.skipIf(pty is None, "needs pty + pyserial")
class RadioLinkTest(unittest.TestCase):
    def setUp(self):
        self.profiles = radio_models.load_models(ROOT)
        self.logs = []

    def make_link(self, cfg):
        return radio_link.RadioLink(cfg, self.logs.append, self.profiles.get)

    def test_codan_on_modem_tnc(self):
        def ptc(line):
            text = line.split(b"\xaa")[-1].strip()
            if text == b"VER":
                return b"DR-9400 Firmware 1.00\r\ncmd: "
            return b"\r\ncmd: "
        dev = FakeDevice(ptc)
        link = self.make_link({"RADIO_MODEL": "CODAN NGT", "PTT_METHOD": "TNC",
                               "PTC_SERIAL_PORT": dev.port, "PTC_BAUD": 57600, "PTC_MODEM_TYPE": "AUTO"})
        self.assertEqual(link.connect(), [])
        command = link.codan_command_text("selcall", "435201", "435299")
        self.assertEqual(command, "selcall 435201")
        self.assertEqual(link.send_codan_cics(command), "")
        time.sleep(0.2)
        sent = [l.split(b"\xaa")[-1].strip() for l in dev.lines]
        # DR-9400: Kenwood TRX set-up like HFChat, then the Codan command
        self.assertIn(b"TRX TY K 9600 A V24", sent)
        self.assertIn(b"TRX T selcall 435201", sent)
        self.assertLess(sent.index(b"TRX TY K 9600 A V24"), sent.index(b"TRX T selcall 435201"))
        # hostmode left first (JHOST0 frames)
        self.assertIn(b"JHOST0", dev.received)
        link.disconnect()

    def test_hostmode_exit_frames(self):
        frames = radio_link.hostmode_exit_bytes()
        self.assertTrue(frames.startswith(b"\xaa\xaa\x00\x01\x05JHOST0"))
        self.assertTrue(frames.endswith(b"\x00\x01\x05JHOST0"))
        # CRC-16/X.25 check value
        self.assertEqual(radio_link._crc16_x25(b"123456789"), 0x906E)

    def test_codan_direct_cat(self):
        dev = FakeDevice(lambda line: b"\r\nOK\r\n" if line.startswith(b"selcall") else b"\r\nERROR: bad\r\n")
        link = self.make_link({"RADIO_MODEL": "CODAN ENVOY", "PTT_METHOD": "CAT", "CODAN_SEND_SELF_ID": True,
                               "CAT_PROTOCOL": "CODAN",
                               "RIG_SERIAL_PORT": dev.port, "RIG_BAUD": 9600})
        self.assertEqual(link.connect(), [])
        command = link.codan_command_text("selcall", "435201", "435299")
        self.assertEqual(command, "selcall 435201 from 435299")
        self.assertEqual(link.send_codan_cics(command), "")
        self.assertIn("ERROR", link.send_codan_cics("beacon 435201"))
        link.disconnect()

    def _icom(self, answer, only_baud=None):
        def radio(d):
            if only_baud is not None:
                import termios
                speed = termios.tcgetattr(dev.slave)[4]
                if speed != getattr(termios, f"B{only_baud}"):
                    return None                       # wrong baud rate: the radio hears garbage
            if d.rstrip(b"\x00").endswith(b"\x94\xe0\x03\xfd"):                 # read frequency
                return b"\xfe\xfe\xe0\x94\x03\x00\x00\x07\x14\x00\xfd"
            return answer(d)
        dev = FakeDevice(None, raw=radio)
        link = self.make_link({"RADIO_MODEL": "IC-7300", "PTT_METHOD": "CAT", "CAT_ADDRESS": "94",
                               "RIG_SERIAL_PORT": dev.port, "RIG_BAUD": 115200})
        self.assertEqual(link.connect(), [])
        return dev, link

    def test_icom_cat_ptt_confirmed(self):
        dev, link = self._icom(lambda d: b"\xfe\xfe\xe0\x94\xfb\xfd" if b"\x1c\x00" in d else None)
        self.assertEqual(link.can_key_audio(), "")
        self.assertTrue(link.set_ptt(True))
        self.assertTrue(link.set_ptt(False))
        self.assertIn(b"\xfe\xfe\x94\xe0\x1c\x00\x01\xfd", dev.received)
        self.assertIn(b"\xfe\xfe\x94\xe0\x1c\x00\x00\xfd", dev.received)
        self.assertTrue(any("bestätigt" in line for line in self.logs))
        link.disconnect()

    def test_icom_baud_rate_found_by_itself(self):
        """IC-7300 linked to REMOTE answers only at 19200 Bd although 115200 is set."""
        dev, link = self._icom(lambda d: b"\xfe\xfe\xe0\x94\xfb\xfd", only_baud=19200)
        self.assertEqual(link.rig.baud, 19200)
        self.assertEqual(link.cfg["RIG_BAUD"], 19200)
        self.assertTrue(link.cfg_changed)
        self.assertTrue(link.set_ptt(True))
        self.assertTrue(any("Unlink from [REMOTE]" in line for line in self.logs))
        link.disconnect()

    def test_rig_port_set_to_the_modem_finds_the_radio(self):
        """RIG COM Port points at the PTC-II (COM20); the IC-7300 is on another port (COM16)."""
        modem = FakeDevice(lambda line: b"\r\ncmd: ")
        radio = FakeDevice(None, raw=lambda d: (b"\xfe\xfe\xe0\x94\x03\x00\x00\x07\x14\x00\xfd"
                                                if d.endswith(b"\x03\xfd") else b"\xfe\xfe\xe0\x94\xfb\xfd"))
        old = radio_link.list_serial_ports
        radio_link.list_serial_ports = lambda: [modem.port, radio.port]
        try:
            link = self.make_link({"RADIO_MODEL": "IC-7300", "PTT_METHOD": "CAT", "CAT_PROTOCOL": "ICOM",
                                   "RIG_SERIAL_PORT": modem.port, "RIG_BAUD": 9600})
            self.assertEqual(link.connect(), [])
        finally:
            radio_link.list_serial_ports = old
        self.assertEqual(link.cfg["RIG_SERIAL_PORT"], radio.port)
        self.assertEqual(link.rig.port, radio.port)
        self.assertTrue(any("PACTOR-Modem, nicht das Funkgerät" in line for line in self.logs))
        self.assertTrue(link.set_ptt(True))
        link.disconnect()

    def test_icom_silent_on_every_baud(self):
        dev = FakeDevice(None, raw=lambda d: None)
        link = self.make_link({"RADIO_MODEL": "IC-7300", "PTT_METHOD": "CAT", "CAT_PROTOCOL": "ICOM",
                               "RIG_SERIAL_PORT": dev.port, "RIG_BAUD": 115200})
        problems = link.connect()
        self.assertEqual(len(problems), 1)
        self.assertIn("an keinem COM Port", problems[0])
        self.assertEqual(link.rig.baud, 115200)
        self.assertIn("blocked", link.icom_prepare_audio_tx())
        link.disconnect()

    def test_icom_meter_and_usb_data(self):
        def radio(d):
            if b"\x15\x11\xfd" in d:
                return b"\xfe\xfe\xe0\x94\x15\x11\x01\x28\xfd"       # Po = 128
            if b"\x15\x13\xfd" in d:
                return b"\xfe\xfe\xe0\x94\x15\x13\x00\x00\xfd"
            if b"\x06\x01\x01\xfd" in d or b"\x1a\x06\x01\x01\xfd" in d:
                return b"\xfe\xfe\xe0\x94\xfb\xfd"
            return None
        dev, link = self._icom(radio)
        self.assertEqual(link.icom_meter("PO"), 128)
        self.assertEqual(link.icom_meter("ALC"), 0)
        self.assertEqual(link.icom_set_usb_data(), "")
        link.disconnect()

    def _ic7300_with_menu(self, off_mod=4, data_mod=1, readable=True):
        """Fake IC-7300: in USB-D like PACTOR uses it, DATA OFF MOD / DATA MOD menu 0066 / 0067."""
        state = {"mode": b"\x01\x01", "data": b"\x01\x01", "menu_writes": []}
        menu = {0x66: off_mod, 0x67: data_mod}
        ok, ng = b"\xfe\xfe\xe0\x94\xfb\xfd", b"\xfe\xfe\xe0\x94\xfa\xfd"

        def radio(d):
            frame = d[d.find(b"\x94\xe0") + 2:d.find(b"\xfd")] if b"\x94\xe0" in d else b""
            if frame == b"\x04":
                return b"\xfe\xfe\xe0\x94\x04" + state["mode"] + b"\xfd"
            if frame == b"\x1a\x06":
                return b"\xfe\xfe\xe0\x94\x1a\x06" + state["data"] + b"\xfd"
            if frame[:3] == b"\x1a\x05\x00" and len(frame) == 4:
                if not readable:
                    return ng
                return b"\xfe\xfe\xe0\x94" + frame + bytes([menu[frame[3]]]) + b"\xfd"
            if frame[:3] == b"\x1a\x05\x00" and len(frame) == 5:
                state["menu_writes"].append(frame)
                return ok
            if frame[:1] == b"\x06" and len(frame) == 3:
                state["mode"] = frame[1:]
                return ok
            if frame[:2] == b"\x1a\x06" and len(frame) == 4:
                state["data"] = frame[2:]
                return ok
            return ok if frame else None
        dev, link = self._icom(radio)
        return state, link

    def test_pactor_on_acc_selcall_in_plain_usb(self):
        """DATA OFF MOD = MIC,USB, DATA MOD = ACC: selcall in USB, PACTOR's USB-D comes back."""
        state, link = self._ic7300_with_menu(off_mod=4, data_mod=1)
        saved = link.icom_prepare_audio_tx()
        self.assertNotIn("blocked", saved)
        self.assertEqual(state["data"], b"\x00\x00")             # DATA off -> source DATA OFF MOD (USB)
        link.icom_restore_audio_tx(saved)
        self.assertEqual((state["mode"], state["data"]), (b"\x01\x01", b"\x01\x01"))   # USB-D again
        self.assertEqual(state["menu_writes"], [])                 # menu never touched
        link.disconnect()

    def test_usb_on_data_mod_uses_usb_d(self):
        state, link = self._ic7300_with_menu(off_mod=0, data_mod=3)
        link.icom_restore_audio_tx(link.icom_prepare_audio_tx())
        self.assertEqual(state["data"], b"\x01\x01")
        self.assertEqual(state["menu_writes"], [])
        link.disconnect()

    def test_no_usb_source_blocks_with_instruction(self):
        state, link = self._ic7300_with_menu(off_mod=2, data_mod=1)      # MIC,ACC / ACC
        saved = link.icom_prepare_audio_tx()
        self.assertIn("DATA OFF MOD = MIC,USB", saved["blocked"])
        self.assertEqual(state["menu_writes"], [])
        link.disconnect()

    def test_icom_refuses_tx(self):
        dev, link = self._icom(lambda d: b"\xfe\xfe\xe0\x94\xfa\xfd")
        self.assertFalse(link.set_ptt(True))
        self.assertTrue(any("Amateurbänder" in line for line in self.logs))
        link.disconnect()

    def test_icom_silent(self):
        dev, link = self._icom(lambda d: None)
        self.assertFalse(link.set_ptt(True))
        self.assertTrue(link.set_ptt(False))
        self.assertTrue(any("KEINE Antwort" in line for line in self.logs))
        link.disconnect()

    def test_codan_model_but_icom_on_the_port_uses_audio(self):
        """Radio model 'CODAN ...' chosen, but an IC-7300 (ICOM) answers on the RIG port."""
        dev = FakeDevice(lambda line: None)
        link = self.make_link({"RADIO_MODEL": "CODAN ENVOY", "PTT_METHOD": "CAT", "CAT_PROTOCOL": "ICOM",
                               "RIG_SERIAL_PORT": dev.port, "RIG_BAUD": 115200})
        self.assertFalse(link.is_codan)
        link.connect()            # the fake does not answer CI-V: a baud-rate problem is reported, port stays open
        self.assertTrue(link.rig.is_open)
        self.assertIn("kein Codan", link.send_codan_cics("statuscall 435299"))
        self.assertNotIn(b"statuscall", dev.received)
        link.disconnect()
        tnc = self.make_link({"RADIO_MODEL": "CODAN NGT", "PTT_METHOD": "TNC", "CAT_PROTOCOL": "ICOM"})
        self.assertTrue(tnc.is_codan)

    def test_tnc_without_codan_cannot_key_audio(self):
        link = self.make_link({"RADIO_MODEL": "IC-7300", "PTT_METHOD": "TNC"})
        self.assertIn("nur mit einem Codan", link.can_key_audio())


import autodetect  # noqa: E402

# Windows device tree of an IC-7300 on a PC with Realtek sound (synthetic, as
# Get-PnpDevice reports it).
TREE = [
    {"Class": "Ports", "Name": "Silicon Labs CP210x USB to UART Bridge (COM16)",
     "Id": "USB\\VID_10C4&PID_EA60\\IC-7300 03001234",
     "Parents": ["USB\\VID_0451&PID_2046\\5&1A2B", "USB\\ROOT_HUB30\\4&ABC", "PCI\\VEN_8086"]},
    {"Class": "Ports", "Name": "Kommunikationsanschluss (COM1)", "Id": "ACPI\\PNP0501\\0", "Parents": ["ACPI\\X"]},
    {"Class": "AudioEndpoint", "Name": "Lautsprecher (USB Audio CODEC)",
     "Id": "SWD\\MMDEVAPI\\{0.0.0.00000000}.{AAA}",
     "Parents": ["USB\\VID_08BB&PID_2901&MI_00\\6&1", "USB\\VID_08BB&PID_2901\\5&2", "USB\\VID_0451&PID_2046\\5&1A2B",
                 "USB\\ROOT_HUB30\\4&ABC"]},
    {"Class": "AudioEndpoint", "Name": "Mikrofon (USB Audio CODEC)",
     "Id": "SWD\\MMDEVAPI\\{0.0.1.00000000}.{BBB}",
     "Parents": ["USB\\VID_08BB&PID_2901&MI_00\\6&1", "USB\\VID_08BB&PID_2901\\5&2", "USB\\VID_0451&PID_2046\\5&1A2B",
                 "USB\\ROOT_HUB30\\4&ABC"]},
    # a USB headset on the same root hub must not be taken
    {"Class": "AudioEndpoint", "Name": "Kopfhörer (USB PnP Sound Device)",
     "Id": "SWD\\MMDEVAPI\\{0.0.0.00000000}.{CCC}",
     "Parents": ["USB\\VID_0D8C&PID_0014&MI_00\\7", "USB\\VID_0D8C&PID_0014\\6", "USB\\ROOT_HUB30\\4&ABC"]},
    {"Class": "AudioEndpoint", "Name": "Lautsprecher (Realtek(R) Audio)",
     "Id": "SWD\\MMDEVAPI\\{0.0.0.00000000}.{DDD}", "Parents": ["HDAUDIO\\FUNC_01", "PCI\\VEN_8086"]},
]
OUTPUTS = ["Microsoft Soundmapper - Output", "Lautsprecher (Realtek(R) Audio)", "Kopfhörer (USB PnP Sound Device)",
           "Lautsprecher (USB Audio CODEC)"]
INPUTS = ["Microsoft Soundmapper - Input", "Mikrofon (Realtek(R) Audio)", "Mikrofon (USB Audio CODEC)"]


class AudioMatchTest(unittest.TestCase):
    def test_same_usb_device_as_com_port(self):
        out, inp = autodetect.audio_for_com_port("COM16", TREE)
        self.assertEqual(out, "Lautsprecher (USB Audio CODEC)")
        self.assertEqual(inp, "Mikrofon (USB Audio CODEC)")
        self.assertEqual(autodetect.audio_for_com_port("COM1", TREE), (None, None))

    def test_mme_names_are_cut_to_31_chars(self):
        names = ["Lautsprecher (2- USB Audio COD"]
        self.assertEqual(autodetect.match_name("Lautsprecher (2- USB Audio CODEC)", names), names[0])

    def test_guess_by_name(self):
        self.assertEqual(autodetect.guess_by_name(OUTPUTS), "Lautsprecher (USB Audio CODEC)")
        self.assertEqual(autodetect.pick_partner(INPUTS, "Lautsprecher (USB Audio CODEC)"),
                         "Mikrofon (USB Audio CODEC)")
        self.assertIsNone(autodetect.guess_by_name(["Lautsprecher (Realtek(R) Audio)"]))
        # unknown interface name, but the only USB sound card
        self.assertEqual(autodetect.guess_by_name(["Lautsprecher (Realtek(R) Audio)", "Speakers (2- USB Sound Card)",
                                                   "Lautsprecher (USB Interface XY)"]), "Speakers (2- USB Sound Card)")
        self.assertEqual(autodetect.guess_by_name(["Lautsprecher (Realtek(R) Audio)", "Lautsprecher (USB Interface XY)"]),
                         "Lautsprecher (USB Interface XY)")


@unittest.skipIf(pty is None, "needs pty + pyserial")
class ProbeTest(unittest.TestCase):
    def test_icom_found_and_address_learned(self):
        def icom(data):
            if b"\xe0\x03\xfd" in data:     # read frequency -> IC-7610 (98h) answers
                return b"\xfe\xfe\xe0\x98\x03\x00\x00\x07\x14\x00\xfd"
            return None
        dev = FakeDevice(None, raw=icom)
        hit = autodetect.probe_rig(dev.port, "ICOM", 0x94, bauds=(115200,))
        self.assertEqual(hit["address"], 0x98)       # found although 94 was set

    def test_ptc_found(self):
        def ptc(line):
            text = line.split(b"\xaa")[-1].strip()
            return b"DR-7800 V1.2\r\ncmd: " if text == b"VER" else b"\r\ncmd: "
        dev = FakeDevice(ptc)
        hit = autodetect.probe_ptc(dev.port, bauds=(57600,))
        self.assertEqual((hit["baud"], hit["modem"]), (57600, "DR-7800"))

    def test_nothing_answers(self):
        dev = FakeDevice(lambda line: None)
        self.assertIsNone(autodetect.probe_rig(dev.port, "YAESU", bauds=(38400,)))
        self.assertIsNone(autodetect.probe_ptc(dev.port, bauds=(57600,)))


def _audio(enc, gen, *args, **kwargs):
    pcm = bytes(enc.generate(gen, *args, **kwargs))
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def _decode(signal):
    dec, calls = CCIR493Decoder(), []
    for i in range(0, len(signal), 4800):
        calls += dec.feed(signal[i:i + 4800])
    return calls + dec.flush()


class CallTypesTest(unittest.TestCase):
    def setUp(self):
        self.enc, self.gen = CodanSelcallEncoder(), AudioGenerator()

    def test_page_and_status_and_gps_round_trip(self):
        rng = np.random.default_rng(3)
        quiet = lambda n: rng.normal(0, 0.05, n).astype(np.float32)
        signal = np.concatenate([
            quiet(20000),
            _audio(self.enc, self.gen, "435201", "435299", content=self.enc.page_content("Treffpunkt 14:30")),
            quiet(10000),
            _audio(self.enc, self.gen, "435201", "435299", content=self.enc.STATUS_REQUEST, preamble_s=1),
            _audio(self.enc, self.gen, "4352", "4353", content=self.enc.GPS_REQUEST, preamble_s=1),
            _audio(self.enc, self.gen, "4352", "4353", fmt=123, preamble_s=1),
            quiet(48000)])
        signal += rng.normal(0, 0.15, len(signal)).astype(np.float32)
        calls = [(c["kind"], c["from"], c["to"], c["text"]) for c in _decode(signal)]
        self.assertEqual(calls, [("Nachricht", "435299", "435201", "TREFFPUNKT 14:30"),
                                 ("Status-Abfrage", "435299", "435201", ""),
                                 ("GPS-Abfrage", "4353", "4352", ""),
                                 ("Kanaltest", "4353", "4352", "")])

    def test_sound_card_clock_off_by_one_percent(self):
        a = _audio(self.enc, self.gen, "435201", "435299", content=self.enc.page_content("X" * 32))
        for drift in (1.01, 0.99):
            x = np.interp(np.arange(0, len(a), drift), np.arange(len(a)), a).astype(np.float32)
            self.assertEqual([c["text"] for c in _decode(x)], ["X" * 32])

    def test_noise_makes_no_call(self):
        noise = np.random.default_rng(9).normal(0, 0.3, 48000 * 20).astype(np.float32)
        self.assertEqual(_decode(noise), [])

    def test_page_limits(self):
        with self.assertRaises(ValueError):
            self.enc.page_content("X" * 33)
        with self.assertRaises(ValueError):
            self.enc.page_content("Grüße")
        self.assertEqual(self.enc.page_content("ab"), [116, 65, 66])

    def test_describe_reply(self):
        call = describe_call([120, 43, 52, 1, 100, 43, 52, 99, 122, 122])
        self.assertEqual((call["kind"], call["from"], call["to"]), ("Selcall (Antwort/Quittung)", "435299", "435201"))


@unittest.skipIf(pty is None, "needs pyserial")
class CicsCommandTest(unittest.TestCase):
    def test_commands(self):
        link = radio_link.RadioLink({"RADIO_MODEL": "CODAN ENVOY"}, lambda t: None, lambda n: None)
        self.assertEqual(link.codan_command_text("page", "435201", "435299", 'Hallo "Wien"'),
                         "pagecall 435201 \"Hallo 'Wien'\"")
        self.assertEqual(link.codan_command_text("status", "435201", "435299"), "statuscall 435201")
        self.assertEqual(link.codan_command_text("gps", "435201", "435299"), "gpscall 435201")
        link.cfg["CODAN_SEND_SELF_ID"] = True
        self.assertEqual(link.codan_command_text("status", "435201", "435299"), "statuscall 435201 from 435299")
        self.assertEqual(link.codan_command_text("hangup", "", "435299"), "hangup")


if __name__ == "__main__":
    unittest.main()
