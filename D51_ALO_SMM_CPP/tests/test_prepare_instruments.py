import datetime as dt
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_instruments.py"
SPEC = importlib.util.spec_from_file_location("prepare_instruments", SCRIPT)
assert SPEC and SPEC.loader
prepare_instruments = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_instruments)


class PrepareInstrumentsTests(unittest.TestCase):
    REAL_FUTURE_ROW = {
        "pScripRefKey": "NIFTY25AUG26FUT",
        "pExpiryDate": "1472135400",
    }

    def test_kotak_1980_epoch_expiry_matches_reference_key(self):
        expiry = prepare_instruments.parse_expiry(
            self.REAL_FUTURE_ROW["pExpiryDate"],
            self.REAL_FUTURE_ROW["pScripRefKey"],
            today=dt.date(2026, 8, 25),
        )
        self.assertEqual(expiry.astimezone(prepare_instruments.IST).date(), dt.date(2026, 8, 25))

    def test_expiry_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expiry mismatch"):
            prepare_instruments.parse_expiry(
                self.REAL_FUTURE_ROW["pExpiryDate"],
                "NIFTY18AUG26FUT",
                today=dt.date(2026, 8, 18),
            )

    def test_expired_reference_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expired contract"):
            prepare_instruments.parse_expiry(
                self.REAL_FUTURE_ROW["pExpiryDate"],
                self.REAL_FUTURE_ROW["pScripRefKey"],
                today=dt.date(2026, 8, 26),
            )

    def test_real_semicolon_strike_column_is_normalized(self):
        row = {"dStrikePrice;": "2435000"}
        raw = prepare_instruments.field(row, "strike")
        self.assertEqual(prepare_instruments.normalize_strike(raw), 24350.0)


if __name__ == "__main__":
    unittest.main()
