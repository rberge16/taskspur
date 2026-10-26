"""Erzeugt eine synthetische FIT-Datei (mit RR-Intervallen) für den Browser-Test: python tests/frontend/make_fit.py <ziel.fit>"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.fitgen import build_fit  # noqa: E402

rng = np.random.default_rng(11)
rr = (470 + rng.normal(0, 16, 2600)).tolist()
for i in range(120, 2600, 400):
    rr[i] = 150
Path(sys.argv[1]).write_bytes(build_fit(1200, rr))
