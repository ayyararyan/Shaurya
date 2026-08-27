#include "shaurya/execution/ipc_protocol.hpp"

#include "shaurya/execution/canonical_json.hpp"

#include <algorithm>
#include <limits>
#include <set>
#include <utility>

namespace shaurya::execution {
namespace {
[[noreturn]] void fail(std::string code) { throw IpcProtocolError(std::move(code)); }
const JsonValue& required(const JsonObject& object, std::string_view key) {
  const auto iterator = object.find(key); if (iterator == object.end()) fail("ipc_missing_field");
  return iterator->second;
}
void exact(const JsonObject& object, std::initializer_list<std::string_view> required_fields,
           std::initializer_list<std::string_view> optional_fields = {}) {
  std::set<std::string_view> allowed(required_fields);
  allowed.insert(optional_fields.begin(), optional_fields.end());
  for (const auto field : required_fields) if (!object.contains(field)) fail("ipc_missing_field");
  for (const auto& [key, unused] : object) { (void)unused; if (!allowed.contains(key)) fail("ipc_unknown_field"); }
}
std::string string(const JsonObject& object, std::string_view key, std::size_t maximum = 128U) {
  try {
    const auto& value = json_string(required(object, key), key);
    if (value.empty() || value.size() > maximum) fail("ipc_invalid_string");
    return value;
  } catch (const JsonError&) { fail("ipc_invalid_field"); }
}
std::uint64_t number(const JsonObject& object, std::string_view key) {
  try { return json_uint64(required(object, key), key); }
  catch (const JsonError&) { fail("ipc_invalid_field"); }
}
std::int64_t signed_number(const JsonObject& object, std::string_view key) {
  try { return json_int64(required(object, key), key); }
  catch (const JsonError&) { fail("ipc_invalid_field"); }
}
std::optional<std::int64_t> nullable_signed_number(const JsonObject& object,
                                                   std::string_view key) {
  const auto& value = required(object, key);
  if (std::holds_alternative<std::nullptr_t>(value.value)) return std::nullopt;
  try { return json_int64(value, key); }
  catch (const JsonError&) { fail("ipc_invalid_field"); }
}
bool digest(std::string_view value) {
  return value.size() == 64U && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= '0' && item <= '9') || (item >= 'a' && item <= 'f');
  });
}
PeerRole role(std::string_view value) {
  if (value == "market_publisher") return PeerRole::MarketPublisher;
  if (value == "strategy_client") return PeerRole::StrategyClient;
  fail("ipc_role_invalid");
}
IpcMessageKind kind(std::string_view value) {
  if (value == "market_observation") return IpcMessageKind::MarketObservation;
  if (value == "strategy_book_observation") return IpcMessageKind::StrategyBookObservation;
  if (value == "order_intent") return IpcMessageKind::OrderIntent;
  if (value == "event_acknowledgement") return IpcMessageKind::EventAcknowledgement;
  if (value == "execution_event") return IpcMessageKind::ExecutionEvent;
  fail("ipc_kind_invalid");
}
std::string kind_name(IpcMessageKind value) {
  switch (value) {
    case IpcMessageKind::MarketObservation: return "market_observation";
    case IpcMessageKind::StrategyBookObservation: return "strategy_book_observation";
    case IpcMessageKind::OrderIntent: return "order_intent";
    case IpcMessageKind::EventAcknowledgement: return "event_acknowledgement";
    case IpcMessageKind::ExecutionEvent: return "execution_event";
  }
  fail("ipc_kind_invalid");
}
JsonValue text(std::string value) { return JsonValue(std::move(value)); }
JsonValue integer(std::uint64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
JsonValue signed_integer(std::int64_t value) {
  return JsonValue(JsonInteger{std::to_string(value)});
}
JsonValue nullable_integer(const std::optional<std::int64_t>& value) {
  return value ? signed_integer(*value) : JsonValue{};
}

std::vector<StrategyBookLevel> levels(const JsonObject& object, std::string_view key,
                                      bool bids) {
  const JsonArray* values = nullptr;
  try { values = &json_array(required(object, key), key); }
  catch (const JsonError&) { fail("ipc_book_levels_invalid"); }
  if (values->empty() || values->size() > 5U) fail("ipc_book_depth_invalid");
  std::vector<StrategyBookLevel> output;
  output.reserve(values->size());
  for (const auto& value : *values) {
    const JsonObject* item = nullptr;
    try { item = &json_object(value, "strategy_book_level"); }
    catch (const JsonError&) { fail("ipc_book_level_invalid"); }
    exact(*item, {"order_count", "price_paise", "quantity"});
    const auto price = number(*item, "price_paise");
    const auto quantity = number(*item, "quantity");
    const auto orders = number(*item, "order_count");
    if (price == 0U || quantity == 0U ||
        quantity > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) ||
        orders == 0U || orders > static_cast<std::uint64_t>(std::numeric_limits<std::int32_t>::max()))
      fail("ipc_book_level_invalid");
    if (!output.empty() && (bids ? price >= output.back().price_paise
                                 : price <= output.back().price_paise))
      fail("ipc_book_order_invalid");
    output.push_back({price, quantity, static_cast<std::uint32_t>(orders)});
  }
  return output;
}
}

IpcProtocolError::IpcProtocolError(std::string code)
    : std::runtime_error(code), code_(std::move(code)) {}

StrategyBookObservation StrategyBookObservation::parse(std::string_view bytes) {
  try {
    const auto document = parse_json(bytes, 32U * 1024U);
    const auto& object = json_object(document, "strategy_book_observation");
    exact(object, {"ask_count", "asks", "bid_count", "bids", "canonical_instrument_id",
                   "cumulative_volume", "exchange_timestamp_ns", "last_trade_quantity",
                   "open_interest", "provenance", "quality_flags", "receive_timestamp_ns",
                   "schema_version", "source"}, {"last_trade_paise"});
    if (string(object, "schema_version", 16U) != "1.0.0") fail("ipc_book_version_invalid");
    StrategyBookObservation result;
    result.canonical_instrument_id = string(object, "canonical_instrument_id", 192U);
    if (!is_canonical_instrument_id(result.canonical_instrument_id))
      fail("ipc_book_instrument_invalid");
    result.bids = levels(object, "bids", true);
    result.asks = levels(object, "asks", false);
    if (number(object, "bid_count") != result.bids.size() ||
        number(object, "ask_count") != result.asks.size())
      fail("ipc_book_depth_invalid");
    if (result.bids.front().price_paise >= result.asks.front().price_paise)
      fail("ipc_book_crossed");
    if (object.contains("last_trade_paise")) {
      result.last_trade_paise = number(object, "last_trade_paise");
      if (*result.last_trade_paise == 0U) fail("ipc_book_trade_invalid");
    }
    result.cumulative_volume = number(object, "cumulative_volume");
    result.last_trade_quantity = number(object, "last_trade_quantity");
    result.open_interest = number(object, "open_interest");
    if (result.last_trade_quantity > 0U && !result.last_trade_paise)
      fail("ipc_book_trade_invalid");
    result.exchange_timestamp_ns = nullable_signed_number(object, "exchange_timestamp_ns");
    result.receive_timestamp_ns = signed_number(object, "receive_timestamp_ns");
    if (result.receive_timestamp_ns <= 0 ||
        (result.exchange_timestamp_ns && *result.exchange_timestamp_ns <= 0))
      fail("ipc_book_timestamp_invalid");
    result.source = string(object, "source", 32U);
    result.provenance = string(object, "provenance", 24U);
    if (result.source != "dhan" || result.provenance != "observed")
      fail("ipc_book_source_invalid");
    const auto& flags = json_array(required(object, "quality_flags"), "quality_flags");
    static const std::set<std::string> allowed = {
        "stale", "crossed_book", "partial_book", "source_sequence_unavailable",
        "coalesced_update", "unusable"};
    if (flags.size() > 32U) fail("ipc_book_quality_invalid");
    for (const auto& value : flags) {
      std::string flag;
      try {
        flag = json_string(value, "quality_flag");
      } catch (const JsonError&) {
        fail("ipc_book_quality_invalid");
      }
      if (!allowed.contains(flag) ||
          std::find(result.quality_flags.begin(), result.quality_flags.end(), flag) !=
              result.quality_flags.end())
        fail("ipc_book_quality_invalid");
      result.quality_flags.push_back(std::move(flag));
    }
    return result;
  } catch (const IpcProtocolError&) { throw; }
  catch (const JsonError&) { fail("ipc_book_malformed"); }
}

std::string StrategyBookObservation::to_json() const {
  const auto encode_levels = [](const std::vector<StrategyBookLevel>& values) {
    JsonArray output;
    output.reserve(values.size());
    for (const auto& level : values) {
      output.emplace_back(JsonObject{{"order_count", integer(level.order_count)},
                                     {"price_paise", integer(level.price_paise)},
                                     {"quantity", integer(level.quantity)}});
    }
    return output;
  };
  JsonObject object{{"ask_count", integer(asks.size())},
                    {"asks", JsonValue(encode_levels(asks))},
                    {"bid_count", integer(bids.size())},
                    {"bids", JsonValue(encode_levels(bids))},
                    {"canonical_instrument_id", text(canonical_instrument_id)},
                    {"cumulative_volume", integer(cumulative_volume)},
                    {"exchange_timestamp_ns", nullable_integer(exchange_timestamp_ns)},
                    {"last_trade_quantity", integer(last_trade_quantity)},
                    {"open_interest", integer(open_interest)},
                    {"provenance", text(provenance)},
                    {"receive_timestamp_ns", signed_integer(receive_timestamp_ns)},
                    {"schema_version", text("1.0.0")},
                    {"source", text(source)}};
  if (last_trade_paise) object.emplace("last_trade_paise", integer(*last_trade_paise));
  JsonArray flags;
  for (const auto& flag : quality_flags) flags.emplace_back(text(flag));
  object.emplace("quality_flags", JsonValue(std::move(flags)));
  return canonical_json(JsonValue(std::move(object)));
}

MarketObservation StrategyBookObservation::derive_market_observation() const {
  const auto validated = StrategyBookObservation::parse(to_json());
  MarketObservation result;
  result.canonical_instrument_id = validated.canonical_instrument_id;
  result.best_bid_paise = validated.bids.front().price_paise;
  result.best_ask_paise = validated.asks.front().price_paise;
  result.last_trade_paise = validated.last_trade_paise;
  result.cumulative_volume = validated.cumulative_volume;
  result.exchange_timestamp_ns = validated.exchange_timestamp_ns;
  result.receive_timestamp_ns = validated.receive_timestamp_ns;
  result.source = validated.source;
  result.provenance = validated.provenance;
  result.quality_flags = validated.quality_flags;
  return MarketObservation::parse(result.to_json());
}

EventAcknowledgement EventAcknowledgement::parse(std::string_view bytes) {
  try {
    const auto document = parse_json(bytes, 4U * 1024U);
    if (canonical_json(document) != bytes) fail("ipc_noncanonical");
    const auto& object = json_object(document, "event_acknowledgement");
    exact(object, {"acknowledged_event_sequence", "schema_version"});
    if (string(object, "schema_version", 16U) != "1.0.0")
      fail("ipc_version_invalid");
    EventAcknowledgement result{number(object, "acknowledged_event_sequence")};
    if (result.acknowledged_event_sequence == 0U)
      fail("ipc_ack_sequence_invalid");
    return result;
  } catch (const IpcProtocolError&) { throw; }
  catch (const JsonError&) { fail("ipc_ack_malformed"); }
}

std::string EventAcknowledgement::to_json() const {
  return canonical_json(JsonValue(JsonObject{
      {"acknowledged_event_sequence", integer(acknowledged_event_sequence)},
      {"schema_version", text("1.0.0")}}));
}

IpcHandshake parse_ipc_handshake(std::string_view bytes) {
  try {
    const auto document = parse_json(bytes, 16U * 1024U);
    if (canonical_json(document) != bytes) fail("ipc_noncanonical");
    const auto& object = json_object(document, "ipc_handshake");
    exact(object, {"configuration_digest", "execution_session_id", "executable_digest", "nonce",
                   "process_start_identity", "protocol_version", "role", "schema_version"},
                  {"after_event_sequence", "strategy_id"});
    if (string(object, "schema_version") != "1.0.0") fail("ipc_version_invalid");
    IpcHandshake result;
    result.bindings.role = role(string(object, "role", 32U));
    result.bindings.protocol_version = string(object, "protocol_version", 16U);
    result.bindings.execution_session_id = string(object, "execution_session_id", 64U);
    result.bindings.configuration_digest = string(object, "configuration_digest", 64U);
    result.bindings.executable_digest = string(object, "executable_digest", 64U);
    result.bindings.process_start_identity = string(object, "process_start_identity", 128U);
    result.bindings.nonce = string(object, "nonce", 128U);
    if (object.contains("after_event_sequence"))
      result.after_event_sequence = number(object, "after_event_sequence");
    if (object.contains("strategy_id")) result.strategy_id = string(object, "strategy_id", 64U);
    if (result.bindings.role == PeerRole::MarketPublisher &&
        (result.after_event_sequence || result.strategy_id)) fail("ipc_role_fields_invalid");
    if (result.bindings.role == PeerRole::StrategyClient && !result.strategy_id)
      fail("ipc_role_fields_invalid");
    return result;
  } catch (const IpcProtocolError&) { throw; }
  catch (const JsonError&) { fail("ipc_handshake_malformed"); }
}

IpcEnvelope parse_ipc_envelope(std::string_view bytes) {
  try {
    const auto document = parse_json(bytes, 65'536U);
    if (canonical_json(document) != bytes) fail("ipc_noncanonical");
    const auto& object = json_object(document, "ipc_envelope");
    exact(object, {"execution_session_id", "kind", "payload", "schema_version"},
                  {"event_sequence", "source_digest", "source_sequence", "strategy_id"});
    if (string(object, "schema_version") != "1.0.0") fail("ipc_version_invalid");
    IpcEnvelope result;
    result.kind = kind(string(object, "kind", 32U));
    result.execution_session_id = string(object, "execution_session_id", 64U);
    if (object.contains("strategy_id")) result.strategy_id = string(object, "strategy_id", 64U);
    if (object.contains("source_sequence")) result.source_sequence = number(object, "source_sequence");
    if (object.contains("source_digest")) result.source_digest = string(object, "source_digest", 64U);
    if (object.contains("event_sequence")) result.event_sequence = number(object, "event_sequence");
    result.canonical_payload = canonical_json(required(object, "payload"));
    if (result.kind == IpcMessageKind::MarketObservation) {
      if (!result.source_sequence || *result.source_sequence == 0U || result.source_digest ||
          result.event_sequence || result.strategy_id)
        fail("ipc_kind_fields_invalid");
      (void)MarketObservation::parse(result.canonical_payload);
    } else if (result.kind == IpcMessageKind::StrategyBookObservation) {
      if (result.event_sequence || result.strategy_id ||
          result.source_sequence.has_value() != result.source_digest.has_value() ||
          (result.source_sequence && *result.source_sequence == 0U) ||
          (result.source_digest && (!digest(*result.source_digest) ||
                                    *result.source_digest != sha256_hex(result.canonical_payload))))
        fail("ipc_kind_fields_invalid");
      (void)StrategyBookObservation::parse(result.canonical_payload);
    } else if (result.kind == IpcMessageKind::OrderIntent) {
      if (result.source_sequence || result.source_digest || result.event_sequence || !result.strategy_id)
        fail("ipc_kind_fields_invalid");
      (void)OrderIntent::parse(result.canonical_payload);
    } else if (result.kind == IpcMessageKind::ExecutionEvent) {
      if (!result.event_sequence || result.source_sequence || result.source_digest || !result.strategy_id)
        fail("ipc_kind_fields_invalid");
      (void)ExecutionEvent::parse(result.canonical_payload);
    } else {
      if (!result.event_sequence || *result.event_sequence == 0U || result.source_sequence ||
          result.source_digest || !result.strategy_id)
        fail("ipc_kind_fields_invalid");
      const auto acknowledgement = EventAcknowledgement::parse(result.canonical_payload);
      if (acknowledgement.acknowledged_event_sequence != *result.event_sequence)
        fail("ipc_ack_sequence_mismatch");
    }
    return result;
  } catch (const IpcProtocolError&) { throw; }
  catch (const JsonError&) { fail("ipc_envelope_malformed"); }
}

std::string encode_ipc_envelope(const IpcEnvelope& envelope) {
  JsonObject object{{"execution_session_id", text(envelope.execution_session_id)},
                    {"kind", text(kind_name(envelope.kind))},
                    {"payload", parse_json(envelope.canonical_payload)},
                    {"schema_version", text("1.0.0")}};
  if (envelope.strategy_id) object.emplace("strategy_id", text(*envelope.strategy_id));
  if (envelope.source_sequence) object.emplace("source_sequence", integer(*envelope.source_sequence));
  if (envelope.source_digest) object.emplace("source_digest", text(*envelope.source_digest));
  if (envelope.event_sequence) object.emplace("event_sequence", integer(*envelope.event_sequence));
  return canonical_json(JsonValue(std::move(object)));
}

void authorize_inbound(PeerRole peer_role, const IpcEnvelope& envelope,
                       std::string_view expected_session, std::string_view expected_strategy) {
  if (envelope.execution_session_id != expected_session) fail("ipc_session_invalid");
  if (peer_role == PeerRole::MarketPublisher) {
    if (envelope.kind != IpcMessageKind::StrategyBookObservation || envelope.source_sequence ||
        envelope.source_digest) fail("ipc_role_unauthorized");
  } else {
    if (envelope.kind != IpcMessageKind::OrderIntent &&
        envelope.kind != IpcMessageKind::EventAcknowledgement) fail("ipc_role_unauthorized");
    if (!envelope.strategy_id || *envelope.strategy_id != expected_strategy)
      fail("ipc_strategy_scope_invalid");
  }
}

void EventReplayLog::append(ReplayEvent event) {
  if (event.sequence == 0U || (!events_.empty() && event.sequence != events_.back().sequence + 1U))
    fail("ipc_event_sequence_invalid");
  (void)ExecutionEvent::parse(event.canonical_event);
  events_.push_back(std::move(event));
}
std::vector<ReplayEvent> EventReplayLog::replay_after(
    std::uint64_t after_sequence, std::string_view execution_session_id,
    std::string_view strategy_id) const {
  if (after_sequence > last_sequence()) fail("ipc_replay_cursor_ahead");
  std::vector<ReplayEvent> output;
  for (const auto& event : events_) {
    if (event.sequence <= after_sequence) continue;
    if (event.execution_session_id != execution_session_id || event.strategy_id != strategy_id)
      fail("ipc_replay_scope_invalid");
    output.push_back(event);
  }
  return output;
}
std::uint64_t EventReplayLog::last_sequence() const noexcept {
  return events_.empty() ? 0U : events_.back().sequence;
}

}  // namespace shaurya::execution
