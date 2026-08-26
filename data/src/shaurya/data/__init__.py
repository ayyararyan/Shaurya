"""Reusable market-data clients, capture, identity, historical, quality, and tape APIs."""

from .access import (
    DataAccess,
    DataCaptureSession,
    DataCatalog,
    DatasetAlreadyActiveError,
    DatasetUnavailableError,
)
from .capture import CaptureUniversePlan, DhanDepth20CapturePool
from .historical import BarInterval, HistoricalBar, HistoricalBarStore, fetch_historical_bars
from .instrument_master import (
    DailyInstrumentMasterStore,
    DhanDailyInstrumentMaster,
    DhanInstrumentIndex,
    KotakInstrumentIndex,
)
from .option_chain import ValidatedOptionChain, fetch_and_validate_option_chain
from .quality import CollectorQualityAudit
from .storage import (
    NSEArchiveUnavailableError,
    resolve_data_catalog,
    resolve_raw_capture_root,
)
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
from .universe import ChainUniverse, select_chain_universe

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
    "NSEArchiveUnavailableError",
    "TRADE_ALIGNMENT_VERSION",
    "TRADE_CLASSIFIER_VERSION",
    "TradeClassification",
    "TapeIndexBuilder",
    "ValidatedOptionChain",
    "archive_tape",
    "fetch_and_validate_option_chain",
    "fetch_historical_bars",
    "classify_trade",
    "ChainUniverse",
    "resolve_data_catalog",
    "resolve_raw_capture_root",
    "select_chain_universe",
]
