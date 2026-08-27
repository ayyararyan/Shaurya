#include "shaurya/execution/contracts.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <set>
#include <utility>

namespace shaurya::execution {
namespace {

[[noreturn]] void invalid(std::string code) { throw JsonError(std::move(code)); }
JsonValue text(std::string value) { return JsonValue(std::move(value)); }
JsonValue integer(std::int64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
JsonValue integer(std::uint64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }

const JsonValue& required(const JsonObject& object, std::string_view key) {
  const auto iterator = object.find(key);
  if (iterator == object.end()) invalid("missing_field:" + std::string(key));
  return iterator->second;
}
const JsonValue* optional(const JsonObject& object, std::string_view key) {
  const auto iterator = object.find(key);
  return iterator == object.end() ? nullptr : &iterator->second;
}
void exact_fields(const JsonObject& object, std::initializer_list<std::string_view> required_keys,
                  std::initializer_list<std::string_view> optional_keys = {}) {
  std::set<std::string_view> allowed(required_keys);
  allowed.insert(optional_keys.begin(), optional_keys.end());
  for (const auto key : required_keys)
    if (!object.contains(key)) invalid("missing_field:" + std::string(key));
  for (const auto& [key, unused] : object) {
    (void)unused;
    if (!allowed.contains(key)) invalid("unknown_field");
  }
}
std::string bounded_string(const JsonValue& value, std::string_view field,
                           std::size_t maximum = 128) {
  const std::string& item = json_string(value, field);
  if (item.empty() || item.size() > maximum) invalid("invalid_string");
  for (const char raw_character : item) {
    const auto character = static_cast<unsigned char>(raw_character);
    if (character < 0x20U || character > 0x7EU) invalid("invalid_string");
  }
  return item;
}
bool conservative_identifier(std::string_view value) {
  return !value.empty() && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= 'A' && item <= 'Z') || (item >= 'a' && item <= 'z') ||
           (item >= '0' && item <= '9') || item == '.' || item == '_' || item == '-';
  });
}
std::optional<std::string> optional_string(const JsonObject& object, std::string_view key,
                                           std::size_t maximum = 128) {
  const auto* item = optional(object, key);
  return item == nullptr ? std::nullopt : std::optional<std::string>(bounded_string(*item, key, maximum));
}
std::optional<std::int64_t> nullable_int64(const JsonObject& object, std::string_view key) {
  const auto* item = optional(object, key);
  if (item == nullptr || std::holds_alternative<std::nullptr_t>(item->value)) return std::nullopt;
  return json_int64(*item, key);
}
std::optional<std::uint64_t> optional_uint64(const JsonObject& object, std::string_view key) {
  const auto* item = optional(object, key);
  return item == nullptr ? std::nullopt : std::optional<std::uint64_t>(json_uint64(*item, key));
}
std::optional<std::uint64_t> nullable_uint64_required(const JsonObject& object,
                                                      std::string_view key) {
  const auto& item = required(object, key);
  if (std::holds_alternative<std::nullptr_t>(item.value)) return std::nullopt;
  return json_uint64(item, key);
}
bool lowercase_hex(std::string_view value, std::size_t length) {
  return value.size() == length && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= '0' && item <= '9') || (item >= 'a' && item <= 'f');
  });
}
void require_uuid(const std::string& value) {
  if (!is_canonical_uuid(value)) invalid("invalid_uuid");
}
void require_version(const JsonObject& object) {
  if (json_string(required(object, "schema_version"), "schema_version") != kContractVersion)
    invalid("unsupported_version");
}
void require_digest(const std::string& value) {
  if (!lowercase_hex(value, 64)) invalid("invalid_digest");
}
void validate_broker_source(const JsonObject& payload) {
  (void)json_uint64(required(payload, "source_sequence"), "source_sequence");
  require_digest(bounded_string(required(payload, "source_fingerprint"),
                                "source_fingerprint", 64));
  static const std::set<std::string> provenances = {
      "simulated", "proxy", "simulated_proxy", "broker_confirmed"};
  if (!provenances.contains(bounded_string(required(payload, "source_provenance"),
                                           "source_provenance", 32)))
    invalid("invalid_source_provenance");
}
JsonObject base_document() { return {{"schema_version", text(std::string(kContractVersion))}}; }
void add_optional(JsonObject& object, std::string key, const std::optional<std::string>& value) {
  if (value) object.emplace(std::move(key), text(*value));
}
void add_optional(JsonObject& object, std::string key, const std::optional<std::uint64_t>& value) {
  if (value) object.emplace(std::move(key), integer(*value));
}
void add_nullable(JsonObject& object, std::string key, const std::optional<std::int64_t>& value) {
  object.emplace(std::move(key), value ? integer(*value) : JsonValue());
}
std::vector<std::string_view> split(std::string_view value, char delimiter) {
  std::vector<std::string_view> output;
  std::size_t begin = 0;
  while (true) {
    const auto end = value.find(delimiter, begin);
    output.push_back(value.substr(begin, end == std::string_view::npos ? end : end - begin));
    if (end == std::string_view::npos) return output;
    begin = end + 1;
  }
}
bool valid_date(std::string_view value) {
  if (value.size() != 10 || value[4] != '-' || value[7] != '-') return false;
  const auto digits = [](std::string_view part) {
    return std::all_of(part.begin(), part.end(), [](char item) { return item >= '0' && item <= '9'; });
  };
  if (!digits(value.substr(0,4)) || !digits(value.substr(5,2)) || !digits(value.substr(8,2))) return false;
  const int year = std::stoi(std::string(value.substr(0,4)));
  const unsigned month = static_cast<unsigned>(std::stoi(std::string(value.substr(5,2))));
  const unsigned day = static_cast<unsigned>(std::stoi(std::string(value.substr(8,2))));
  return std::chrono::year_month_day{std::chrono::year{year}, std::chrono::month{month},
                                     std::chrono::day{day}}.ok();
}
void ensure_no_secrets(const JsonValue& value) {
  static const std::array<std::string_view, 14> forbidden = {
      "credential", "password", "accesstoken", "refreshtoken", "sessiontoken",
      "totp", "cookie", "authorization", "privatekey", "authenticationurl",
      "rawhttpbody", "responsebody", "brokerurl", "header"};
  if (const auto* object = std::get_if<JsonObject>(&value.value)) {
    for (const auto& [key, item] : *object) {
      std::string normalized;
      normalized.reserve(key.size());
      for (const auto raw_character : key) {
        const auto character = static_cast<unsigned char>(raw_character);
        if (std::isalnum(character) != 0) {
          normalized.push_back(static_cast<char>(std::tolower(character)));
        }
      }
      if (std::any_of(forbidden.begin(), forbidden.end(), [&](std::string_view candidate) {
            return normalized.find(candidate) != std::string::npos;
          })) invalid("secret_field");
      ensure_no_secrets(item);
    }
  } else if (const auto* array = std::get_if<JsonArray>(&value.value)) {
    for (const auto& item : *array) ensure_no_secrets(item);
  }
}
void payload_fields(const JsonObject& payload,
                    std::initializer_list<std::string_view> allowed_fields,
                    std::initializer_list<std::string_view> required_fields = {}) {
  if (payload.size() > 128U) invalid("payload_too_large");
  const std::set<std::string_view> allowed(allowed_fields);
  for (const auto required_field : required_fields) {
    if (!payload.contains(required_field)) invalid("missing_payload_field");
  }
  for (const auto& [field, unused] : payload) {
    (void)unused;
    if (!allowed.contains(field)) invalid("invalid_payload_field");
  }
}
void require_strategy_correlation(const ExecutionEvent& event, bool require_order) {
  if (!event.strategy_id || !event.strategy_run_id || !event.intent_id ||
      (require_order && !event.internal_order_id) || (!require_order && event.internal_order_id)) {
    invalid("invalid_event_correlation");
  }
}
void forbid_correlation(const ExecutionEvent& event) {
  if (event.strategy_id || event.strategy_run_id || event.intent_id || event.internal_order_id) {
    invalid("invalid_event_correlation");
  }
}
void validate_event_variant(const ExecutionEvent& event) {
  const auto& type = event.event_type;
  if (type == "session_started" || type == "session_stopping" || type == "session_stopped") {
    forbid_correlation(event);
    payload_fields(event.payload,
                   {"mode", "build_digest", "routing_snapshot_digest", "state", "reason",
                    "launch_attestation_digest", "invocation_id", "operator_id", "device_id",
                    "public_key_fingerprint", "cli_release_digest",
                    "deployment_manifest_digest", "executor_build_digest", "requested_mode",
                    "confirmation_type", "launch_timestamp_ns"});
    const std::array<std::string_view, 11U> launch_fields = {
        "launch_attestation_digest", "invocation_id", "operator_id", "device_id",
        "public_key_fingerprint", "cli_release_digest", "deployment_manifest_digest",
        "executor_build_digest", "requested_mode", "confirmation_type", "launch_timestamp_ns"};
    const bool any_launch = std::any_of(launch_fields.begin(), launch_fields.end(),
                                       [&](std::string_view field) {
                                         return event.payload.contains(field);
                                       });
    if (any_launch) {
      if (type != "session_started" ||
          std::any_of(launch_fields.begin(), launch_fields.end(),
                      [&](std::string_view field) { return !event.payload.contains(field); }))
        invalid("invalid_launch_evidence");
      for (const auto field : {"launch_attestation_digest", "cli_release_digest",
                               "deployment_manifest_digest", "executor_build_digest"})
        require_digest(bounded_string(required(event.payload, field), field, 64));
      require_uuid(bounded_string(required(event.payload, "invocation_id"), "invocation_id"));
      (void)bounded_string(required(event.payload, "operator_id"), "operator_id", 128);
      (void)bounded_string(required(event.payload, "device_id"), "device_id", 128);
      (void)bounded_string(required(event.payload, "public_key_fingerprint"),
                           "public_key_fingerprint", 128);
      if (bounded_string(required(event.payload, "requested_mode"), "requested_mode", 16) !=
              "shadow" ||
          bounded_string(required(event.payload, "confirmation_type"), "confirmation_type", 64) !=
              "SHAURYA_SHADOW_LAUNCH" ||
          json_int64(required(event.payload, "launch_timestamp_ns"), "launch_timestamp_ns") <= 0)
        invalid("invalid_launch_evidence");
    }
  } else if (type == "ledger_repair_recorded") {
    forbid_correlation(event);
    payload_fields(event.payload,
                   {"confirmation_type", "damaged_segment_bytes", "damaged_segment_sha256",
                    "repair_tool_version", "source_label", "verified_prefix_bytes"},
                   {"confirmation_type", "damaged_segment_bytes", "damaged_segment_sha256",
                    "repair_tool_version", "source_label", "verified_prefix_bytes"});
    if (bounded_string(required(event.payload, "confirmation_type"), "confirmation_type", 40) !=
        "REPAIR_TRUNCATED_LEDGER") invalid("invalid_repair_payload");
    (void)json_uint64(required(event.payload, "damaged_segment_bytes"),
                      "damaged_segment_bytes");
    const auto repair_digest = bounded_string(
        required(event.payload, "damaged_segment_sha256"), "damaged_segment_sha256", 64);
    require_digest(repair_digest);
    (void)bounded_string(required(event.payload, "repair_tool_version"),
                         "repair_tool_version", 16);
    (void)bounded_string(required(event.payload, "source_label"), "source_label", 128);
    (void)json_uint64(required(event.payload, "verified_prefix_bytes"),
                      "verified_prefix_bytes");
  } else if (type == "safety_stop") {
    const bool any_strategy = event.strategy_id || event.strategy_run_id || event.intent_id ||
                              event.internal_order_id;
    if (any_strategy && (!event.strategy_id || !event.strategy_run_id || !event.intent_id)) {
      invalid("invalid_event_correlation");
    }
    payload_fields(event.payload, {"reason", "error_code", "queue", "stage"});
  } else if (type == "market_observation_accepted") {
    forbid_correlation(event);
    payload_fields(event.payload,
                   {"best_ask_paise", "best_bid_paise", "canonical_instrument_id",
                    "cumulative_volume", "last_trade_paise", "provenance",
                    "receive_timestamp_ns", "source", "source_digest", "source_sequence"},
                   {"best_ask_paise", "best_bid_paise", "canonical_instrument_id",
                    "cumulative_volume", "last_trade_paise", "provenance",
                    "receive_timestamp_ns", "source", "source_digest", "source_sequence"});
    if (!is_canonical_instrument_id(bounded_string(
            required(event.payload, "canonical_instrument_id"), "canonical_instrument_id", 192)) ||
        bounded_string(required(event.payload, "source"), "source", 32) != "dhan" ||
        bounded_string(required(event.payload, "provenance"), "provenance", 24) != "observed" ||
        json_int64(required(event.payload, "receive_timestamp_ns"),
                   "receive_timestamp_ns") <= 0 ||
        json_uint64(required(event.payload, "source_sequence"), "source_sequence") == 0U)
      invalid("invalid_market_observation_evidence");
    for (const auto field : {"best_ask_paise", "best_bid_paise", "last_trade_paise"}) {
      const auto price = nullable_uint64_required(event.payload, field);
      if (price && *price == 0U) invalid("invalid_market_observation_evidence");
    }
    (void)json_uint64(required(event.payload, "cumulative_volume"), "cumulative_volume");
    require_digest(bounded_string(required(event.payload, "source_digest"),
                                  "source_digest", 64));
  } else if (type == "intent_received") {
    require_strategy_correlation(event, false);
    payload_fields(event.payload, {"semantic_fingerprint", "canonical_instrument_id"},
                   {"semantic_fingerprint"});
    const auto fingerprint = bounded_string(required(event.payload, "semantic_fingerprint"),
                                            "semantic_fingerprint", 64);
    require_digest(fingerprint);
    if (const auto* instrument = optional(event.payload, "canonical_instrument_id")) {
      if (!is_canonical_instrument_id(json_string(*instrument, "canonical_instrument_id")))
        invalid("invalid_instrument");
    }
  } else if (type == "mapping_refused") {
    require_strategy_correlation(event, false);
    payload_fields(event.payload, {"error_code", "routing_snapshot_digest"}, {"error_code"});
    (void)bounded_string(required(event.payload, "error_code"), "error_code", 64);
    if (const auto* digest = optional(event.payload, "routing_snapshot_digest"))
      require_digest(bounded_string(*digest, "routing_snapshot_digest", 64));
  } else if (type == "risk_rejected") {
    require_strategy_correlation(event, false);
    payload_fields(event.payload,
                   {"broker_call_count", "decision_id", "configuration_digest",
                    "rejection_code", "risk_decision"},
                   {"broker_call_count", "decision_id", "configuration_digest",
                    "rejection_code", "risk_decision"});
    if (json_uint64(required(event.payload, "broker_call_count"), "broker_call_count") != 0U)
      invalid("invalid_risk_boundary");
    require_uuid(bounded_string(required(event.payload, "decision_id"), "decision_id"));
    require_digest(bounded_string(required(event.payload, "configuration_digest"),
                                  "configuration_digest", 64));
    (void)bounded_string(required(event.payload, "rejection_code"), "rejection_code", 64);
    const auto embedded = RiskDecision::parse(canonical_json(required(event.payload,
                                                                  "risk_decision")));
    if (embedded.decision_id != bounded_string(required(event.payload, "decision_id"),
                                               "decision_id", 64) ||
        embedded.configuration_digest != bounded_string(
            required(event.payload, "configuration_digest"), "configuration_digest", 64) ||
        !embedded.rejection_code ||
        *embedded.rejection_code != bounded_string(required(event.payload, "rejection_code"),
                                                    "rejection_code", 64))
      invalid("invalid_risk_boundary");
  } else if (type == "mapping_validated") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"canonical_instrument_id", "routing_snapshot_digest", "instrument_token", "exchange_segment",
                    "trading_symbol", "lot_size", "tick_size_paise"},
                   {"routing_snapshot_digest", "instrument_token", "exchange_segment",
                    "trading_symbol", "lot_size", "tick_size_paise"});
    require_digest(bounded_string(required(event.payload, "routing_snapshot_digest"),
                                  "routing_snapshot_digest", 64));
    if (const auto* canonical = optional(event.payload, "canonical_instrument_id"); canonical &&
        !is_canonical_instrument_id(bounded_string(*canonical, "canonical_instrument_id", 192)))
      invalid("invalid_instrument");
    (void)bounded_string(required(event.payload, "instrument_token"), "instrument_token", 64);
    if (bounded_string(required(event.payload, "exchange_segment"), "exchange_segment", 16) !=
        "nse_fo") invalid("invalid_route_payload");
    (void)bounded_string(required(event.payload, "trading_symbol"), "trading_symbol", 128);
    if (json_uint64(required(event.payload, "lot_size"), "lot_size") == 0 ||
        json_uint64(required(event.payload, "tick_size_paise"), "tick_size_paise") == 0)
      invalid("invalid_route_payload");
  } else if (type == "risk_approved") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"broker_call_count", "decision_id", "configuration_digest",
                    "risk_decision"},
                   {"broker_call_count", "decision_id", "configuration_digest",
                    "risk_decision"});
    if (json_uint64(required(event.payload, "broker_call_count"), "broker_call_count") != 0U)
      invalid("invalid_risk_boundary");
    require_uuid(bounded_string(required(event.payload, "decision_id"), "decision_id"));
    require_digest(bounded_string(required(event.payload, "configuration_digest"),
                                  "configuration_digest", 64));
    const auto embedded = RiskDecision::parse(canonical_json(required(event.payload,
                                                                  "risk_decision")));
    if (embedded.decision != "approved" || embedded.rejection_code ||
        embedded.decision_id != bounded_string(required(event.payload, "decision_id"),
                                               "decision_id", 64) ||
        embedded.configuration_digest != bounded_string(
            required(event.payload, "configuration_digest"), "configuration_digest", 64))
      invalid("invalid_risk_boundary");
  } else if (type == "submission_started") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"baseline_cumulative_volume", "canonical_instrument_id", "route_digest",
                    "side", "quantity", "limit_price_paise", "broker", "attempt_sequence"},
                   {"canonical_instrument_id", "route_digest", "side", "quantity",
                    "limit_price_paise"});
    if (!is_canonical_instrument_id(bounded_string(
            required(event.payload, "canonical_instrument_id"), "canonical_instrument_id", 192)))
      invalid("invalid_instrument");
    require_digest(bounded_string(required(event.payload, "route_digest"), "route_digest", 64));
    const auto side = bounded_string(required(event.payload, "side"), "side", 4);
    if (side != "BUY" && side != "SELL") invalid("invalid_side");
    if (json_uint64(required(event.payload, "quantity"), "quantity") == 0 ||
        json_uint64(required(event.payload, "limit_price_paise"), "limit_price_paise") == 0)
      invalid("invalid_order_fields");
    if (const auto* baseline = optional(event.payload, "baseline_cumulative_volume"))
      (void)json_uint64(*baseline, "baseline_cumulative_volume");
  } else if (type == "broker_acknowledged") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"update_id", "broker_order_id", "provenance", "instrument_token",
                    "quantity", "limit_price_paise", "source_sequence",
                    "source_fingerprint", "source_provenance"},
                   {"update_id", "broker_order_id", "source_sequence",
                    "source_fingerprint", "source_provenance"});
    (void)bounded_string(required(event.payload, "update_id"), "update_id", 128);
    (void)bounded_string(required(event.payload, "broker_order_id"), "broker_order_id", 128);
    validate_broker_source(event.payload);
  } else if (type == "partially_filled" || type == "filled") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"update_id", "broker_order_id", "cumulative_filled_quantity",
                    "fill_price_paise", "provenance", "instrument_token",
                    "evidence_timestamp_ns", "source_sequence", "source_fingerprint",
                    "source_provenance"},
                   {"update_id", "cumulative_filled_quantity", "source_sequence",
                    "source_fingerprint", "source_provenance"});
    (void)bounded_string(required(event.payload, "update_id"), "update_id", 128);
    (void)json_uint64(required(event.payload, "cumulative_filled_quantity"),
                      "cumulative_filled_quantity");
    if (const auto* timestamp = optional(event.payload, "evidence_timestamp_ns"))
      (void)json_int64(*timestamp, "evidence_timestamp_ns");
    validate_broker_source(event.payload);
  } else if (type == "cancel_requested" || type == "cancelled") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"update_id", "broker_order_id", "provenance", "source_sequence",
                    "source_fingerprint", "source_provenance"},
                   type == "cancelled"
                       ? std::initializer_list<std::string_view>{"update_id", "source_sequence",
                                                                 "source_fingerprint",
                                                                 "source_provenance"}
                       : std::initializer_list<std::string_view>{"update_id"});
    (void)bounded_string(required(event.payload, "update_id"), "update_id", 128);
    if (type == "cancelled") validate_broker_source(event.payload);
  } else if (type == "modify_requested" || type == "modified") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"update_id", "quantity", "limit_price_paise", "provenance",
                    "source_sequence", "source_fingerprint", "source_provenance"},
                   type == "modified"
                       ? std::initializer_list<std::string_view>{"update_id", "quantity",
                                                                 "limit_price_paise",
                                                                 "source_sequence",
                                                                 "source_fingerprint",
                                                                 "source_provenance"}
                       : std::initializer_list<std::string_view>{"update_id", "quantity",
                                                                 "limit_price_paise"});
    (void)bounded_string(required(event.payload, "update_id"), "update_id", 128);
    if (json_uint64(required(event.payload, "quantity"), "quantity") == 0U ||
        json_uint64(required(event.payload, "limit_price_paise"), "limit_price_paise") == 0U)
      invalid("invalid_modify_payload");
    if (type == "modified") validate_broker_source(event.payload);
  } else if (type == "modify_rejected" || type == "cancel_rejected") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"update_id", "error_code", "provenance", "source_sequence",
                    "source_fingerprint", "source_provenance"},
                   {"update_id", "error_code", "source_sequence", "source_fingerprint",
                    "source_provenance"});
    (void)bounded_string(required(event.payload, "update_id"), "update_id", 128);
    (void)bounded_string(required(event.payload, "error_code"), "error_code", 64);
    validate_broker_source(event.payload);
  } else if (type == "broker_rejected" || type == "ambiguous_submission") {
    require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"update_id", "error_code", "provenance", "source_sequence",
                    "source_fingerprint", "source_provenance"},
                   {"update_id", "error_code", "source_sequence", "source_fingerprint",
                    "source_provenance"});
    (void)bounded_string(required(event.payload, "update_id"), "update_id", 128);
    (void)bounded_string(required(event.payload, "error_code"), "error_code", 64);
    validate_broker_source(event.payload);
  } else if (type == "reconciliation_required" || type == "reconciliation_completed") {
    const bool any_correlation = event.strategy_id || event.strategy_run_id || event.intent_id ||
                                 event.internal_order_id;
    if (any_correlation) require_strategy_correlation(event, true);
    payload_fields(event.payload,
                   {"reason", "error_code", "update_id", "broker_order_id",
                    "cumulative_filled_quantity", "authoritative_state"});
  }
}
std::string action_name(IntentAction action) {
  switch (action) { case IntentAction::Place: return "place"; case IntentAction::Modify: return "modify"; case IntentAction::Cancel: return "cancel"; }
  invalid("invalid_action");
}
std::string side_name(OrderSide side) { return side == OrderSide::Buy ? "BUY" : "SELL"; }
}

bool is_canonical_uuid(std::string_view value) {
  if (value.size() != 36) return false;
  for (std::size_t index = 0; index < value.size(); ++index) {
    if (index == 8 || index == 13 || index == 18 || index == 23) {
      if (value[index] != '-') return false;
    } else if (!((value[index] >= '0' && value[index] <= '9') ||
                 (value[index] >= 'a' && value[index] <= 'f'))) return false;
  }
  return true;
}

bool is_canonical_instrument_id(std::string_view value) {
  const auto parts = split(value, ':');
  if (parts.size() != 5 && parts.size() != 7) return false;
  if (parts[0] != "NSE" || parts[1] != "NSE_FNO") return false;
  if (parts[2].empty() || !std::all_of(parts[2].begin(), parts[2].end(), [](char item) {
        return (item >= 'A' && item <= 'Z') || (item >= '0' && item <= '9') || item == '.' || item == '_' || item == '-';
      })) return false;
  if (parts[3] == "future") return parts.size() == 5 && valid_date(parts[4]);
  if (parts[3] != "option" || parts.size() != 7 || !valid_date(parts[4]) ||
      (parts[6] != "CE" && parts[6] != "PE")) return false;
  const auto strike = parts[5];
  if (strike.empty() || strike.front() == '0') return false;
  const auto decimal = strike.find('.');
  if (decimal == std::string_view::npos) {
    return std::all_of(strike.begin(), strike.end(), [](char item) {
      return item >= '0' && item <= '9';
    });
  }
  if (decimal == 0 || decimal + 1 == strike.size() ||
      strike.find('.', decimal + 1) != std::string_view::npos || strike.back() == '0') return false;
  return std::all_of(strike.begin(), strike.end(), [](char item) {
    return item == '.' || (item >= '0' && item <= '9');
  });
}

OrderIntent OrderIntent::parse(std::string_view json) {
  const auto document = parse_json(json);
  const auto& object = json_object(document, "order_intent");
  exact_fields(object,
      {"schema_version","intent_id","strategy_id","strategy_run_id","execution_session_id",
       "created_at_ns","expires_at_ns","canonical_instrument_id","action"},
      {"side","quantity","limit_price_paise","product","time_in_force","target_internal_order_id","strategy_tag"});
  require_version(object);
  OrderIntent output;
  output.intent_id = bounded_string(required(object,"intent_id"),"intent_id"); require_uuid(output.intent_id);
  output.strategy_id = bounded_string(required(object,"strategy_id"),"strategy_id",64);
  if (!conservative_identifier(output.strategy_id)) invalid("invalid_strategy_id");
  output.strategy_run_id = bounded_string(required(object,"strategy_run_id"),"strategy_run_id"); require_uuid(output.strategy_run_id);
  output.execution_session_id = bounded_string(required(object,"execution_session_id"),"execution_session_id"); require_uuid(output.execution_session_id);
  output.created_at_ns = json_int64(required(object,"created_at_ns"),"created_at_ns");
  output.expires_at_ns = json_int64(required(object,"expires_at_ns"),"expires_at_ns");
  if (output.expires_at_ns <= output.created_at_ns) invalid("invalid_expiry");
  output.canonical_instrument_id = bounded_string(required(object,"canonical_instrument_id"),"canonical_instrument_id",192);
  if (!is_canonical_instrument_id(output.canonical_instrument_id)) invalid("invalid_instrument");
  const auto action = bounded_string(required(object,"action"),"action",16);
  if (action == "place") output.action = IntentAction::Place;
  else if (action == "modify") output.action = IntentAction::Modify;
  else if (action == "cancel") output.action = IntentAction::Cancel;
  else invalid("invalid_action");
  if (const auto side = optional_string(object,"side",4)) {
    if (*side == "BUY") output.side = OrderSide::Buy;
    else if (*side == "SELL") output.side = OrderSide::Sell;
    else invalid("invalid_side");
  }
  output.quantity = optional_uint64(object,"quantity");
  output.limit_price_paise = optional_uint64(object,"limit_price_paise");
  output.product = optional_string(object,"product",8);
  output.time_in_force = optional_string(object,"time_in_force",8);
  output.target_internal_order_id = optional_string(object,"target_internal_order_id");
  output.strategy_tag = optional_string(object,"strategy_tag",64);
  if (output.strategy_tag && !conservative_identifier(*output.strategy_tag))
    invalid("invalid_strategy_tag");
  if (output.target_internal_order_id) require_uuid(*output.target_internal_order_id);
  if (output.action == IntentAction::Cancel) {
    if (output.side || output.quantity || output.limit_price_paise || output.product || output.time_in_force || !output.target_internal_order_id)
      invalid("invalid_cancel_fields");
  } else {
    if (!output.side || !output.quantity || *output.quantity == 0 || !output.limit_price_paise ||
        *output.limit_price_paise == 0 || output.product != "NRML" || output.time_in_force != "DAY")
      invalid("invalid_order_fields");
    if ((output.action == IntentAction::Place) == output.target_internal_order_id.has_value())
      invalid("invalid_target");
  }
  return output;
}

std::string OrderIntent::to_json() const {
  JsonObject object = base_document();
  object.emplace("action", text(action_name(action)));
  object.emplace("canonical_instrument_id", text(canonical_instrument_id));
  object.emplace("created_at_ns", integer(created_at_ns));
  object.emplace("execution_session_id", text(execution_session_id));
  object.emplace("expires_at_ns", integer(expires_at_ns));
  object.emplace("intent_id", text(intent_id));
  add_optional(object,"limit_price_paise",limit_price_paise);
  add_optional(object,"product",product);
  add_optional(object,"quantity",quantity);
  if (side) object.emplace("side",text(side_name(*side)));
  object.emplace("strategy_id",text(strategy_id));
  object.emplace("strategy_run_id",text(strategy_run_id));
  add_optional(object,"strategy_tag",strategy_tag);
  add_optional(object,"target_internal_order_id",target_internal_order_id);
  add_optional(object,"time_in_force",time_in_force);
  return canonical_json(JsonValue(std::move(object)));
}
std::string OrderIntent::semantic_fingerprint() const {
  auto object = json_object(parse_json(to_json()),"intent");
  object.erase("intent_id");
  return sha256_hex(canonical_json(JsonValue(std::move(object))));
}

ExecutionEvent ExecutionEvent::parse(std::string_view json) {
  const auto document=parse_json(json); const auto& object=json_object(document,"event");
  exact_fields(object,{"schema_version","event_id","event_type","timestamp_ns","execution_session_id","payload"},
               {"strategy_id","strategy_run_id","intent_id","internal_order_id"});
  require_version(object); ExecutionEvent output;
  output.event_id=bounded_string(required(object,"event_id"),"event_id"); require_uuid(output.event_id);
  output.event_type=bounded_string(required(object,"event_type"),"event_type",40);
  static const std::set<std::string> types={"market_observation_accepted","intent_received","mapping_validated","mapping_refused","risk_approved","risk_rejected","submission_started","broker_acknowledged","partially_filled","filled","modify_requested","modified","modify_rejected","cancel_requested","cancelled","cancel_rejected","broker_rejected","ambiguous_submission","reconciliation_required","reconciliation_completed","safety_stop","session_started","session_stopping","session_stopped","ledger_repair_recorded"};
  if (!types.contains(output.event_type)) invalid("invalid_event_type");
  output.timestamp_ns=json_int64(required(object,"timestamp_ns"),"timestamp_ns");
  output.execution_session_id=bounded_string(required(object,"execution_session_id"),"execution_session_id"); require_uuid(output.execution_session_id);
  output.strategy_id=optional_string(object,"strategy_id",64);
  if(output.strategy_id&&!conservative_identifier(*output.strategy_id)) invalid("invalid_strategy_id");
  output.strategy_run_id=optional_string(object,"strategy_run_id"); if(output.strategy_run_id) require_uuid(*output.strategy_run_id);
  output.intent_id=optional_string(object,"intent_id"); if(output.intent_id) require_uuid(*output.intent_id);
  output.internal_order_id=optional_string(object,"internal_order_id"); if(output.internal_order_id) require_uuid(*output.internal_order_id);
  output.payload=json_object(required(object,"payload"),"payload"); ensure_no_secrets(JsonValue(output.payload));
  validate_event_variant(output);
  return output;
}
std::string ExecutionEvent::to_json() const {
  JsonObject object=base_document(); object.emplace("event_id",text(event_id)); object.emplace("event_type",text(event_type));
  object.emplace("execution_session_id",text(execution_session_id)); add_optional(object,"intent_id",intent_id);
  add_optional(object,"internal_order_id",internal_order_id); object.emplace("payload",JsonValue(payload));
  add_optional(object,"strategy_id",strategy_id); add_optional(object,"strategy_run_id",strategy_run_id);
  object.emplace("timestamp_ns",integer(timestamp_ns)); return canonical_json(JsonValue(std::move(object)));
}

RiskDecision RiskDecision::parse(std::string_view json) {
  const auto document=parse_json(json); const auto& object=json_object(document,"risk");
  exact_fields(object,{"schema_version","decision_id","intent_id","decision","timestamp_ns","rule_set_version","configuration_digest","rules_checked","mapping_age_ns","market_age_ns","session_state"},{"rejection_code","rejection_reason"});
  require_version(object); RiskDecision output;
  output.decision_id=bounded_string(required(object,"decision_id"),"decision_id"); require_uuid(output.decision_id);
  output.intent_id=bounded_string(required(object,"intent_id"),"intent_id"); require_uuid(output.intent_id);
  output.decision=bounded_string(required(object,"decision"),"decision",16); if(output.decision!="approved"&&output.decision!="rejected") invalid("invalid_decision");
  output.timestamp_ns=json_int64(required(object,"timestamp_ns"),"timestamp_ns"); output.rule_set_version=bounded_string(required(object,"rule_set_version"),"rule_set_version",64);
  output.configuration_digest=bounded_string(required(object,"configuration_digest"),"configuration_digest",64); require_digest(output.configuration_digest);
  for(const auto& value:json_array(required(object,"rules_checked"),"rules_checked")) {
    const auto& rule=json_object(value,"rule"); exact_fields(rule,{"rule","outcome","before_value","projected_value","limit_value","unit"});
    RuleCheck check{bounded_string(required(rule,"rule"),"rule",64),bounded_string(required(rule,"outcome"),"outcome",16),json_int64(required(rule,"before_value"),"before_value"),json_int64(required(rule,"projected_value"),"projected_value"),json_int64(required(rule,"limit_value"),"limit_value"),bounded_string(required(rule,"unit"),"unit",24)};
    if(check.outcome!="pass"&&check.outcome!="fail") invalid("invalid_rule_outcome"); output.rules_checked.push_back(std::move(check));
  }
  if(output.rules_checked.empty()||output.rules_checked.size()>128) invalid("invalid_rules");
  output.rejection_code=optional_string(object,"rejection_code",64); output.rejection_reason=optional_string(object,"rejection_reason",160);
  if((output.decision=="rejected")!=static_cast<bool>(output.rejection_code&&output.rejection_reason)) invalid("invalid_rejection_fields");
  output.mapping_age_ns=json_int64(required(object,"mapping_age_ns"),"mapping_age_ns"); output.market_age_ns=json_int64(required(object,"market_age_ns"),"market_age_ns");
  if(output.mapping_age_ns<0||output.market_age_ns<0) invalid("invalid_freshness"); output.session_state=bounded_string(required(object,"session_state"),"session_state",32);
  static const std::set<std::string> session_states={"ready","not_ready","safety_stop","reconciliation_required","stopping"};
  if(!session_states.contains(output.session_state)) invalid("invalid_session_state"); return output;
}
std::string RiskDecision::to_json() const {
  JsonObject object=base_document(); object.emplace("configuration_digest",text(configuration_digest)); object.emplace("decision",text(decision)); object.emplace("decision_id",text(decision_id)); object.emplace("intent_id",text(intent_id));
  object.emplace("mapping_age_ns",integer(mapping_age_ns)); object.emplace("market_age_ns",integer(market_age_ns)); add_optional(object,"rejection_code",rejection_code); add_optional(object,"rejection_reason",rejection_reason);
  JsonArray rules; for(const auto& check:rules_checked) rules.emplace_back(JsonObject{{"before_value",integer(check.before_value)},{"limit_value",integer(check.limit_value)},{"outcome",text(check.outcome)},{"projected_value",integer(check.projected_value)},{"rule",text(check.rule)},{"unit",text(check.unit)}});
  object.emplace("rule_set_version",text(rule_set_version)); object.emplace("rules_checked",JsonValue(std::move(rules))); object.emplace("session_state",text(session_state)); object.emplace("timestamp_ns",integer(timestamp_ns)); return canonical_json(JsonValue(std::move(object)));
}

PositionSnapshot PositionSnapshot::parse(std::string_view json) {
  const auto document=parse_json(json); const auto& object=json_object(document,"positions"); exact_fields(object,{"schema_version","snapshot_id","execution_session_id","timestamp_ns","source","provenance","reconciliation_status","positions"}); require_version(object); PositionSnapshot output;
  output.snapshot_id=bounded_string(required(object,"snapshot_id"),"snapshot_id"); require_uuid(output.snapshot_id); output.execution_session_id=bounded_string(required(object,"execution_session_id"),"execution_session_id"); require_uuid(output.execution_session_id);
  output.timestamp_ns=json_int64(required(object,"timestamp_ns"),"timestamp_ns"); output.source=bounded_string(required(object,"source"),"source",32); output.provenance=bounded_string(required(object,"provenance"),"provenance",24); output.reconciliation_status=bounded_string(required(object,"reconciliation_status"),"reconciliation_status",24);
  static const std::set<std::string> sources={"paper","kotak"}; static const std::set<std::string> provenances={"simulated","proxy","broker_confirmed"}; static const std::set<std::string> statuses={"matched","mismatch","unavailable","partial"};
  if(!sources.contains(output.source)||!provenances.contains(output.provenance)||!statuses.contains(output.reconciliation_status)) invalid("invalid_position_provenance");
  std::set<std::string> instruments,tokens; for(const auto& value:json_array(required(object,"positions"),"positions")) { const auto& item=json_object(value,"position"); exact_fields(item,{"canonical_instrument_id","instrument_token","strategy_desired","ledger_reconstructed","broker_authoritative"}); PositionEntry entry; entry.canonical_instrument_id=bounded_string(required(item,"canonical_instrument_id"),"canonical_instrument_id",192); if(!is_canonical_instrument_id(entry.canonical_instrument_id)) invalid("invalid_instrument"); entry.instrument_token=bounded_string(required(item,"instrument_token"),"instrument_token",64); entry.strategy_desired=json_int64(required(item,"strategy_desired"),"strategy_desired"); entry.ledger_reconstructed=json_int64(required(item,"ledger_reconstructed"),"ledger_reconstructed"); entry.broker_authoritative=nullable_int64(item,"broker_authoritative"); if(!instruments.insert(entry.canonical_instrument_id).second||!tokens.insert(entry.instrument_token).second) invalid("duplicate_position"); output.positions.push_back(std::move(entry)); }
  return output;
}
std::string PositionSnapshot::to_json() const { JsonObject object=base_document(); object.emplace("execution_session_id",text(execution_session_id)); JsonArray items; for(const auto& entry:positions) { JsonObject item{{"canonical_instrument_id",text(entry.canonical_instrument_id)},{"instrument_token",text(entry.instrument_token)},{"ledger_reconstructed",integer(entry.ledger_reconstructed)},{"strategy_desired",integer(entry.strategy_desired)}}; add_nullable(item,"broker_authoritative",entry.broker_authoritative); items.emplace_back(std::move(item)); } object.emplace("positions",JsonValue(std::move(items))); object.emplace("provenance",text(provenance)); object.emplace("reconciliation_status",text(reconciliation_status)); object.emplace("snapshot_id",text(snapshot_id)); object.emplace("source",text(source)); object.emplace("timestamp_ns",integer(timestamp_ns)); return canonical_json(JsonValue(std::move(object))); }

MarketObservation MarketObservation::parse(std::string_view json) {
  const auto document=parse_json(json); const auto& object=json_object(document,"observation"); exact_fields(object,{"schema_version","canonical_instrument_id","cumulative_volume","exchange_timestamp_ns","receive_timestamp_ns","source","provenance","quality_flags"},{"best_bid_paise","best_ask_paise","last_trade_paise"}); require_version(object); MarketObservation output;
  output.canonical_instrument_id=bounded_string(required(object,"canonical_instrument_id"),"canonical_instrument_id",192); if(!is_canonical_instrument_id(output.canonical_instrument_id)) invalid("invalid_instrument"); output.best_bid_paise=optional_uint64(object,"best_bid_paise"); output.best_ask_paise=optional_uint64(object,"best_ask_paise"); output.last_trade_paise=optional_uint64(object,"last_trade_paise"); if((output.best_bid_paise&&*output.best_bid_paise==0)||(output.best_ask_paise&&*output.best_ask_paise==0)||(output.last_trade_paise&&*output.last_trade_paise==0)) invalid("invalid_price"); output.cumulative_volume=json_uint64(required(object,"cumulative_volume"),"cumulative_volume"); output.exchange_timestamp_ns=nullable_int64(object,"exchange_timestamp_ns"); output.receive_timestamp_ns=json_int64(required(object,"receive_timestamp_ns"),"receive_timestamp_ns"); output.source=bounded_string(required(object,"source"),"source",32); output.provenance=bounded_string(required(object,"provenance"),"provenance",24); if(output.source!="dhan") invalid("invalid_observation_source"); if(output.provenance!="observed"&&output.provenance!="simulated"&&output.provenance!="proxy") invalid("invalid_provenance"); static const std::set<std::string> allowed={"stale","crossed_book","partial_book","source_sequence_unavailable","coalesced_update","unusable"}; const auto& quality_values=json_array(required(object,"quality_flags"),"quality_flags"); if(quality_values.size()>32) invalid("invalid_quality_flag"); for(const auto& value:quality_values) { auto flag=bounded_string(value,"quality_flag",32); if(!allowed.contains(flag)||std::find(output.quality_flags.begin(),output.quality_flags.end(),flag)!=output.quality_flags.end()) invalid("invalid_quality_flag"); output.quality_flags.push_back(std::move(flag)); } if(output.best_bid_paise&&output.best_ask_paise&&*output.best_bid_paise>*output.best_ask_paise&&std::find(output.quality_flags.begin(),output.quality_flags.end(),"unusable")==output.quality_flags.end()) invalid("crossed_book"); return output;
}
std::string MarketObservation::to_json() const { JsonObject object=base_document(); add_optional(object,"best_ask_paise",best_ask_paise); add_optional(object,"best_bid_paise",best_bid_paise); object.emplace("canonical_instrument_id",text(canonical_instrument_id)); object.emplace("cumulative_volume",integer(cumulative_volume)); add_nullable(object,"exchange_timestamp_ns",exchange_timestamp_ns); add_optional(object,"last_trade_paise",last_trade_paise); object.emplace("provenance",text(provenance)); JsonArray flags; for(const auto& flag:quality_flags) flags.emplace_back(text(flag)); object.emplace("quality_flags",JsonValue(std::move(flags))); object.emplace("receive_timestamp_ns",integer(receive_timestamp_ns)); object.emplace("source",text(source)); return canonical_json(JsonValue(std::move(object))); }

}  // namespace shaurya::execution
