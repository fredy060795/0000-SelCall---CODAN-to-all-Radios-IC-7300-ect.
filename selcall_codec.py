"""Signal generation for SelCall: sequential tones, DTMF and CODAN / CCIR 493-4 FSK.

No GUI and no serial port here, so it can be tested on its own.
"""

import io
import wave

import numpy as np

# Tone Frequency Definitions (in Hz)
TONE_STANDARDS = {
    "DTMF": {
        "type": "dtmf",
        "duration": 100,
        "gap": 50,
        "matrix": {
            "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
            "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
            "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
            "E": (941, 1209), "0": (941, 1336), "F": (941, 1477), "D": (941, 1633)
        }
    },
    "CCIR1": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "A": 2400, "B": 930, "C": 2247, "D": 990, "E": 2110, "R": 2110
        }
    },
    "CCIR7": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "A": 2400, "B": 930, "C": 2247, "D": 990, "E": 2110, "R": 2110
        }
    },
    "PCCIR": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "R": 2110
        }
    },
    "EIA": {
        "type": "sequential",
        "duration": 33,
        "gap": 0,
        "tones": {
            "1": 741, "2": 882, "3": 1023, "4": 1164, "5": 1305,
            "6": 1446, "7": 1587, "8": 1728, "9": 1869, "0": 600,
            "A": 459, "B": 1091, "C": 2010, "D": 2151, "E": 2292, "R": 459
        }
    },
    "EEA": {
        "type": "sequential",
        "duration": 40,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "A": 1055, "B": 930, "C": 2247, "D": 990, "E": 2110, "R": 2110
        }
    },
    "CCITT": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1124, "2": 1197, "3": 1275, "4": 1358, "5": 1446,
            "6": 1540, "7": 1640, "8": 1747, "9": 1860, "0": 1981,
            "A": 2400, "B": 930, "C": 2247, "D": 990, "E": 2110, "R": 2110
        }
    },
    "EURO": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 979.8, "2": 903.1, "3": 832.5, "4": 767.4, "5": 707.4,
            "6": 652.3, "7": 601.6, "8": 554.9, "9": 511.8, "0": 1062.9
        }
    },
    "NATEL": {
        "type": "sequential",
        "duration": 100,
        "gap": 0,
        "tones": {
            "1": 1633, "2": 1633, "3": 1633, "4": 1633, "5": 1633,
            "6": 1633, "7": 1633, "8": 1633, "9": 1633, "0": 1633
        }
    },
    "VDEW": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 1060, "2": 1160, "3": 1270, "4": 1400, "5": 1530,
            "6": 1670, "7": 1830, "8": 2000, "9": 2200, "0": 2400
        }
    },
    "MODAT": {
        "type": "sequential",
        "duration": 30,
        "gap": 0,
        "tones": {
            "1": 631.0, "2": 741.0, "3": 882.0, "4": 1023.0, "5": 1164.0,
            "6": 1305.0, "7": 1446.0, "8": 1587.0, "9": 1728.0, "0": 600.0,
            "R": 459.0
        }
    },
    "ZVEI1": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 1060, "2": 1160, "3": 1270, "4": 1400, "5": 1530,
            "6": 1670, "7": 1830, "8": 2000, "9": 2200, "0": 2400,
            "A": 2800, "B": 810, "C": 930, "D": 885, "E": 2600, "R": 2600
        }
    },
    "ZVEI2": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 1060, "2": 1160, "3": 1270, "4": 1400, "5": 1530,
            "6": 1670, "7": 1830, "8": 2000, "9": 2200, "0": 2400,
            "A": 885, "B": 810, "C": 930, "D": 1000, "E": 2600, "R": 2600
        }
    },
    "ZVEI3": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 970, "2": 1060, "3": 1160, "4": 1270, "5": 1400,
            "6": 1530, "7": 1670, "8": 1830, "9": 2000, "0": 2200,
            "A": 885, "B": 810, "C": 930, "D": 2400, "E": 2600, "R": 2600
        }
    },
    "PZVEI": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 1060, "2": 1160, "3": 1270, "4": 1400, "5": 1530,
            "6": 1670, "7": 1830, "8": 2000, "9": 2200, "0": 2400,
            "R": 2600
        }
    },
    "DZVEI": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 970, "2": 1060, "3": 1160, "4": 1270, "5": 1400,
            "6": 1530, "7": 1670, "8": 1830, "9": 2000, "0": 2200,
            "R": 2600
        }
    },
    "PDZVEI": {
        "type": "sequential",
        "duration": 70,
        "gap": 0,
        "tones": {
            "1": 970, "2": 1060, "3": 1160, "4": 1270, "5": 1400,
            "6": 1530, "7": 1670, "8": 1830, "9": 2000, "0": 2200,
            "R": 2600
        }
    },
    "ICAO": {
        "type": "icao",
        "duration": 1000,
        "gap": 200,
        "tones": {
            "A": 312.6, "B": 346.7, "C": 384.6, "D": 426.6,
            "E": 473.2, "F": 524.8, "G": 582.1, "H": 645.7,
            "J": 716.1, "K": 794.3, "L": 881.0, "M": 977.2,
            "P": 1083.9, "Q": 1202.3, "R": 1333.5, "S": 1479.1
        }
    },
    "CTCSS": {
        "type": "ctcss",
        "duration": 1000,
        "gap": 0,
        "tones": {
            "67.0": 67.0, "71.9": 71.9, "74.4": 74.4, "77.0": 77.0,
            "79.7": 79.7, "82.5": 82.5, "85.4": 85.4, "88.5": 88.5,
            "91.5": 91.5, "94.8": 94.8, "97.4": 97.4, "100.0": 100.0,
            "103.5": 103.5, "107.2": 107.2, "110.9": 110.9, "114.8": 114.8,
            "118.8": 118.8, "123.0": 123.0, "127.3": 127.3, "131.8": 131.8,
            "136.5": 136.5, "141.3": 141.3, "146.2": 146.2, "151.4": 151.4,
            "156.7": 156.7, "162.2": 162.2, "167.9": 167.9, "173.8": 173.8,
            "179.9": 179.9, "186.2": 186.2, "192.8": 192.8, "203.5": 203.5,
            "210.7": 210.7, "218.1": 218.1, "225.7": 225.7, "233.6": 233.6,
            "241.8": 241.8, "250.3": 250.3, "254.1": 254.1
        }
    }
}

NECODE_TONES = {
    "0": 600, "1": 741, "2": 882, "3": 1023, "4": 1164,
    "5": 1305, "6": 1446, "7": 1587, "8": 1728, "9": 1869
}


class AudioGenerator:
    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate

    @staticmethod
    def _to_pcm(signal):
        signal = np.clip(signal, -1.0, 1.0)
        return bytearray((signal * 32767).astype('<i2').tobytes())

    def _ramp(self, signal, ramp_ms=3):
        n = min(int(self.sample_rate * ramp_ms / 1000.0), len(signal) // 2)
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n)
            signal[:n] *= ramp
            signal[-n:] *= ramp[::-1]
        return signal

    def generate_sine_wave(self, frequencies, duration_ms, amplitude=0.5):
        num_samples = int(self.sample_rate * (duration_ms / 1000.0))
        if isinstance(frequencies, (int, float)):
            freqs = [frequencies]
        else:
            freqs = list(frequencies)
        t = np.arange(num_samples) / self.sample_rate
        val = np.zeros(num_samples)
        for f in freqs:
            if f > 0:
                val += np.sin(2.0 * np.pi * f * t)
        val = (val / max(len(freqs), 1)) * amplitude
        return self._to_pcm(self._ramp(val))

    def generate_tone_sequence(self, tones, amplitude=0.5):
        """Phase-continuous sequence of single tones: list of (freq_hz, duration_ms)."""
        freq_per_sample = []
        for freq, dur in tones:
            n = int(round(self.sample_rate * dur / 1000.0))
            freq_per_sample.append(np.full(n, float(freq)))
        if not freq_per_sample:
            return bytearray()
        f = np.concatenate(freq_per_sample)
        phase = 2.0 * np.pi * np.cumsum(f) / self.sample_rate
        signal = np.where(f > 0, np.sin(phase), 0.0) * amplitude
        return self._to_pcm(self._ramp(signal, 5))

    def generate_fsk(self, bits, baud, f_zero, f_one, amplitude=0.5):
        """Phase-continuous 2-FSK (no clicks between bits)."""
        bit_ms = 1000.0 / baud
        # exact sample positions avoid timing drift over long preambles
        bounds = np.round(np.arange(len(bits) + 1) * self.sample_rate / baud).astype(int)
        f = np.empty(bounds[-1])
        for i, b in enumerate(bits):
            f[bounds[i]:bounds[i + 1]] = f_one if b else f_zero
        phase = 2.0 * np.pi * np.cumsum(f) / self.sample_rate
        return self._to_pcm(self._ramp(np.sin(phase) * amplitude, 5))

    def generate_silence(self, duration_ms):
        num_samples = int(self.sample_rate * (duration_ms / 1000.0))
        return bytearray(num_samples * 2)

    def create_wav_bytes(self, audio_data):
        byte_io = io.BytesIO()
        with wave.open(byte_io, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio_data)
        return byte_io.getvalue()


class CodanSelcallEncoder:
    """CODAN HF selcall = CCIR 493-4 (4-digit) / open 6-digit selcall.

    100 baud phase-continuous 2-FSK, 1700 Hz = bit 0, 1870 Hz = bit 1
    (audio frequencies in USB). Each word = 7 information bits (LSB first)
    followed by 3 check bits = number of zero bits in the information part
    (MSB first). Every message word is sent twice (DX / RX, time diversity).
    """
    BAUD = 100
    F_ZERO = 1700.0
    F_ONE = 1870.0

    FMT_SELCALL = 120       # selective call to individual station
    FMT_CHANNEL_TEST = 123  # Codan channel test / beacon (radio answers with tones)
    EOS_ARQ = 117           # end of sequence, acknowledge request
    PHASING_DX = 125
    PHASING_RX = [109, 108, 107, 106, 105, 104]

    CATEGORIES = {
        "Routine": 100,
        "Business": 106,
        "Safety": 108,
        "Urgent": 110,
        "Distress": 112,
    }

    @staticmethod
    def word_bits(value):
        value &= 0x7F
        bits = [(value >> i) & 1 for i in range(7)]
        zeros = bits.count(0)
        bits += [(zeros >> 2) & 1, (zeros >> 1) & 1, zeros & 1]
        return bits

    @staticmethod
    def split_id(station_id, label):
        """4 digits -> 2 symbols, 6 digits -> 3 symbols (each symbol = digit pair 00-99)."""
        sid = str(station_id).strip().replace(" ", "")
        if not (sid.isdigit() and len(sid) in (4, 6)):
            raise ValueError(
                f"{label} '{sid}' is invalid: CODAN / CCIR 493-4 selcall uses 4 or 6 digits "
                f"(e.g. 1234 or 435299)."
            )
        return [int(sid[i:i + 2]) for i in range(0, len(sid), 2)]

    # Content after the caller's address (open selcall layout, also understood
    # by Codan radios in an Open Selcall network)
    PAGE = 116              # pagecall: 116 + up to 32 text characters
    STATUS_REQUEST = (103, 103)
    GPS_REQUEST = (125, 125)
    PAGE_MAX_CHARS = 32
    END_SYMBOLS = (117, 122, 127, 119)

    @classmethod
    def page_content(cls, text):
        text = str(text or "").upper()
        if not 1 <= len(text) <= cls.PAGE_MAX_CHARS:
            raise ValueError(f"Nachricht: 1 bis {cls.PAGE_MAX_CHARS} Zeichen.")
        bad = sorted({ch for ch in text if not 32 <= ord(ch) < 127})
        if bad:
            raise ValueError(f"Nachricht: diese Zeichen gehen nicht: {''.join(bad)} (keine Umlaute)")
        return [cls.PAGE] + [ord(ch) for ch in text]

    def build_words(self, call_id, our_id, fmt=FMT_SELCALL, category=100, content=()):
        to = self.split_id(call_id, "Call ID")
        frm = self.split_id(our_id, "Our ID")
        if len(to) != len(frm):
            raise ValueError("Call ID and Our ID must both have 4 digits or both have 6 digits.")
        # Message in DX order: format, called address, category, self ID,
        # content, EOS x3
        dx = [fmt] + to + [category] + frm + list(content) + [self.EOS_ARQ] * 3
        # RX copy lags the DX copy by 4 words (time diversity)
        rx = [dx[0], dx[0]] + dx[:-2]
        words = []
        for ph in self.PHASING_RX:
            words += [self.PHASING_DX, ph]
        for d, r in zip(dx, rx):
            words += [d, r]
        return words

    def build_bits(self, call_id, our_id, fmt=FMT_SELCALL, category=100, preamble_s=2.0, content=()):
        n_pre = max(20, int(round(preamble_s * self.BAUD)))
        bits = [i & 1 for i in range(n_pre)]  # dot pattern 0101...
        for w in self.build_words(call_id, our_id, fmt, category, content):
            bits += self.word_bits(w)
        return bits

    def generate(self, audio_gen, call_id, our_id, fmt=FMT_SELCALL, category=100, preamble_s=2.0, content=()):
        bits = self.build_bits(call_id, our_id, fmt, category, preamble_s, content)
        return audio_gen.generate_fsk(bits, self.BAUD, self.F_ZERO, self.F_ONE)


def describe_call(words):
    """Turn the DX words of a call (format .. end) into a dict, None if not a call."""
    if len(words) < 6:
        return None
    fmt = words[0]
    if fmt not in (120, 123, 125, 102, 116):
        return None
    try:
        cat_at = next(i for i in range(1, 5) if words[i] is not None and words[i] >= 100)
    except StopIteration:
        return None
    to = words[1:cat_at]
    n = len(to)
    if n not in (2, 3) or len(words) < cat_at + 1 + n + 1:
        return None
    frm = words[cat_at + 1:cat_at + 1 + n]
    if any(w is None or w > 99 for w in to + frm):
        return None
    rest = [w for w in words[cat_at + 1 + n:]]
    end = None
    while rest and (rest[-1] is None or rest[-1] in CodanSelcallEncoder.END_SYMBOLS):
        if rest[-1] is not None:
            end = rest[-1]
        rest.pop()
    call = {
        "to": "".join(f"{w:02d}" for w in to),
        "from": "".join(f"{w:02d}" for w in frm),
        "category": words[cat_at],
        "format": fmt,
        "end": end,
        "content": rest,
        "kind": "Selcall",
        "text": "",
    }
    if fmt == 123:
        call["kind"] = "Kanaltest"
    elif rest[:1] == [CodanSelcallEncoder.PAGE]:
        call["kind"] = "Nachricht"
        call["text"] = "".join(chr(w) if w is not None and 32 <= w < 127 else "?" for w in rest[1:])
    elif tuple(rest[:2]) == CodanSelcallEncoder.STATUS_REQUEST:
        call["kind"] = "Status-Abfrage"
    elif tuple(rest[:2]) == CodanSelcallEncoder.GPS_REQUEST:
        call["kind"] = "GPS-Abfrage"
    elif rest[:1] == [121]:
        call["kind"] = "GPS-Position"
    elif rest[:1] == [102]:
        call["kind"] = "Telefonruf"
    elif rest[:2] == [104, 105]:
        call["kind"] = "Auflegen"
    elif rest:
        call["kind"] = "Ruf mit Daten"
        call["text"] = " ".join("?" if w is None else str(w) for w in rest)
    if end == 122:
        call["kind"] += " (Antwort/Quittung)"
    return call


class CCIR493Decoder:
    """Receives CODAN / CCIR 493-4 calls from audio (100 Bd FSK 1700/1870 Hz).

    feed() takes float samples; it returns the calls found so far.  The
    receiver looks for the phasing sequence, then reads every word in the DX
    position and repairs bad ones from their RX copy four words later.
    """
    DECIMATE = 10

    def __init__(self, sample_rate=48000, keep_s=12.0):
        self.sample_rate = int(sample_rate)
        self.keep = int(keep_s * sample_rate)
        self.buffer = np.zeros(0, dtype=np.float32)
        self.offset = 0              # absolute sample index of buffer[0]
        self.pending = 0
        self._last = {}

    def feed(self, samples):
        samples = np.asarray(samples, dtype=np.float32).ravel()
        self.buffer = np.concatenate([self.buffer, samples])
        self.pending += len(samples)
        calls = []
        if self.pending >= self.sample_rate // 2:     # look every 0.5 s
            self.pending = 0
            calls = self._scan()
            if len(self.buffer) > self.keep:
                cut = len(self.buffer) - self.keep
                self.buffer = self.buffer[cut:]
                self.offset += cut
        return calls

    def flush(self):
        self.pending = 0
        return self._scan()

    # -- signal -> soft bits
    def _discriminator(self):
        x = self.buffer.astype(np.float64)
        n = np.arange(len(x)) + self.offset
        win = self.sample_rate // 100
        out = []
        for f in (CodanSelcallEncoder.F_ZERO, CodanSelcallEncoder.F_ONE):
            mixed = x * np.exp(-2j * np.pi * f * n / self.sample_rate)
            c = np.cumsum(mixed)
            avg = np.empty_like(c)
            avg[:win] = c[:win]
            avg[win:] = c[win:] - c[:-win]
            out.append(np.abs(avg))
        a0, a1 = out
        d = (a1 - a0) / (a1 + a0 + 1e-9)
        return d[::self.DECIMATE]

    @staticmethod
    def _words(bits):
        """value and parity-ok of the 10-bit word starting at every bit."""
        n = len(bits) - 9
        if n <= 0:
            return np.zeros(0, int), np.zeros(0, bool)
        b = np.lib.stride_tricks.sliding_window_view(bits, 10)[:n]
        value = (b[:, :7] * (1 << np.arange(7))).sum(axis=1)
        zeros = 7 - b[:, :7].sum(axis=1)
        check = b[:, 7] * 4 + b[:, 8] * 2 + b[:, 9]
        return value, check == zeros

    def _scan(self):
        d = self._discriminator()
        spb = self.sample_rate // 100 // self.DECIMATE        # decimated samples per bit (48)
        best = None
        for polarity in (1, -1):
            for off in range(0, spb, 6):
                soft = polarity * d[off + spb - 1::spb]
                value, ok = self._words((soft > 0).astype(np.int64))
                start = self._find_phasing(value, ok)
                if start is None:
                    continue
                result = self._read_call(polarity * d, off + start * spb, spb)
                if result is None:
                    continue
                words, end_pos, quality = result
                if best is None or quality > best[0]:
                    best = (quality, words, end_pos * self.DECIMATE)
        if best is None:
            return []
        _, words, end_sample = best
        found = []
        call = describe_call(words)
        if call is not None:
            key = (call["from"], call["to"], call["kind"], call["text"])
            t = self.offset + end_sample
            if t - self._last.get(key, -10 ** 12) > 3 * self.sample_rate:
                self._last[key] = t
                found.append(call)
        cut = min(len(self.buffer), end_sample)       # drop what has been read
        self.buffer = self.buffer[cut:]
        self.offset += cut
        return found

    @staticmethod
    def _find_phasing(value, ok):
        """Bit index of the first DX word of a phasing sequence, None if none."""
        n = len(value)
        for s in range(0, n - 40):
            if (ok[s] and value[s] == 125 and ok[s + 20] and value[s + 20] == 125
                    and ok[s + 10] and ok[s + 30] and 104 <= value[s + 30] < value[s + 10] <= 111
                    and value[s + 10] - value[s + 30] == 1):
                return s
        return None

    @staticmethod
    def _word_at(d, pos, spb):
        """(value, ok, margin) of the word whose first bit window ends at pos + spb - 1."""
        idx = pos + spb - 1 + spb * np.arange(10)
        if idx[-1] >= len(d) or pos < 0:
            return None
        soft = d[idx]
        bits = (soft > 0).astype(int)
        value = int((bits[:7] * (1 << np.arange(7))).sum())
        ok = bits[7] * 4 + bits[8] * 2 + bits[9] == 7 - bits[:7].sum()
        return value, bool(ok), float(np.min(np.abs(soft)))

    def _track(self, d, pos, spb):
        """Best word near pos (follows a sound card clock that runs a bit off)."""
        best = None
        for shift in (0, -2, 2, -4, 4, -6, 6, -8, 8, -10, 10, -12, 12):
            word = self._word_at(d, pos + shift, spb)
            if word is None:
                return None, 0
            if word[1] and (best is None or word[2] > best[0][2] + 0.05):
                best = (word, shift)
        return (best if best is not None else (self._word_at(d, pos, spb), 0))

    def _read_call(self, d, pos, spb):
        w = 10 * spb                                  # one word
        # phasing: walk the DX/RX pairs to the one whose RX is 104
        for _ in range(9):
            dx, shift = self._track(d, pos, spb)
            if dx is None:
                return None
            pos += shift
            rx, rshift = self._track(d, pos + w, spb)
            if rx is None:
                return None
            if not (dx[1] and dx[0] == 125):
                break                                  # already at the format word
            pos += 2 * w
            if rx[1] and rx[0] == 104:
                break
        words, quality, end_seen = [], 0, 0
        for k in range(70):
            dx, shift = self._track(d, pos, spb)
            if dx is None:
                return None                            # call not complete yet
            pos += shift
            word = dx[0] if dx[1] else None
            if word is None:                           # RX copy, 4 words later
                rx, _ = self._track(d, pos + 4 * w + w, spb)
                if rx is None:
                    return None
                word = rx[0] if rx[1] else None
            quality += 1 if dx[1] else 0
            words.append(word)
            pos += 2 * w
            if word in CodanSelcallEncoder.END_SYMBOLS and k >= 5:
                end_seen += 1
                if end_seen >= 2:
                    return words, pos, quality
        return words, pos, quality
