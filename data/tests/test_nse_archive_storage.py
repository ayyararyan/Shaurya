from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from shaurya.data import storage
from shaurya.data.storage import (
    DEFAULT_NSE_ARCHIVE_MOUNT,
    DEFAULT_NSE_ARCHIVE_ROOT,
    EXPECTED_NSE_ARCHIVE_SHARE,
    NSE_ARCHIVE_ROOT_ENV,
    NSEArchiveLayout,
    NSEArchiveUnavailableError,
    resolve_data_catalog,
    resolve_raw_capture_root,
)
from shaurya.data_cli.capture_chain import _parser as chain_parser
from shaurya.data_cli.capture_dhan import _parser as dhan_parser


def test_configured_archive_prepares_one_iso_date_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "NSE"
    archive.mkdir()
    monkeypatch.setenv(NSE_ARCHIVE_ROOT_ENV, str(archive))

    raw = resolve_raw_capture_root(None, trading_date=date(2026, 8, 21))

    assert raw == archive / "2026-08-21" / "raw"
    assert {path.name for path in raw.parent.iterdir()} == {
        "raw",
        "metadata",
        "indexes",
        "derived",
    }


def test_explicit_test_root_does_not_require_or_create_server_layout(tmp_path: Path) -> None:
    explicit = tmp_path / "isolated-capture"

    assert (
        resolve_raw_capture_root(
            explicit,
            trading_date=date(2026, 8, 21),
            allow_nonarchive=True,
        )
        == explicit
    )
    assert not explicit.exists()


def test_default_catalog_uses_daily_metadata_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "NSE"
    archive.mkdir()
    monkeypatch.setenv(NSE_ARCHIVE_ROOT_ENV, str(archive))

    catalog = resolve_data_catalog(None, trading_date=date(2026, 8, 21))

    assert catalog == archive / "2026-08-21" / "metadata" / "datasets"


def test_controlled_local_catalog_sits_beside_capture_root(tmp_path: Path) -> None:
    raw = tmp_path / "raw"

    catalog = resolve_data_catalog(
        None,
        trading_date=date(2026, 8, 21),
        allow_nonarchive=True,
        nonarchive_capture_root=raw,
    )

    assert catalog == tmp_path / "datasets"


def test_nonarchive_capture_is_rejected_without_controlled_override(tmp_path: Path) -> None:
    explicit = tmp_path / "accidental-local-capture"

    with pytest.raises(NSEArchiveUnavailableError, match="non-archive capture root rejected"):
        resolve_raw_capture_root(explicit, trading_date=date(2026, 8, 21))


def test_archive_parent_traversal_cannot_bypass_nonarchive_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "NSE"
    archive.mkdir()
    monkeypatch.setenv(NSE_ARCHIVE_ROOT_ENV, str(archive))

    with pytest.raises(NSEArchiveUnavailableError, match="non-archive capture root rejected"):
        resolve_raw_capture_root(
            archive / ".." / "outside",
            trading_date=date(2026, 8, 21),
        )


def test_archive_root_must_be_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NSE_ARCHIVE_ROOT_ENV, "relative/NSE")

    with pytest.raises(NSEArchiveUnavailableError, match="absolute path"):
        NSEArchiveLayout.configured(date(2026, 8, 21))


def test_missing_smb_mount_refuses_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "is_mount", lambda _path: False)

    with pytest.raises(NSEArchiveUnavailableError, match="refusing local fallback"):
        storage._verify_default_smb_mount()


def test_production_constants_bind_the_iex_server_share() -> None:
    assert Path("/Volumes/Aryan") == DEFAULT_NSE_ARCHIVE_MOUNT
    assert Path("/Volumes/Aryan/NSE") == DEFAULT_NSE_ARCHIVE_ROOT
    assert EXPECTED_NSE_ARCHIVE_SHARE == "//Aryan@172.20.10.38/Aryan"


@pytest.mark.parametrize("parser_factory", [dhan_parser, chain_parser])
def test_live_capture_entry_points_default_to_central_archive(
    parser_factory: Callable[[], argparse.ArgumentParser],
) -> None:
    assert parser_factory().get_default("output_root") is None


@pytest.mark.parametrize("parser_factory", [dhan_parser, chain_parser])
def test_capture_and_consumer_entry_points_default_to_archive_catalogue(
    parser_factory: Callable[[], argparse.ArgumentParser],
) -> None:
    assert parser_factory().get_default("data_catalog") is None
