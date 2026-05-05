"""Historical data loading interfaces for the Phase 5 backtest engine."""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional


@dataclass(frozen=True)
class HistoricalTickRecord:
    """Normalized tick record used by the replay harness."""

    timestamp_utc: datetime
    exchange: str
    symbol: str
    bid: float
    ask: float
    last_price: float
    volume: float

    @property
    def timestamp_ms(self) -> int:
        return int(self.timestamp_utc.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    value = value.strip()
    if not value:
        raise ValueError("empty timestamp")

    if value.isdigit():
        raw = int(value)
        if raw > 10**14:
            raw = raw // 1_000_000
        elif raw > 10**11:
            raw = raw // 1_000
        return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    return _as_utc(parsed)


class HistoricalTickLoader:
    """Load historical market data for deterministic replay."""

    def __init__(
        self,
        symbols: list[str],
        start_date: datetime,
        end_date: datetime,
        source_path: Optional[Path] = None,
        cache_path: Optional[Path] = None,
    ) -> None:
        self.symbols = symbols
        self.start_date = _as_utc(start_date)
        self.end_date = _as_utc(end_date)
        self.source_path = source_path
        self.cache_path = cache_path

    def _resolve_source(self) -> Optional[Path]:
        if self.source_path is not None:
            if self.source_path.exists():
                return self.source_path

        if self.cache_path is not None and self.cache_path.exists():
            return self.cache_path

        candidates = [
            Path("artifacts") / "backtest_data" / "ticks_raw.csv",
            Path("artifacts") / "backtest_data" / "ticks_raw.jsonl",
            Path("artifacts") / "backtest_data" / "ticks_raw.sqlite",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _iter_source_rows(self, source: Path) -> Iterable[HistoricalTickRecord]:
        suffix = source.suffix.lower()
        if suffix == ".sqlite":
            yield from self._read_sqlite(source)
        elif suffix == ".jsonl":
            yield from self._read_jsonl(source)
        else:
            yield from self._read_csv(source)

    def _read_csv(self, path: Path) -> Iterable[HistoricalTickRecord]:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield self._row_to_record(row)

    def _read_jsonl(self, path: Path) -> Iterable[HistoricalTickRecord]:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield self._row_to_record(json.loads(line))

    def _read_sqlite(self, path: Path) -> Iterable[HistoricalTickRecord]:
        conn = sqlite3.connect(path)
        try:
            cur = conn.execute(
                """
                SELECT timestamp_utc, exchange, symbol, bid, ask, last_price, volume
                FROM historical_ticks
                WHERE timestamp_utc >= ? AND timestamp_utc <= ?
                ORDER BY timestamp_utc ASC
                """,
                (self.start_date.isoformat(), self.end_date.isoformat()),
            )
            for row in cur.fetchall():
                yield HistoricalTickRecord(
                    timestamp_utc=_parse_timestamp(str(row[0])),
                    exchange=str(row[1]),
                    symbol=str(row[2]),
                    bid=float(row[3]),
                    ask=float(row[4]),
                    last_price=float(row[5]),
                    volume=float(row[6]),
                )
        finally:
            conn.close()

    def _row_to_record(self, row: dict[str, object]) -> HistoricalTickRecord:
        timestamp_key = next(
            (k for k in ("timestamp_utc", "timestamp", "ts", "open_time", "open_time_ms") if k in row),
            None,
        )
        if timestamp_key is None:
            raise ValueError("historical tick row is missing a timestamp field")

        exchange_key = next((k for k in ("exchange", "exchange_id", "source") if k in row), None)
        symbol_key = next((k for k in ("symbol", "pair") if k in row), None)
        bid_key = next((k for k in ("bid", "best_bid") if k in row), None)
        ask_key = next((k for k in ("ask", "best_ask") if k in row), None)
        last_key = next((k for k in ("last_price", "last", "close", "price") if k in row), None)
        volume_key = next((k for k in ("volume", "volume_24h", "qty") if k in row), None)

        if None in {exchange_key, symbol_key, bid_key, ask_key, last_key, volume_key}:
            raise ValueError(f"historical tick row missing required fields: {row}")

        return HistoricalTickRecord(
            timestamp_utc=_parse_timestamp(str(row[timestamp_key])),
            exchange=str(row[exchange_key]),
            symbol=str(row[symbol_key]),
            bid=float(row[bid_key]),
            ask=float(row[ask_key]),
            last_price=float(row[last_key]),
            volume=float(row[volume_key]),
        )

    def _write_cache(self, records: list[HistoricalTickRecord]) -> None:
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.cache_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_ticks (
                    timestamp_utc TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    bid REAL NOT NULL,
                    ask REAL NOT NULL,
                    last_price REAL NOT NULL,
                    volume REAL NOT NULL
                )
                """
            )
            conn.execute("DELETE FROM historical_ticks")
            conn.executemany(
                "INSERT INTO historical_ticks VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        rec.timestamp_utc.isoformat(),
                        rec.exchange,
                        rec.symbol,
                        rec.bid,
                        rec.ask,
                        rec.last_price,
                        rec.volume,
                    )
                    for rec in records
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def load(self) -> list[HistoricalTickRecord]:
        """Return all historical ticks for the configured date range."""

        source = self._resolve_source()
        records: list[HistoricalTickRecord] = []

        if source is None:
            raise FileNotFoundError(
                "No historical tick source found. Provide source_path or create artifacts/backtest_data/ticks_raw.csv"
            )

        if source.suffix.lower() == ".sqlite":
            records = list(self._read_sqlite(source))
        else:
            records = [
                rec
                for rec in self._iter_source_rows(source)
                if rec.symbol in self.symbols and self.start_date <= rec.timestamp_utc <= self.end_date
            ]
            records.sort(key=lambda rec: rec.timestamp_utc)
            self._write_cache(records)

        return records

    def iterator(self) -> Iterator[HistoricalTickRecord]:
        """Stream historical ticks in chronological order."""

        yield from self.load()
