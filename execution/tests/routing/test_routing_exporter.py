from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "execution" / "ops" / "export_routing_snapshot.py"
FIXTURES = REPO_ROOT / "execution" / "tests" / "fixtures" / "routing"
SPEC = importlib.util.spec_from_file_location("routing_exporter", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load routing exporter")
EXPORTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXPORTER
SPEC.loader.exec_module(EXPORTER)


class RoutingExporterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="shaurya-routing-exporter-", dir="/private/tmp"
        )
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.dhan = self.root / "dhan.csv"
        self.kotak = self.root / "kotak.csv"
        self.universe = self.root / "universe.json"
        shutil.copyfile(FIXTURES / "dhan_master_2026-08-27.csv", self.dhan)
        shutil.copyfile(FIXTURES / "kotak_master_2026-08-27.csv", self.kotak)
        shutil.copyfile(FIXTURES / "universe_2026-08-27.json", self.universe)
        for path in (self.dhan, self.kotak, self.universe):
            path.chmod(0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def outputs(self, name: str) -> tuple[Path, Path]:
        directory = self.root / name
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        return directory / "routing_snapshot.json", directory / "routing_manifest.json"

    def export(self, name: str = "output"):
        snapshot, manifest = self.outputs(name)
        result = EXPORTER.export_snapshot(
            dhan_master=self.dhan,
            kotak_master=self.kotak,
            universe=self.universe,
            snapshot=snapshot,
            manifest=manifest,
            trading_date_text="2026-08-27",
        )
        return result, snapshot, manifest

    def rewrite_json(self, path: Path, update) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        update(value)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)

    def expect_code(self, code: str, call) -> None:
        with self.assertRaises(EXPORTER.ExportError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)

    def test_deterministic_complete_export_and_manifest(self) -> None:
        first, first_snapshot, first_manifest = self.export("one")
        second, second_snapshot, second_manifest = self.export("two")
        self.assertEqual(first_snapshot.read_bytes(), second_snapshot.read_bytes())
        self.assertEqual(first_manifest.read_bytes(), second_manifest.read_bytes())
        self.assertEqual(stat.S_IMODE(first_snapshot.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(first_manifest.stat().st_mode), 0o600)
        snapshot = json.loads(first_snapshot.read_text(encoding="utf-8"))
        manifest = json.loads(first_manifest.read_text(encoding="utf-8"))
        self.assertEqual(first.record_count, 2)
        self.assertEqual(len(snapshot["records"]), 2)
        self.assertEqual(
            [record["canonical_instrument_id"] for record in snapshot["records"]],
            sorted(record["canonical_instrument_id"] for record in snapshot["records"]),
        )
        self.assertNotIn("9003", first_snapshot.read_text(encoding="utf-8"))
        self.assertEqual(manifest["bytes"], len(first_snapshot.read_bytes()))
        self.assertEqual(
            manifest["snapshot_sha256"], hashlib.sha256(first_snapshot.read_bytes()).hexdigest()
        )
        self.assertEqual(
            manifest["requested_universe_sha256"],
            hashlib.sha256(self.universe.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["sources"],
            [
                {"broker": "dhan", "sha256": hashlib.sha256(self.dhan.read_bytes()).hexdigest()},
                {"broker": "kotak", "sha256": hashlib.sha256(self.kotak.read_bytes()).hexdigest()},
            ],
        )
        self.assertTrue(first_snapshot.read_bytes().endswith(b"\n"))
        self.assertEqual(first_snapshot.read_bytes().count(b"\n"), 1)
        self.assertNotIn(str(self.root), first_snapshot.read_text(encoding="utf-8"))

    def test_identical_existing_pair_is_idempotent(self) -> None:
        _, snapshot, manifest = self.export()
        before = (snapshot.stat().st_ino, manifest.stat().st_ino)
        result = EXPORTER.export_snapshot(
            dhan_master=self.dhan,
            kotak_master=self.kotak,
            universe=self.universe,
            snapshot=snapshot,
            manifest=manifest,
            trading_date_text="2026-08-27",
        )
        self.assertTrue(result.already_present)
        self.assertEqual(before, (snapshot.stat().st_ino, manifest.stat().st_ino))

    def test_stale_or_duplicate_universe_is_refused(self) -> None:
        self.rewrite_json(self.universe, lambda value: value.__setitem__("dhan_master_as_of_date", "2026-08-26"))
        self.expect_code("TRADING_DATE_MISMATCH", self.export)
        shutil.copyfile(FIXTURES / "universe_2026-08-27.json", self.universe)
        self.universe.chmod(0o600)
        self.rewrite_json(
            self.universe,
            lambda value: value["canonical_instrument_ids"].append(
                value["canonical_instrument_ids"][0]
            ),
        )
        self.expect_code("UNIVERSE_DUPLICATE", self.export)

    def test_duplicate_json_key_and_unknown_field_are_refused(self) -> None:
        self.universe.write_text(
            '{"schema_version":"1.0.0","schema_version":"1.0.0"}', encoding="utf-8"
        )
        self.universe.chmod(0o600)
        self.expect_code("UNIVERSE_MALFORMED", self.export)
        shutil.copyfile(FIXTURES / "universe_2026-08-27.json", self.universe)
        self.universe.chmod(0o600)
        self.rewrite_json(self.universe, lambda value: value.__setitem__("unknown", True))
        self.expect_code("UNIVERSE_MALFORMED", self.export)

    def test_missing_mapping_and_duplicate_route_are_refused(self) -> None:
        payload = self.kotak.read_text(encoding="utf-8")
        self.kotak.write_text(
            "\n".join(line for line in payload.splitlines() if not line.startswith("9002,")) + "\n",
            encoding="utf-8",
        )
        self.kotak.chmod(0o600)
        self.expect_code("MAPPING_MISSING", self.export)
        shutil.copyfile(FIXTURES / "kotak_master_2026-08-27.csv", self.kotak)
        self.kotak.chmod(0o600)
        self.kotak.write_text(
            self.kotak.read_text(encoding="utf-8").replace(
                "NIFTY03SEP2625000CE,NIFTY03SEP2625000CE",
                "NIFTY03SEP26FUT,NIFTY03SEP2625000CE",
            ),
            encoding="utf-8",
        )
        self.kotak.chmod(0o600)
        self.expect_code("ROUTE_DUPLICATE", self.export)

    def test_fractional_lot_and_tick_are_refused(self) -> None:
        original = self.dhan.read_text(encoding="utf-8")
        self.dhan.write_text(original.replace(",65,5.0000,NIFTY", ",65.5,5.0000,NIFTY", 1), encoding="utf-8")
        self.dhan.chmod(0o600)
        self.expect_code("LOT_INVALID", self.export)
        self.dhan.write_text(original.replace(",65,5.0000,NIFTY", ",65,0.5,NIFTY", 1), encoding="utf-8")
        self.dhan.chmod(0o600)
        self.expect_code("TICK_INVALID", self.export)

    def test_malformed_master_header_is_refused(self) -> None:
        self.dhan.write_text("bad,header\n1,2\n", encoding="utf-8")
        self.dhan.chmod(0o600)
        self.expect_code("MASTER_MALFORMED", self.export)

    def test_unsafe_partial_and_different_outputs_are_refused(self) -> None:
        snapshot, manifest = self.outputs("partial")
        snapshot.write_text("partial", encoding="utf-8")
        snapshot.chmod(0o600)
        self.expect_code(
            "OUTPUT_PARTIAL",
            lambda: EXPORTER.export_snapshot(
                dhan_master=self.dhan,
                kotak_master=self.kotak,
                universe=self.universe,
                snapshot=snapshot,
                manifest=manifest,
                trading_date_text="2026-08-27",
            ),
        )
        _, snapshot, manifest = self.export("different")
        snapshot.write_text("different", encoding="utf-8")
        snapshot.chmod(0o600)
        self.expect_code(
            "OUTPUT_EXISTS_DIFFERENT",
            lambda: EXPORTER.export_snapshot(
                dhan_master=self.dhan,
                kotak_master=self.kotak,
                universe=self.universe,
                snapshot=snapshot,
                manifest=manifest,
                trading_date_text="2026-08-27",
            ),
        )

    def test_symlink_target_and_unsafe_parent_are_refused(self) -> None:
        snapshot, manifest = self.outputs("symlink")
        target = self.root / "foreign"
        target.write_text("foreign", encoding="utf-8")
        snapshot.symlink_to(target)
        self.expect_code(
            "OUTPUT_UNSAFE",
            lambda: EXPORTER.export_snapshot(
                dhan_master=self.dhan,
                kotak_master=self.kotak,
                universe=self.universe,
                snapshot=snapshot,
                manifest=manifest,
                trading_date_text="2026-08-27",
            ),
        )
        unsafe = self.root / "unsafe"
        unsafe.mkdir(mode=0o755)
        self.expect_code(
            "OUTPUT_PARENT_UNSAFE",
            lambda: EXPORTER.export_snapshot(
                dhan_master=self.dhan,
                kotak_master=self.kotak,
                universe=self.universe,
                snapshot=unsafe / "snapshot.json",
                manifest=unsafe / "manifest.json",
                trading_date_text="2026-08-27",
            ),
        )

    def test_unsafe_input_and_output_leaf_are_refused(self) -> None:
        actual = self.root / "actual-universe.json"
        shutil.copyfile(self.universe, actual)
        actual.chmod(0o600)
        self.universe.unlink()
        self.universe.symlink_to(actual)
        self.expect_code("INPUT_UNSAFE", self.export)

        self.universe.unlink()
        shutil.copyfile(FIXTURES / "universe_2026-08-27.json", self.universe)
        self.universe.chmod(0o666)
        self.expect_code("INPUT_UNSAFE", self.export)

        self.universe.chmod(0o600)
        output = self.root / "unsafe-name"
        output.mkdir(mode=0o700)
        self.expect_code(
            "OUTPUT_PATH_INVALID",
            lambda: EXPORTER.export_snapshot(
                dhan_master=self.dhan,
                kotak_master=self.kotak,
                universe=self.universe,
                snapshot=output / "snapshot name.json",
                manifest=output / "manifest.json",
                trading_date_text="2026-08-27",
            ),
        )

    def test_cli_emits_only_stable_markers(self) -> None:
        snapshot, manifest = self.outputs("cli")
        command = [
            sys.executable,
            str(MODULE_PATH),
            "--dhan-master", str(self.dhan),
            "--kotak-master", str(self.kotak),
            "--universe", str(self.universe),
            "--snapshot", str(snapshot),
            "--manifest", str(manifest),
            "--trading-date", "2026-08-27",
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^\[ROUTING_EXPORT_OK\] state=created records=2 snapshot_sha256=[0-9a-f]{64}\n$")
        self.assertEqual(result.stderr, "")

    def test_exporter_has_only_public_data_imports_and_no_network_import(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        self.assertIn("shaurya.contracts", imported)
        self.assertIn("shaurya.data", imported)
        self.assertFalse(
            imported
            & {
                "aiohttp",
                "http",
                "requests",
                "shaurya.data.dhan_client",
                "socket",
                "urllib",
            }
        )


if __name__ == "__main__":
    unittest.main()
