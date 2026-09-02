#!/usr/bin/env python3
"""Extract 09:20 and 09:21 option prints from the consolidated archive."""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

import pandas as pd


PATTERN = re.compile(
    r"(?:.*/)?data/(?P<year>\d{4})/"
    r"(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})__WEEK1__"
    r"(?P<tag>ATM(?:[+-]\d+)?)__(?P<side>CALL|PUT)__1m\.csv$"
)
TIMES = {b"09:20", b"09:21"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--option-zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows: list[tuple[object, ...]] = []
    with zipfile.ZipFile(args.option_zip) as archive:
        for name in archive.namelist():
            match = PATTERN.match(name)
            if match is None or int(match.group("year")) < 2023:
                continue
            tag = match.group("tag")
            offset = 0 if tag == "ATM" else int(tag[3:])
            with archive.open(name) as handle:
                next(handle, None)
                for raw in handle:
                    if len(raw) < 16 or raw[11:16] not in TIMES:
                        continue
                    fields = raw.decode("utf-8").rstrip().split(",")
                    if len(fields) < 6 or fields[0][:10] < "2023-01-23":
                        continue
                    try:
                        values = tuple(float(x) for x in fields[1:6])
                    except ValueError:
                        continue
                    rows.append(
                        (
                            fields[0][:10],
                            fields[0][11:16],
                            int(match.group("year")),
                            offset,
                            match.group("side"),
                            *values,
                        )
                    )
    columns = ["date", "time", "source_year", "offset", "side", "open", "high", "low", "close", "volume"]
    frame = pd.DataFrame(rows, columns=columns)
    frame = frame.drop_duplicates(["date", "time", "offset", "side"], keep="last")
    frame = frame.sort_values(["date", "time", "side", "offset"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)
    print(
        {
            "rows": len(frame),
            "dates": frame.date.nunique(),
            "date_min": frame.date.min(),
            "date_max": frame.date.max(),
            "time_counts": frame.groupby("time").size().to_dict(),
        }
    )


if __name__ == "__main__":
    main()
