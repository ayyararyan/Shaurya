from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from shaurya.contracts.tape import DepthLevel, QualityFlag, TapeRow, TradeSide
from shaurya.data.trade_direction import (
    TRADE_ALIGNMENT_VERSION,
    TRADE_CLASSIFIER_VERSION,
    CaptureTradeDirectionClassifier,
    ClassificationReason,
    classify_trade,
)

RUN_ID = "sha-20260819T010000.000000Z-dat14000"
INSTRUMENT_ID = "NSE:NSE_FNO:NIFTY:future:2026-08-25"
T0 = datetime(2026, 8, 19, 3, 45, tzinfo=UTC)


def _classification(**overrides: object):
    values: dict[str, object] = {
        "last_price": 100.5,
        "best_bid": 100.0,
        "best_ask": 101.0,
        "last_differing_trade_price": 100.0,
        "quote_age_ms": 10.0,
        "quote_freshness_bound_ms": 1000.0,
        "cumulative_volume_increment": 10,
        "last_quantity": 10,
    }
    values.update(overrides)
    return classify_trade(**values)  # type: ignore[arg-type]


def test_quote_rule_above_mid_is_buy() -> None:
    result = _classification(last_price=100.75)
    assert result.side is TradeSide.BUY
    assert result.reason is ClassificationReason.QUOTE_RULE


def test_quote_rule_below_mid_is_sell() -> None:
    result = _classification(last_price=100.25)
    assert result.side is TradeSide.SELL
    assert result.reason is ClassificationReason.QUOTE_RULE


def test_at_mid_uptick_is_buy() -> None:
    result = _classification(last_differing_trade_price=100.0)
    assert result.side is TradeSide.BUY
    assert result.reason is ClassificationReason.TICK_RULE


def test_at_mid_downtick_is_sell() -> None:
    result = _classification(last_differing_trade_price=101.0)
    assert result.side is TradeSide.SELL
    assert result.reason is ClassificationReason.TICK_RULE


def test_at_mid_without_prior_differing_price_is_explicitly_unclassified() -> None:
    result = _classification(last_differing_trade_price=None)
    assert result.side is TradeSide.UNCLASSIFIED
    assert result.reason is ClassificationReason.NO_PRIOR_DIFFERING_TRADE
    assert not result.degraded


def test_stale_quote_is_degraded_and_unclassified() -> None:
    result = _classification(quote_age_ms=1000.1, quote_freshness_bound_ms=1000.0)
    assert result.side is TradeSide.UNCLASSIFIED
    assert result.reason is ClassificationReason.STALE_QUOTE
    assert result.degraded


def test_volume_increment_larger_than_last_quantity_is_coalesced() -> None:
    result = _classification(cumulative_volume_increment=11, last_quantity=10)
    assert result.coalesced


def _row(
    *,
    sequence: int,
    event_type: str,
    received_at: datetime,
    update_side: str | None = None,
    bids: tuple[DepthLevel, ...] = (),
    asks: tuple[DepthLevel, ...] = (),
    last_price: float | None = None,
    last_quantity: int | None = None,
    cumulative_volume: int | None = None,
) -> TapeRow:
    return TapeRow(
        run_id=RUN_ID,
        receive_sequence=sequence,
        connection_epoch=1,
        source="dhan",
        event_type=event_type,
        instrument_id=INSTRUMENT_ID,
        broker_security_id="58072",
        exchange_segment="NSE_FNO",
        receive_ts=received_at,
        raw_message_size_bytes=332,
        update_side=update_side,
        bids=bids,
        asks=asks,
        last_price=last_price,
        last_quantity=last_quantity,
        cumulative_volume=cumulative_volume,
    )


def test_alignment_uses_latest_complete_past_depth_state_and_records_both_side_times() -> None:
    classifier = CaptureTradeDirectionClassifier(quote_freshness_seconds=1.0)
    bid20 = (DepthLevel(100.0, 10, 1),)
    ask20 = (DepthLevel(101.0, 10, 1),)
    bid200 = (DepthLevel(100.2, 10, 1),)
    ask200 = (DepthLevel(100.8, 10, 1),)
    classifier.process(
        _row(
            sequence=1,
            event_type="depth20",
            received_at=T0,
            update_side="bid",
            bids=bid20,
        )
    )
    classifier.process(
        _row(
            sequence=2,
            event_type="depth20",
            received_at=T0 + timedelta(milliseconds=100),
            update_side="ask",
            bids=bid20,
            asks=ask20,
        )
    )
    classifier.process(
        _row(
            sequence=3,
            event_type="depth200",
            received_at=T0 + timedelta(milliseconds=200),
            update_side="bid",
            bids=bid200,
        )
    )
    classifier.process(
        _row(
            sequence=4,
            event_type="depth200",
            received_at=T0 + timedelta(milliseconds=300),
            update_side="ask",
            bids=bid200,
            asks=ask200,
        )
    )
    classifier.process(
        _row(
            sequence=5,
            event_type="full",
            received_at=T0 + timedelta(milliseconds=350),
            last_price=100.4,
            last_quantity=10,
            cumulative_volume=100,
        )
    )
    classified = classifier.process(
        _row(
            sequence=6,
            event_type="full",
            received_at=T0 + timedelta(milliseconds=400),
            last_price=100.6,
            last_quantity=5,
            cumulative_volume=110,
        )
    )

    assert classified.trade_quote_channel == "depth200"
    assert classified.trade_quote_bid == 100.2
    assert classified.trade_quote_ask == 100.8
    assert classified.trade_quote_bid_receive_ts == T0 + timedelta(milliseconds=200)
    assert classified.trade_quote_ask_receive_ts == T0 + timedelta(milliseconds=300)
    assert classified.trade_quote_receive_ts == T0 + timedelta(milliseconds=300)
    assert classified.trade_quote_age_ms == 200.0
    assert classified.trade_side is TradeSide.BUY
    assert classified.trade_classifier_version == TRADE_CLASSIFIER_VERSION
    assert classified.trade_alignment_version == TRADE_ALIGNMENT_VERSION
    assert classified.cumulative_volume_increment == 10
    assert classified.trade_coalesced
    assert QualityFlag.COALESCED_PRINT in classified.quality_flags


def test_no_depth_quote_is_retained_as_explicit_degraded_classification() -> None:
    classifier = CaptureTradeDirectionClassifier()
    baseline = _row(
        sequence=1,
        event_type="quote",
        received_at=T0,
        last_price=100.0,
        last_quantity=5,
        cumulative_volume=100,
    )
    classifier.process(baseline)
    classified = classifier.process(
        replace(
            baseline,
            receive_sequence=2,
            receive_ts=T0 + timedelta(milliseconds=10),
            last_price=101.0,
            cumulative_volume=105,
        )
    )
    assert classified.trade_side is TradeSide.UNCLASSIFIED
    assert classified.trade_classification_reason == "no_prevailing_quote"
    assert classified.trade_classification_degraded
    assert QualityFlag.TRADE_CLASSIFICATION_DEGRADED in classified.quality_flags
