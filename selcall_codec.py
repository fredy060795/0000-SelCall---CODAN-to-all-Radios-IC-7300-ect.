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

    def build_words(self, call_id, our_id, fmt=FMT_SELCALL, category=100):
        to = self.split_id(call_id, "Call ID")
        frm = self.split_id(our_id, "Our ID")
        if len(to) != len(frm):
            raise ValueError("Call ID and Our ID must both have 4 digits or both have 6 digits.")
        # Message in DX order: format, called address, category, self ID, EOS x3
        dx = [fmt] + to + [category] + frm + [self.EOS_ARQ] * 3
        # RX copy lags the DX copy by 4 words (time diversity)
        rx = [dx[0], dx[0]] + dx[:-2]
        words = []
        for ph in self.PHASING_RX:
            words += [self.PHASING_DX, ph]
        for d, r in zip(dx, rx):
            words += [d, r]
        return words

    def build_bits(self, call_id, our_id, fmt=FMT_SELCALL, category=100, preamble_s=2.0):
        n_pre = max(20, int(round(preamble_s * self.BAUD)))
        bits = [i & 1 for i in range(n_pre)]  # dot pattern 0101...
        for w in self.build_words(call_id, our_id, fmt, category):
            bits += self.word_bits(w)
        return bits

    def generate(self, audio_gen, call_id, our_id, fmt=FMT_SELCALL, category=100, preamble_s=2.0):
        bits = self.build_bits(call_id, our_id, fmt, category, preamble_s)
        return audio_gen.generate_fsk(bits, self.BAUD, self.F_ZERO, self.F_ONE)
