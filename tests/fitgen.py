"""Minimaler FIT-Schreiber für Tests (synthetische Daten – keine echten Aktivitäten im Repository)."""
import struct

_CRC = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401, 0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]


def crc16(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= tmp ^ _CRC[byte & 0xF]
        tmp = _CRC[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= tmp ^ _CRC[(byte >> 4) & 0xF]
    return crc


BASE = {"enum": (0x00, "B", 1), "uint8": (0x02, "B", 1), "uint16": (0x84, "H", 2), "uint32": (0x86, "I", 4)}


def _define(local: int, global_num: int, fields: list[tuple[int, str, int]]) -> bytes:
    """fields: (field_num, base_type, count)"""
    out = struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields))
    for num, base, count in fields:
        out += struct.pack("<BBB", num, BASE[base][2] * count, BASE[base][0])
    return out


def _data(local: int, fields: list[tuple[int, str, int]], values: list) -> bytes:
    out = bytes([local])
    for (num, base, count), v in zip(fields, values):
        vals = v if count > 1 else [v]
        out += struct.pack("<" + BASE[base][1] * count, *vals)
    return out


FIT_EPOCH = 631065600


def build_fit(seconds=1200, rr_ms=None, sport=1, start_unix=1_790_000_000) -> bytes:
    """seconds Records im Sekundentakt (HF 120–160, Leistung, Tempo), optional RR-Intervalle (ms) als hrv-Nachrichten."""
    ts0 = start_unix - FIT_EPOCH
    body = b""
    fid = [(0, "enum", 1), (1, "uint16", 1), (4, "uint32", 1)]
    body += _define(0, 0, fid) + _data(0, fid, [4, 255, ts0])
    rec = [(253, "uint32", 1), (3, "uint8", 1), (7, "uint16", 1), (6, "uint16", 1), (2, "uint16", 1), (5, "uint32", 1), (4, "uint8", 1)]
    body += _define(1, 20, rec)
    dist = 0.0
    for i in range(seconds):
        speed = 2.8 + 0.4 * ((i // 120) % 2)
        dist += speed
        hr = 120 + (i * 40) // seconds
        body += _data(1, rec, [ts0 + i, hr, 250 + (i % 7), int(speed * 1000), int((100 + 5 * (i % 30) / 30 + 500) * 5), int(dist * 100), 78])
    if rr_ms:
        hrv = [(0, "uint16", 5)]
        body += _define(2, 78, hrv)
        for k in range(0, len(rr_ms), 5):
            chunk = [int(round(x)) for x in rr_ms[k:k + 5]]
            chunk += [0xFFFF] * (5 - len(chunk))
            body += _data(2, hrv, [chunk])
    lap = [(253, "uint32", 1), (2, "uint32", 1), (7, "uint32", 1), (9, "uint32", 1), (15, "uint8", 1)]
    body += _define(3, 19, lap)
    part = seconds // 3
    for n in range(3):
        body += _data(3, lap, [ts0 + (n + 1) * part, ts0 + n * part, part * 1000, int(dist / 3 * 100), 130 + 10 * n])
    ses = [(253, "uint32", 1), (5, "enum", 1), (8, "uint32", 1), (9, "uint32", 1), (16, "uint8", 1)]
    body += _define(4, 18, ses) + _data(4, ses, [ts0 + seconds, sport, seconds * 1000, int(dist * 100), 140])
    header = struct.pack("<BBHI4s", 14, 0x20, 2132, len(body), b".FIT")
    header += struct.pack("<H", crc16(header))
    return header + body + struct.pack("<H", crc16(header + body))
