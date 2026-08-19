"""Reusable market-data clients, capture, identity, historical, quality, and tape APIs."""

from .alignment_analysis import analyze_alignment_tapes, analyze_tape_rows
from .capture import CaptureUniversePlan, DhanDepth20CapturePool
from .dhan_client import DhanClient, DhanCredentials
from .historical import BarInterval, HistoricalBar, HistoricalBarStore, fetch_historical_bars
from .instrument_master import (
    DailyInstrumentMasterStore,
    DhanDailyInstrumentMaster,
    DhanInstrumentIndex,
    KotakInstrumentIndex,
)
from .option_chain import ValidatedOptionChain, fetch_and_validate_option_chain
from .quality import CollectorQualityAudit
from .tape import JsonlTapeReader, JsonlTapeWriter
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
    "DailyInstrumentMasterStore",
    "DhanClient",
    "DhanCredentials",
    "DhanDailyInstrumentMaster",
    "DhanDepth20CapturePool",
    "DhanInstrumentIndex",
    "HistoricalBar",
    "HistoricalBarStore",
    "JsonlTapeReader",
    "JsonlTapeWriter",
    "KotakInstrumentIndex",
    "TRADE_ALIGNMENT_VERSION",
    "TRADE_CLASSIFIER_VERSION",
    "TradeClassification",
    "ValidatedOptionChain",
    "analyze_alignment_tapes",
    "analyze_tape_rows",
    "fetch_and_validate_option_chain",
    "fetch_historical_bars",
    "classify_trade",
]
