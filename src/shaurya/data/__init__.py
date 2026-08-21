"""Reusable market-data clients, capture, identity, historical, quality, and tape APIs."""

from .access import (
    DataAccess,
    DataCaptureSession,
    DataCatalog,
    DatasetAlreadyActiveError,
    DatasetUnavailableError,
)
from .alignment_analysis import analyze_alignment_tapes, analyze_tape_rows
from .capture import CaptureUniversePlan, DhanDepth20CapturePool
from .historical import BarInterval, HistoricalBar, HistoricalBarStore, fetch_historical_bars
from .instrument_master import (
    DailyInstrumentMasterStore,
    DhanDailyInstrumentMaster,
    DhanInstrumentIndex,
    KotakInstrumentIndex,
)
from .ofi_replication import (
    inspect_replication_capture,
    iter_session_rows,
    resolve_nifty_front_month_future,
)
from .option_chain import ValidatedOptionChain, fetch_and_validate_option_chain
from .quality import CollectorQualityAudit
from .tape import (
    CompleteLineJsonlTail,
    IndexedJsonlTapeReader,
    JsonlTapeReader,
    JsonlTapeWriter,
    TapeIndexBuilder,
    archive_tape,
)
from .trade_direction import (
    TRADE_ALIGNMENT_VERSION,
    TRADE_CLASSIFIER_VERSION,
    CaptureTradeDirectionClassifier,
    TradeClassification,
    classify_trade,
)

__all__ = [
    "BarInterval",
    "CaptureUniversePlan",
    "CaptureTradeDirectionClassifier",
    "CollectorQualityAudit",
    "CompleteLineJsonlTail",
    "DataAccess",
    "DataCaptureSession",
    "DataCatalog",
    "DatasetAlreadyActiveError",
    "DatasetUnavailableError",
    "DailyInstrumentMasterStore",
    "DhanDailyInstrumentMaster",
    "DhanDepth20CapturePool",
    "DhanInstrumentIndex",
    "HistoricalBar",
    "HistoricalBarStore",
    "IndexedJsonlTapeReader",
    "JsonlTapeReader",
    "JsonlTapeWriter",
    "KotakInstrumentIndex",
    "TRADE_ALIGNMENT_VERSION",
    "TRADE_CLASSIFIER_VERSION",
    "TradeClassification",
    "TapeIndexBuilder",
    "ValidatedOptionChain",
    "analyze_alignment_tapes",
    "analyze_tape_rows",
    "archive_tape",
    "fetch_and_validate_option_chain",
    "fetch_historical_bars",
    "inspect_replication_capture",
    "iter_session_rows",
    "resolve_nifty_front_month_future",
    "classify_trade",
]
