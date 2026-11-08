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
from selcall_codec import AudioGenerator, CodanSelcallEncoder  # noqa: E402

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

    def __init__(self, answer):
        self.master, slave = pty.openpty()
        self.port = os.ttyname(slave)
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
                               "RIG_SERIAL_PORT": dev.port, "RIG_BAUD": 9600})
        self.assertEqual(link.connect(), [])
        command = link.codan_command_text("selcall", "435201", "435299")
        self.assertEqual(command, "selcall 435201 from 435299")
        self.assertEqual(link.send_codan_cics(command), "")
        self.assertIn("ERROR", link.send_codan_cics("beacon 435201"))
        link.disconnect()

    def test_icom_cat_ptt(self):
        dev = FakeDevice(lambda line: None)
        link = self.make_link({"RADIO_MODEL": "IC-7300", "PTT_METHOD": "CAT", "CAT_ADDRESS": "94",
                               "RIG_SERIAL_PORT": dev.port, "RIG_BAUD": 115200})
        self.assertEqual(link.connect(), [])
        self.assertEqual(link.can_key_audio(), "")
        self.assertTrue(link.set_ptt(True))
        self.assertTrue(link.set_ptt(False))
        time.sleep(0.2)
        self.assertIn(b"\xfe\xfe\x94\xe0\x1c\x00\x01\xfd", dev.received)
        self.assertIn(b"\xfe\xfe\x94\xe0\x1c\x00\x00\xfd", dev.received)
        link.disconnect()

    def test_tnc_without_codan_cannot_key_audio(self):
        link = self.make_link({"RADIO_MODEL": "IC-7300", "PTT_METHOD": "TNC"})
        self.assertIn("nur mit einem Codan", link.can_key_audio())


if __name__ == "__main__":
    unittest.main()
