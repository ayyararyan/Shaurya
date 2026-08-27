#include "shaurya/execution/kotak_adapter.hpp"

#include "shaurya/execution/canonical_json.hpp"

#include <algorithm>
#include <stdexcept>

namespace shaurya::execution {
namespace {
const JsonValue& required(const JsonObject& object, std::string_view key) {
  const auto iterator = object.find(key);
  if (iterator == object.end()) throw JsonError("kotak_fixture_missing_field");
  return iterator->second;
}
void exact(const JsonObject& object, std::initializer_list<std::string_view> fields) {
  if (object.size() != fields.size()) throw JsonError("kotak_fixture_unknown_field");
  for (const auto field : fields)
    if (!object.contains(field)) throw JsonError("kotak_fixture_missing_field");
}
JsonValue text(std::string value) { return JsonValue(std::move(value)); }
JsonValue integer(std::uint64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
std::string side(OrderSide value) { return value == OrderSide::Buy ? "BUY" : "SELL"; }
bool bounded_identifier(std::string_view value, std::size_t maximum) {
  return !value.empty() && value.size() <= maximum &&
         std::all_of(value.begin(), value.end(), [](char item) {
           return (item >= 'A' && item <= 'Z') || (item >= 'a' && item <= 'z') ||
                  (item >= '0' && item <= '9') || item == '-' || item == '_';
         });
}
std::string update_fingerprint(const KotakParsedUpdate& update) {
  return sha256_hex(std::to_string(update.sequence) + "|" + update.internal_order_id + "|" +
                    update.state + "|" + std::to_string(update.cumulative_filled_quantity));
}
void validate_route(const RoutingRecord& route) {
  if (route.canonical_instrument_id.empty() || route.instrument_token.empty() ||
      route.exchange_segment != "nse_fo" || route.trading_symbol.empty() ||
      route.lot_size == 0U || route.tick_size_paise == 0U)
    throw std::invalid_argument("unverified_routing_result");
}
void validate_correlation(std::string_view value) {
  if (value.empty() || value.size() > 64U ||
      !std::all_of(value.begin(), value.end(), [](char item) {
        return (item >= 'A' && item <= 'Z') || (item >= 'a' && item <= 'z') ||
               (item >= '0' && item <= '9') || item == '-' || item == '_';
      })) throw std::invalid_argument("invalid_correlation_id");
}
KotakFixtureRequest build(KotakFixtureOperation operation, JsonObject body,
                          std::string correlation_id) {
  validate_correlation(correlation_id);
  body.emplace("correlation_id", text(correlation_id));
  return {operation, std::move(correlation_id), canonical_json(JsonValue(std::move(body)))};
}
}

KotakFixtureRequest KotakFixtureCodec::build_place(const BrokerOrderRequest& request,
                                                   std::string correlation_id) {
  validate_route(request.route);
  if (request.internal_order_id.empty() || request.quantity == 0U ||
      request.limit_price_paise == 0U) throw std::invalid_argument("invalid_place_request");
  return build(KotakFixtureOperation::Place,
               {{"exchange_segment", text(request.route.exchange_segment)},
                {"instrument_token", text(request.route.instrument_token)},
                {"internal_order_id", text(request.internal_order_id)},
                {"limit_price_paise", integer(request.limit_price_paise)},
                {"order_type", text("LIMIT")}, {"product", text("NRML")},
                {"quantity", integer(request.quantity)}, {"side", text(side(request.side))},
                {"time_in_force", text("DAY")},
                {"trading_symbol", text(request.route.trading_symbol)}},
               std::move(correlation_id));
}

KotakFixtureRequest KotakFixtureCodec::build_modify(const BrokerModifyRequest& request,
                                                    const RoutingRecord& route, OrderSide order_side,
                                                    std::string correlation_id) {
  validate_route(route);
  if (request.internal_order_id.empty() || request.quantity == 0U ||
      request.limit_price_paise == 0U) throw std::invalid_argument("invalid_modify_request");
  return build(KotakFixtureOperation::Modify,
               {{"exchange_segment", text(route.exchange_segment)},
                {"instrument_token", text(route.instrument_token)},
                {"internal_order_id", text(request.internal_order_id)},
                {"limit_price_paise", integer(request.limit_price_paise)},
                {"order_type", text("LIMIT")}, {"product", text("NRML")},
                {"quantity", integer(request.quantity)}, {"side", text(side(order_side))},
                {"time_in_force", text("DAY")}, {"trading_symbol", text(route.trading_symbol)}},
               std::move(correlation_id));
}

KotakFixtureRequest KotakFixtureCodec::build_cancel(std::string_view internal_order_id,
                                                    const RoutingRecord& route,
                                                    std::string correlation_id) {
  validate_route(route);
  if (internal_order_id.empty()) throw std::invalid_argument("invalid_cancel_request");
  return build(KotakFixtureOperation::Cancel,
               {{"exchange_segment", text(route.exchange_segment)},
                {"instrument_token", text(route.instrument_token)},
                {"internal_order_id", text(std::string(internal_order_id))},
                {"trading_symbol", text(route.trading_symbol)}},
               std::move(correlation_id));
}

BrokerMutationResult KotakFixtureCodec::parse_mutation_response(
    std::string_view internal_order_id, std::string_view correlation_id,
    unsigned http_status, std::string_view sanitized_body) {
  validate_correlation(correlation_id);
  if (http_status < 200U || http_status >= 300U)
    return {BrokerMutationStatus::Ambiguous, std::string(internal_order_id), std::nullopt,
            "sanitized_fixture", BrokerError{"http_failure", http_status,
                                               std::string(correlation_id)}};
  try {
    const auto document = parse_json(sanitized_body, 16U * 1024U);
    const auto& object = json_object(document, "kotak_fixture_response");
    exact(object, {"broker_correlation_id", "correlation_id", "status"});
    if (json_string(required(object, "correlation_id"), "correlation_id") != correlation_id)
      throw JsonError("kotak_fixture_correlation_mismatch");
    const auto status = json_string(required(object, "status"), "status");
    const auto broker_id = json_string(required(object, "broker_correlation_id"),
                                       "broker_correlation_id");
    if (!bounded_identifier(broker_id, 64U)) throw JsonError("kotak_fixture_invalid_id");
    if (status == "acknowledged")
      return {BrokerMutationStatus::Acknowledged, std::string(internal_order_id), broker_id,
              "sanitized_fixture", std::nullopt};
    if (status == "rejected")
      return {BrokerMutationStatus::Rejected, std::string(internal_order_id), broker_id,
              "sanitized_fixture", BrokerError{"broker_rejected", http_status,
                                                 std::string(correlation_id)}};
    throw JsonError("kotak_fixture_invalid_status");
  } catch (const JsonError&) {
    return {BrokerMutationStatus::Ambiguous, std::string(internal_order_id), std::nullopt,
            "sanitized_fixture", BrokerError{"malformed_response", http_status,
                                               std::string(correlation_id)}};
  }
}

KotakParsedUpdate KotakFixtureCodec::parse_update(std::string_view sanitized_body) {
  const auto document = parse_json(sanitized_body, 16U * 1024U);
  const auto& object = json_object(document, "kotak_fixture_update");
  exact(object, {"cumulative_filled_quantity", "internal_order_id", "sequence", "state",
                 "update_id"});
  KotakParsedUpdate update{json_uint64(required(object, "sequence"), "sequence"),
                           json_string(required(object, "update_id"), "update_id"),
                           json_string(required(object, "internal_order_id"), "internal_order_id"),
                           json_string(required(object, "state"), "state"),
                           json_uint64(required(object, "cumulative_filled_quantity"),
                                       "cumulative_filled_quantity"),
                           "sanitized_fixture"};
  if (update.sequence == 0U || !bounded_identifier(update.update_id, 64U) ||
      (update.state != "session_lost" && !is_canonical_uuid(update.internal_order_id)) ||
      (update.state == "session_lost" && !update.internal_order_id.empty()) ||
      (update.state != "acknowledged" && update.state != "partially_filled" &&
       update.state != "filled" && update.state != "cancelled" &&
       update.state != "rejected" && update.state != "session_lost") ||
      (update.state == "acknowledged" && update.cumulative_filled_quantity != 0U) ||
      ((update.state == "partially_filled" || update.state == "filled") &&
       update.cumulative_filled_quantity == 0U))
    throw JsonError("kotak_fixture_invalid_update");
  return update;
}

void KotakFixtureCodec::require_live_mode(bool requested) {
  if (requested) throw std::logic_error("kotak_live_transport_not_compiled");
}

KotakFixtureUpdateQueue::KotakFixtureUpdateQueue(std::size_t maximum_depth)
    : maximum_depth_(maximum_depth) {
  if (maximum_depth == 0U) throw std::invalid_argument("invalid_update_queue_depth");
}

bool KotakFixtureUpdateQueue::push(KotakParsedUpdate update) {
  if (safety_stopped_) return false;
  if (const auto found = update_fingerprints_.find(update.update_id);
      found != update_fingerprints_.end()) {
    if (found->second == update_fingerprint(update)) return true;
    safety_stopped_ = true;
    return false;
  }
  if (update.sequence <= last_sequence_ || queued_.size() >= maximum_depth_ ||
      update.state == "session_lost") {
    safety_stopped_ = true;
    return false;
  }
  last_sequence_ = update.sequence;
  update_fingerprints_.emplace(update.update_id, update_fingerprint(update));
  queued_.push_back(std::move(update));
  return true;
}

std::vector<KotakParsedUpdate> KotakFixtureUpdateQueue::drain() {
  auto result = std::move(queued_);
  queued_.clear();
  return result;
}

}  // namespace shaurya::execution
