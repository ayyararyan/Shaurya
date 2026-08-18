"""DAT-09 diagnostic: measure Dhan's real concurrent-subscription cap per depth tier.

Not a production capture path — a one-off empirical probe. TASKS.md's DAT-09 needs the real
concurrent-instrument cap per tier, which the documented "50/1 instruments per message"
batching rule implies but does not prove (see GCP_SCALING.md §3). This script:

  1. 20-level: subscribes ~200+ real NIFTY instruments (two near expiries, near-ATM strikes,
     plus front/next futures) on one socket via DhanLiveStream (which already batches 50 per
     message), and checks via the written tape which of the subscribed security_ids actually
     received at least one packet in the capture window.
  2. 200-level: subscribes several *different* single instruments on one socket via sequential
     flat subscribe messages (bypassing DhanLiveStream's one-instrument guard, which is correct
     for production but blocks this specific question) and tallies packets per security_id to
     see whether more than one instrument's book actually arrives on that socket.

Read-only market data only. Never place, modify, or cancel an order.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from websockets.asyncio.client import connect

from shaurya.contracts.artifacts import ArtifactManifest
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
    OptionType,
)
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import (
    DhanLiveStream,
    DhanStreamConfig,
    ParsedDisconnect,
    StreamMetrics,
    parse_deep_packets,
)
from shaurya.data.tape import JsonlTapeWriter

REPO = Path(__file__).resolve().parents[1]
MASTER = REPO / "data" / "api-scrip-master.csv"
CRED_PATH = Path("/Users/maheit/.cache/openclaw/gdrive/My Drive/Market Making/dhan_credentials.env")
DURATION_SECONDS = 40.0


def _mapping(row: dict, symbol: str) -> DhanInstrumentMapping:
    kind = (
        InstrumentKind.OPTION if row["SEM_INSTRUMENT_NAME"] == "OPTIDX" else InstrumentKind.FUTURE
    )
    option_type = OptionType(row["SEM_OPTION_TYPE"]) if kind is InstrumentKind.OPTION else None
    strike = Decimal(row["SEM_STRIKE_PRICE"]) if kind is InstrumentKind.OPTION else None
    expiry = date.fromisoformat(row["SEM_EXPIRY_DATE"].split(" ")[0])
    instrument = InstrumentId(
        exchange="NSE",
        segment=ExchangeSegment.NSE_FNO,
        underlying=symbol,
        kind=kind,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )
    return DhanInstrumentMapping(
        instrument=instrument,
        security_id=row["SEM_SMST_SECURITY_ID"],
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol=row["SEM_TRADING_SYMBOL"],
        lot_size=int(float(row["SEM_LOT_UNITS"])) if row["SEM_LOT_UNITS"] else None,
        tick_size_paise=Decimal(row["SEM_TICK_SIZE"]) if row["SEM_TICK_SIZE"] else None,
        as_of_date=date.today(),
        source=str(MASTER),
    )


def build_nifty_universe() -> list[DhanInstrumentMapping]:
    rows = list(csv.DictReader(MASTER.open(encoding="utf-8-sig")))
    opts = [
        r
        for r in rows
        if r["SEM_EXM_EXCH_ID"] == "NSE"
        and r["SEM_INSTRUMENT_NAME"] == "OPTIDX"
        and r["SEM_TRADING_SYMBOL"].startswith("NIFTY-")
        and r["SEM_EXPIRY_DATE"] in ("2026-08-25 14:30:00", "2026-09-01 14:30:00")
        and 23000 <= float(r["SEM_STRIKE_PRICE"]) <= 25500
    ]
    futs = [
        r
        for r in rows
        if r["SEM_EXM_EXCH_ID"] == "NSE"
        and r["SEM_INSTRUMENT_NAME"] == "FUTIDX"
        and r["SEM_TRADING_SYMBOL"] in ("NIFTY-Aug2026-FUT", "NIFTY-Sep2026-FUT")
    ]
    return [_mapping(r, "NIFTY") for r in opts + futs]


async def run_20level_probe(instruments: list[DhanInstrumentMapping]) -> dict:
    credentials = DhanCredentials.from_env_file(CRED_PATH)
    manifest = ArtifactManifest.create(REPO / "artifacts" / "dat09-probe-depth20")
    metrics = StreamMetrics()
    writer = JsonlTapeWriter(manifest, fsync_every=200)
    stream = DhanLiveStream(
        credentials,
        instruments,
        writer.write,
        run_id=str(manifest.run_id),
        config=DhanStreamConfig(enable_standard_feed=False, enable_20_level_depth=True),
        metrics=metrics,
    )
    task = asyncio.create_task(stream.run())
    done, _ = await asyncio.wait({task}, timeout=DURATION_SECONDS)
    if task not in done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    else:
        with contextlib.suppress(BaseException):
            task.result()
    writer.close()
    manifest.complete(rows=writer.rows_written, elapsed_seconds=DURATION_SECONDS)
    tape_path = manifest.run_dir / f"tape_{manifest.run_id}.jsonl"
    seen: set[str] = set()
    for line in tape_path.read_text().splitlines():
        seen.add(json.loads(line)["broker_security_id"])
    subscribed = {m.security_id for m in instruments}
    return {
        "subscribed_count": len(subscribed),
        "received_at_least_one_packet_count": len(seen & subscribed),
        "never_received_count": len(subscribed - seen),
        "never_received_sample": sorted(subscribed - seen)[:15],
        "rows": writer.rows_written,
        "run_dir": str(manifest.run_dir),
        "metrics_snapshot": metrics.snapshot(DURATION_SECONDS),
    }


async def run_200level_probe(instruments: list[DhanInstrumentMapping]) -> dict:
    credentials = DhanCredentials.from_env_file(CRED_PATH)
    url = (
        f"wss://full-depth-api.dhan.co/?token={credentials.access_token}"
        f"&clientId={credentials.client_id}&authType=2"
    )
    counts: Counter[str] = Counter()
    sizes: dict[str, int] = defaultdict(int)
    async with connect(url, ping_interval=None, open_timeout=10, max_size=4 * 1024 * 1024) as ws:
        for mapping in instruments:
            await ws.send(
                json.dumps(
                    {
                        "RequestCode": 23,
                        "ExchangeSegment": mapping.exchange_segment.value,
                        "SecurityId": mapping.security_id,
                    }
                )
            )
            await asyncio.sleep(0.05)
        end = time.monotonic() + DURATION_SECONDS
        while time.monotonic() < end:
            try:
                message = await asyncio.wait_for(
                    ws.recv(), timeout=max(end - time.monotonic(), 0.1)
                )
            except TimeoutError:
                break
            if not isinstance(message, bytes):
                continue
            for packet in parse_deep_packets(message, depth_levels=200):
                if isinstance(packet, ParsedDisconnect):
                    continue
                key = str(packet.security_id)
                counts[key] += 1
                sizes[key] = packet.raw_size
    subscribed = {m.security_id: m.trading_symbol for m in instruments}
    return {
        "subscribed": subscribed,
        "packet_counts_by_security_id": dict(counts),
        "instruments_with_any_packet": sorted(set(counts) & set(subscribed)),
        "instruments_with_zero_packets": sorted(set(subscribed) - set(counts)),
    }


async def main() -> None:
    universe = build_nifty_universe()
    depth200_probe_ids = {"58072", "68407"}  # Aug/Sep NIFTY futures, guaranteed liquid
    depth200_instruments = [m for m in universe if m.security_id in depth200_probe_ids]
    extra_strikes = [m for m in universe if m.instrument.kind.value == "option"][:3]
    depth200_instruments += extra_strikes

    results = await asyncio.gather(
        run_20level_probe(universe),
        run_200level_probe(depth200_instruments),
    )
    print(
        json.dumps(
            {"depth20_probe": results[0], "depth200_probe": results[1]}, indent=2, default=str
        )
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
