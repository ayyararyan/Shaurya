#include "shaurya/execution/risk.hpp"

#include "shaurya/execution/canonical_json.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <string_view>

namespace shaurya::execution {
namespace {

const JsonValue& required_field(const JsonObject& object, std::string_view key) {
  const auto found = object.find(key);
  if (found == object.end()) throw std::invalid_argument("risk_config_missing_field");
  return found->second;
}

void exact_fields(const JsonObject& object, std::initializer_list<std::string_view> fields) {
  if (object.size() != fields.size()) throw std::invalid_argument("risk_config_unknown_field");
  for (const auto field : fields) {
    if (!object.contains(field)) throw std::invalid_argument("risk_config_missing_field");
  }
}

JsonValue json_text(std::string value) { return JsonValue(std::move(value)); }
JsonValue json_unsigned(std::uint64_t value) {
  return JsonValue(JsonInteger{std::to_string(value)});
}
JsonValue json_signed(std::int64_t value) {
  return JsonValue(JsonInteger{std::to_string(value)});
}
JsonValue json_nullable(std::optional<std::int64_t> value) {
  return value ? json_signed(*value) : JsonValue();
}

std::optional<std::int64_t> optional_int64(const JsonValue& value, std::string_view field) {
  if (std::holds_alternative<std::nullptr_t>(value.value)) return std::nullopt;
  return json_int64(value, field);
}

bool lowercase_digest(std::string_view value) {
  return value.size() == 64U && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= '0' && item <= '9') || (item >= 'a' && item <= 'f');
  });
}

bool valid_trading_date(std::string_view value) {
  if (value.size() != 10U || value[4] != '-' || value[7] != '-') return false;
  for (std::size_t index = 0; index < value.size(); ++index) {
    if (index == 4U || index == 7U) continue;
    if (value[index] < '0' || value[index] > '9') return false;
  }
  const unsigned month = static_cast<unsigned>((value[5] - '0') * 10 + value[6] - '0');
  const unsigned day = static_cast<unsigned>((value[8] - '0') * 10 + value[9] - '0');
  return month >= 1U && month <= 12U && day >= 1U && day <= 31U;
}

std::string deterministic_uuid(std::string_view seed) {
  std::string digest = sha256_hex(seed);
  digest[12] = '4';
  digest[16] = '8';
  return digest.substr(0, 8) + '-' + digest.substr(8, 4) + '-' + digest.substr(12, 4) + '-' +
         digest.substr(16, 4) + '-' + digest.substr(20, 12);
}

bool add_overflow(std::int64_t left, std::int64_t right, std::int64_t& output) {
  if ((right > 0 && left > std::numeric_limits<std::int64_t>::max() - right) ||
      (right < 0 && left < std::numeric_limits<std::int64_t>::min() - right)) return true;
  output = left + right;
  return false;
}

bool multiply_overflow(std::uint64_t left, std::uint64_t right, std::uint64_t& output) {
  if (left != 0U && right > std::numeric_limits<std::uint64_t>::max() / left) return true;
  output = left * right;
  return false;
}

bool signed_multiply_overflow(std::int64_t left, std::int64_t right, std::int64_t& output) {
  if (left == 0 || right == 0) { output = 0; return false; }
  if ((left == -1 && right == std::numeric_limits<std::int64_t>::min()) ||
      (right == -1 && left == std::numeric_limits<std::int64_t>::min())) return true;
  if (left > 0) {
    if ((right > 0 && left > std::numeric_limits<std::int64_t>::max() / right) ||
        (right < 0 && right < std::numeric_limits<std::int64_t>::min() / left)) return true;
  } else {
    if ((right > 0 && left < std::numeric_limits<std::int64_t>::min() / right) ||
        (right < 0 && left < std::numeric_limits<std::int64_t>::max() / right)) return true;
  }
  output = left * right;
  return false;
}

std::int64_t bounded_uint(std::uint64_t value) {
  return value > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())
             ? std::numeric_limits<std::int64_t>::max()
             : static_cast<std::int64_t>(value);
}

std::int64_t absolute_saturated(std::int64_t value) {
  if (value == std::numeric_limits<std::int64_t>::min())
    return std::numeric_limits<std::int64_t>::max();
  return value < 0 ? -value : value;
}

bool unhealthy_quality(const MarketObservation& observation) {
  static constexpr std::string_view blocked[] = {"stale", "crossed_book", "unusable"};
  return std::any_of(observation.quality_flags.begin(), observation.quality_flags.end(),
                     [](const std::string& flag) {
    return std::find(std::begin(blocked), std::end(blocked), flag) != std::end(blocked);
  });
}

}  // namespace

std::string RiskConfiguration::canonical_payload() const {
  JsonObject greeks_object{{"maximum_absolute_delta", json_nullable(greeks.maximum_absolute_delta)},
                           {"maximum_absolute_gamma", json_nullable(greeks.maximum_absolute_gamma)},
                           {"maximum_absolute_vega", json_nullable(greeks.maximum_absolute_vega)}};
  JsonObject object{{"configuration_version", json_text(configuration_version)},
                    {"greeks", JsonValue(std::move(greeks_object))},
                    {"maximum_absolute_instrument_position",
                     json_signed(maximum_absolute_instrument_position)},
                    {"maximum_clock_skew_ns", json_signed(maximum_clock_skew_ns)},
                    {"maximum_daily_loss_paise", json_unsigned(maximum_daily_loss_paise)},
                    {"maximum_drawdown_paise", json_unsigned(maximum_drawdown_paise)},
                    {"maximum_greek_age_ns", json_signed(maximum_greek_age_ns)},
                    {"maximum_gross_premium_paise", json_unsigned(maximum_gross_premium_paise)},
                    {"maximum_mapping_age_ns", json_signed(maximum_mapping_age_ns)},
                    {"maximum_observation_age_ns", json_signed(maximum_observation_age_ns)},
                    {"maximum_order_quantity", json_unsigned(maximum_order_quantity)},
                    {"maximum_orders_per_window", json_unsigned(maximum_orders_per_window)},
                    {"maximum_outstanding_orders", json_unsigned(maximum_outstanding_orders)},
                    {"order_rate_window_ns", json_signed(order_rate_window_ns)},
                    {"schema_version", json_text(schema_version)},
                    {"trading_date", json_text(trading_date)}};
  return canonical_json(JsonValue(std::move(object)));
}

RiskConfiguration RiskConfiguration::parse(std::string_view json) {
  try {
    const auto document = parse_json(json, 64U * 1024U);
    const auto& object = json_object(document, "risk_configuration");
    exact_fields(object, {"configuration_digest", "configuration_version", "greeks",
                          "maximum_absolute_instrument_position", "maximum_clock_skew_ns",
                          "maximum_daily_loss_paise", "maximum_drawdown_paise",
                          "maximum_greek_age_ns", "maximum_gross_premium_paise",
                          "maximum_mapping_age_ns",
                          "maximum_observation_age_ns", "maximum_order_quantity",
                          "maximum_orders_per_window", "maximum_outstanding_orders",
                          "order_rate_window_ns", "schema_version", "trading_date"});
    const auto& greek_object = json_object(required_field(object, "greeks"), "greeks");
    exact_fields(greek_object, {"maximum_absolute_delta", "maximum_absolute_gamma",
                                "maximum_absolute_vega"});
    RiskConfiguration result;
    result.schema_version = json_string(required_field(object, "schema_version"), "schema_version");
    result.configuration_version = json_string(required_field(object, "configuration_version"),
                                               "configuration_version");
    result.configuration_digest = json_string(required_field(object, "configuration_digest"),
                                              "configuration_digest");
    result.trading_date = json_string(required_field(object, "trading_date"), "trading_date");
    result.maximum_observation_age_ns = json_int64(
        required_field(object, "maximum_observation_age_ns"), "maximum_observation_age_ns");
    result.maximum_mapping_age_ns = json_int64(
        required_field(object, "maximum_mapping_age_ns"), "maximum_mapping_age_ns");
    result.maximum_greek_age_ns = json_int64(required_field(object, "maximum_greek_age_ns"),
                                            "maximum_greek_age_ns");
    result.maximum_clock_skew_ns = json_int64(required_field(object, "maximum_clock_skew_ns"),
                                             "maximum_clock_skew_ns");
    result.maximum_order_quantity = json_uint64(required_field(object, "maximum_order_quantity"),
                                               "maximum_order_quantity");
    result.maximum_absolute_instrument_position = json_int64(
        required_field(object, "maximum_absolute_instrument_position"),
        "maximum_absolute_instrument_position");
    result.maximum_gross_premium_paise = json_uint64(
        required_field(object, "maximum_gross_premium_paise"), "maximum_gross_premium_paise");
    result.maximum_outstanding_orders = json_uint64(
        required_field(object, "maximum_outstanding_orders"), "maximum_outstanding_orders");
    result.maximum_orders_per_window = json_uint64(
        required_field(object, "maximum_orders_per_window"), "maximum_orders_per_window");
    result.order_rate_window_ns = json_int64(required_field(object, "order_rate_window_ns"),
                                            "order_rate_window_ns");
    result.maximum_daily_loss_paise = json_uint64(
        required_field(object, "maximum_daily_loss_paise"), "maximum_daily_loss_paise");
    result.maximum_drawdown_paise = json_uint64(
        required_field(object, "maximum_drawdown_paise"), "maximum_drawdown_paise");
    result.greeks.maximum_absolute_delta = optional_int64(
        required_field(greek_object, "maximum_absolute_delta"), "maximum_absolute_delta");
    result.greeks.maximum_absolute_gamma = optional_int64(
        required_field(greek_object, "maximum_absolute_gamma"), "maximum_absolute_gamma");
    result.greeks.maximum_absolute_vega = optional_int64(
        required_field(greek_object, "maximum_absolute_vega"), "maximum_absolute_vega");
    if (!lowercase_digest(result.configuration_digest) ||
        sha256_hex(result.canonical_payload()) != result.configuration_digest) {
      throw std::invalid_argument("risk_config_digest_mismatch");
    }
    return result;
  } catch (const JsonError&) {
    throw std::invalid_argument("invalid_risk_configuration_json");
  }
}

RiskEngine::RiskEngine(RiskConfiguration configuration) : configuration_(std::move(configuration)) {
  if (configuration_.schema_version != "1.0.0" || configuration_.configuration_version.empty() ||
      !lowercase_digest(configuration_.configuration_digest) ||
      !valid_trading_date(configuration_.trading_date) ||
      configuration_.maximum_observation_age_ns < 0 ||
      configuration_.maximum_mapping_age_ns <= 0 ||
      configuration_.maximum_greek_age_ns < 0 || configuration_.maximum_clock_skew_ns < 0 ||
      configuration_.maximum_order_quantity == 0U ||
      configuration_.maximum_absolute_instrument_position <= 0 ||
      configuration_.maximum_gross_premium_paise == 0U ||
      configuration_.maximum_outstanding_orders == 0U ||
      configuration_.maximum_orders_per_window == 0U ||
      configuration_.order_rate_window_ns <= 0 ||
      configuration_.maximum_daily_loss_paise == 0U ||
      configuration_.maximum_drawdown_paise == 0U) {
    throw std::invalid_argument("invalid_risk_configuration");
  }
  if (sha256_hex(configuration_.canonical_payload()) != configuration_.configuration_digest)
    throw std::invalid_argument("risk_config_digest_mismatch");
  for (const auto limit : {configuration_.greeks.maximum_absolute_delta,
                           configuration_.greeks.maximum_absolute_gamma,
                           configuration_.greeks.maximum_absolute_vega}) {
    if (limit && *limit <= 0) throw std::invalid_argument("invalid_greek_limit");
  }
}

RiskDecision RiskEngine::evaluate(const OrderIntent& intent, const RiskSnapshot& snapshot) const {
  RiskDecision decision;
  decision.intent_id = intent.intent_id;
  decision.timestamp_ns = snapshot.now_ns;
  decision.rule_set_version = "risk-v1";
  decision.configuration_digest = configuration_.configuration_digest;
  decision.mapping_age_ns = std::max<std::int64_t>(0, snapshot.mapping_age_ns);
  decision.market_age_ns = 0;
  decision.session_state = snapshot.ready ? "ready" : "not_ready";

  std::optional<std::string> rejection;
  const auto check = [&](std::string rule, bool passed, std::int64_t before,
                         std::int64_t projected, std::int64_t limit, std::string unit,
                         std::string code) {
    if (rejection) return;
    decision.rules_checked.push_back(
        {std::move(rule), passed ? "pass" : "fail", before, projected, limit, std::move(unit)});
    if (!passed && !rejection) rejection = std::move(code);
  };

  const bool correlation_ok =
      (snapshot.expected_execution_session_id.empty() ||
       intent.execution_session_id == snapshot.expected_execution_session_id) &&
      (snapshot.expected_strategy_id.empty() || intent.strategy_id == snapshot.expected_strategy_id) &&
      (snapshot.expected_strategy_run_id.empty() ||
       intent.strategy_run_id == snapshot.expected_strategy_run_id);

  if (intent.action == IntentAction::Cancel) {
    check("cancel_correlation", correlation_ok, 0, correlation_ok ? 0 : 1, 0, "state",
          "intent_correlation_mismatch");
    check("cancel_idempotency", snapshot.idempotency == RiskIdempotencyState::NewIntent, 0, 0, 0,
          "state", snapshot.idempotency == RiskIdempotencyState::Conflict
                           ? "intent_payload_conflict"
                           : "duplicate_intent");
    check("cancel_target", snapshot.cancel_target_known && !snapshot.cancel_target_terminal,
          bounded_uint(snapshot.cancel_target_filled_quantity),
          bounded_uint(snapshot.cancel_target_filled_quantity), 0, "units", "cancel_target_invalid");
    check("cancel_session", snapshot.broker_health != BrokerSessionHealth::Lost, 0, 0, 0,
          "state", "broker_session_lost");
    if (!rejection && snapshot.broker_health == BrokerSessionHealth::Unknown)
      decision.session_state = "reconciliation_required";
  } else {
    check("authority", !snapshot.kill_switch && snapshot.ready &&
                           !snapshot.reconciliation_required,
          snapshot.kill_switch ? 1 : 0, snapshot.ready ? 0 : 1, 0, "boolean",
          snapshot.kill_switch ? "kill_switch" : "session_not_ready");
    check("idempotency", snapshot.idempotency == RiskIdempotencyState::NewIntent, 0, 0, 0,
          "state", snapshot.idempotency == RiskIdempotencyState::Conflict
                           ? "intent_payload_conflict"
                           : "duplicate_intent");
    check("correlation", correlation_ok, 0, correlation_ok ? 0 : 1, 0, "state",
          "intent_correlation_mismatch");
    const bool route_ok = snapshot.mapping_state == RiskMappingState::Verified && snapshot.route &&
                          snapshot.route_trading_date == configuration_.trading_date &&
                          snapshot.route->canonical_instrument_id == intent.canonical_instrument_id &&
                          snapshot.mapping_age_ns >= 0 && snapshot.maximum_mapping_age_ns > 0 &&
                          snapshot.mapping_age_ns <= snapshot.maximum_mapping_age_ns;
    check("routing", route_ok, snapshot.mapping_age_ns, snapshot.mapping_age_ns,
          snapshot.maximum_mapping_age_ns, "ns",
          snapshot.mapping_age_ns > snapshot.maximum_mapping_age_ns ? "routing_stale"
                                                                     : "routing_unverified");
    const bool shape_ok = intent.side && intent.quantity && *intent.quantity > 0U &&
                          intent.limit_price_paise && *intent.limit_price_paise > 0U &&
                          intent.product == "NRML" && intent.time_in_force == "DAY";
    check("contract", shape_ok, 0, shape_ok ? 0 : 1, 0, "state", "unsupported_order_shape");
    if (intent.action == IntentAction::Modify) {
      const bool target_ok = intent.target_internal_order_id && snapshot.mutation_target_known &&
                             !snapshot.mutation_target_terminal && snapshot.mutation_target &&
                             snapshot.mutation_target->canonical_instrument_id ==
                                 intent.canonical_instrument_id &&
                             snapshot.mutation_target->side == intent.side && intent.quantity &&
                             *intent.quantity >
                                 snapshot.mutation_target->cumulative_filled_quantity;
      check("modify_target", target_ok, 0, target_ok ? 0 : 1, 0, "state",
            "modify_target_invalid");
    }
    std::int64_t latest_created = snapshot.now_ns;
    if (configuration_.maximum_clock_skew_ns <=
        std::numeric_limits<std::int64_t>::max() - snapshot.now_ns) {
      latest_created += configuration_.maximum_clock_skew_ns;
    } else {
      latest_created = std::numeric_limits<std::int64_t>::max();
    }
    const bool time_ok = intent.expires_at_ns > intent.created_at_ns &&
                         snapshot.now_ns < intent.expires_at_ns && intent.created_at_ns <= latest_created;
    check("time", time_ok, intent.created_at_ns, snapshot.now_ns, intent.expires_at_ns, "ns",
          "intent_expired_or_skewed");
    check("broker_health", snapshot.broker_health == BrokerSessionHealth::Ready, 0, 0, 0,
          "state", "broker_unhealthy");

    std::int64_t observation_age = std::numeric_limits<std::int64_t>::max();
    bool observation_ok = false;
    if (snapshot.observation) {
      if (snapshot.observation->receive_timestamp_ns >= 0 &&
          snapshot.now_ns >= snapshot.observation->receive_timestamp_ns)
        observation_age = snapshot.now_ns - snapshot.observation->receive_timestamp_ns;
      observation_ok = snapshot.observation->canonical_instrument_id == intent.canonical_instrument_id &&
                       snapshot.observation->source == "dhan" && !unhealthy_quality(*snapshot.observation) &&
                       observation_age >= 0 && observation_age <= configuration_.maximum_observation_age_ns;
      if (snapshot.observation->exchange_timestamp_ns &&
          (*snapshot.observation->exchange_timestamp_ns < 0 ||
           *snapshot.observation->exchange_timestamp_ns > snapshot.observation->receive_timestamp_ns ||
           snapshot.now_ns < *snapshot.observation->exchange_timestamp_ns ||
           snapshot.now_ns - *snapshot.observation->exchange_timestamp_ns >
               configuration_.maximum_observation_age_ns)) observation_ok = false;
    }
    decision.market_age_ns = observation_age;
    check("observation", observation_ok, observation_age, observation_age,
          configuration_.maximum_observation_age_ns, "ns", "observation_unusable");

    const std::uint64_t quantity = intent.quantity.value_or(0U);
    const std::uint64_t projected_quantity =
        intent.action == IntentAction::Modify && snapshot.mutation_target &&
                quantity > snapshot.mutation_target->cumulative_filled_quantity
            ? quantity - snapshot.mutation_target->cumulative_filled_quantity
            : quantity;
    const std::uint64_t price = intent.limit_price_paise.value_or(0U);
    const std::uint64_t lot = snapshot.route ? snapshot.route->lot_size : 0U;
    const std::uint64_t tick = snapshot.route ? snapshot.route->tick_size_paise : 0U;
    const bool sizing_ok = lot > 0U && tick > 0U && quantity > 0U && quantity % lot == 0U &&
                           price > 0U && price % tick == 0U &&
                           quantity <= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) &&
                           price <= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) &&
                           quantity <= configuration_.maximum_order_quantity;
    check("sizing", sizing_ok, bounded_uint(quantity), bounded_uint(quantity),
          bounded_uint(configuration_.maximum_order_quantity), "units", "invalid_tick_lot_or_size");

    std::uint64_t outstanding = snapshot.working_orders.size();
    if (intent.action == IntentAction::Modify && intent.target_internal_order_id &&
        std::any_of(snapshot.working_orders.begin(), snapshot.working_orders.end(),
                    [&](const WorkingRiskOrder& order) {
                      return order.internal_order_id == *intent.target_internal_order_id;
                    })) --outstanding;
    check("outstanding_orders", outstanding < configuration_.maximum_outstanding_orders,
          bounded_uint(outstanding), bounded_uint(outstanding + 1U),
          bounded_uint(configuration_.maximum_outstanding_orders), "orders", "outstanding_limit");
    const auto window_start = snapshot.now_ns <
        std::numeric_limits<std::int64_t>::min() + configuration_.order_rate_window_ns
                                  ? std::numeric_limits<std::int64_t>::min()
                                  : snapshot.now_ns - configuration_.order_rate_window_ns;
    const auto recent = static_cast<std::uint64_t>(std::count_if(
        snapshot.recent_order_timestamps_ns.begin(), snapshot.recent_order_timestamps_ns.end(),
        [&](std::int64_t timestamp) { return timestamp > window_start && timestamp <= snapshot.now_ns; }));
    check("order_rate", recent < configuration_.maximum_orders_per_window, bounded_uint(recent),
          bounded_uint(recent + 1U), bounded_uint(configuration_.maximum_orders_per_window),
          "orders", "order_rate_limit");

    const bool position_authority = snapshot.broker_positions_authoritative &&
                                    snapshot.position_marks_authoritative;
    check("position_authority", position_authority, 0,
          position_authority ? 0 : 1, 0, "state",
          snapshot.broker_positions_authoritative ? "position_marks_not_authoritative"
                                                  : "positions_not_authoritative");
    std::int64_t projected_position = snapshot.exact_instrument_position;
    bool position_overflow = false;
    for (const auto& order : snapshot.working_orders) {
      if (order.canonical_instrument_id != intent.canonical_instrument_id) continue;
      if (intent.action == IntentAction::Modify && intent.target_internal_order_id &&
          order.internal_order_id == *intent.target_internal_order_id) {
        continue;
      }
      const auto signed_quantity = order.remaining_quantity > static_cast<std::uint64_t>(
          std::numeric_limits<std::int64_t>::max())
                                       ? std::numeric_limits<std::int64_t>::max()
                                       : static_cast<std::int64_t>(order.remaining_quantity);
      std::int64_t updated = projected_position;
      position_overflow |= add_overflow(projected_position,
          order.side == OrderSide::Buy ? signed_quantity : -signed_quantity, updated);
      projected_position = updated;
    }
    const auto signed_new = projected_quantity > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())
                                ? std::numeric_limits<std::int64_t>::max()
                                : static_cast<std::int64_t>(projected_quantity);
    std::int64_t final_position = projected_position;
    position_overflow |= add_overflow(projected_position,
        intent.side == OrderSide::Buy ? signed_new : -signed_new, final_position);
    const bool position_ok = !position_overflow &&
                             absolute_saturated(final_position) <=
                                 configuration_.maximum_absolute_instrument_position;
    check("position", position_ok, snapshot.exact_instrument_position, final_position,
          configuration_.maximum_absolute_instrument_position, "units", "position_limit");
    const auto sell_quantity = projected_quantity > static_cast<std::uint64_t>(
        std::numeric_limits<std::int64_t>::max())
                                   ? std::numeric_limits<std::int64_t>::max()
                                   : static_cast<std::int64_t>(projected_quantity);
    std::uint64_t reserved_sell = snapshot.exact_token_working_sell_quantity;
    if (intent.action == IntentAction::Modify && snapshot.mutation_target &&
        snapshot.mutation_target->side == OrderSide::Sell &&
        reserved_sell >= snapshot.mutation_target->remaining_quantity) {
      reserved_sell -= snapshot.mutation_target->remaining_quantity;
    }
    const bool reserved_fits = reserved_sell <=
        static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
    const auto required_sell = reserved_fits &&
        static_cast<std::uint64_t>(sell_quantity) <=
            static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) - reserved_sell
                                   ? static_cast<std::int64_t>(reserved_sell) + sell_quantity
                                   : std::numeric_limits<std::int64_t>::max();
    const bool sell_ok = intent.side != OrderSide::Sell ||
                         (reserved_fits && snapshot.exact_token_position >= required_sell);
    check("sell_availability", sell_ok, snapshot.exact_token_position,
          snapshot.exact_token_position >= std::numeric_limits<std::int64_t>::min() + sell_quantity
              ? snapshot.exact_token_position - sell_quantity
              : std::numeric_limits<std::int64_t>::min(), 0, "units",
          "token_inventory_unavailable");

    std::uint64_t gross = snapshot.current_gross_premium_paise;
    bool gross_overflow = false;
    for (const auto& order : snapshot.working_orders) {
      if (intent.action == IntentAction::Modify && intent.target_internal_order_id &&
          order.internal_order_id == *intent.target_internal_order_id) continue;
      std::uint64_t premium{};
      gross_overflow |= multiply_overflow(order.remaining_quantity, order.limit_price_paise, premium);
      if (gross > std::numeric_limits<std::uint64_t>::max() - premium) gross_overflow = true;
      else gross += premium;
    }
    std::uint64_t new_premium{};
    gross_overflow |= multiply_overflow(projected_quantity, price, new_premium);
    const std::uint64_t projected_gross = gross_overflow || gross >
        std::numeric_limits<std::uint64_t>::max() - new_premium
                                             ? std::numeric_limits<std::uint64_t>::max()
                                             : gross + new_premium;
    check("gross_premium", !gross_overflow &&
                               projected_gross <= configuration_.maximum_gross_premium_paise,
          bounded_uint(gross), bounded_uint(projected_gross),
          bounded_uint(configuration_.maximum_gross_premium_paise), "paise", "gross_premium_limit");

    const auto greek_check = [&](std::string name, std::optional<std::int64_t> limit,
                                 std::int64_t current, std::int64_t per_unit) {
      if (!limit || rejection) return;
      bool fresh = snapshot.greek_snapshot && snapshot.greek_snapshot->authoritative &&
                   snapshot.greek_snapshot->canonical_instrument_id == intent.canonical_instrument_id &&
                   snapshot.greek_snapshot->source == "risk_provider" &&
                   snapshot.greek_snapshot->provenance == "authoritative" &&
                   snapshot.greek_snapshot->timestamp_ns >= 0 &&
                   snapshot.now_ns >= snapshot.greek_snapshot->timestamp_ns &&
                   snapshot.now_ns - snapshot.greek_snapshot->timestamp_ns <=
                       configuration_.maximum_greek_age_ns;
      std::int64_t change{};
      std::int64_t projected{};
      const auto direction = intent.side == OrderSide::Buy ? signed_new : -signed_new;
      const bool overflow = signed_multiply_overflow(per_unit, direction, change) ||
                            add_overflow(current, change, projected);
      check(std::move(name), fresh && !overflow && absolute_saturated(projected) <= *limit,
            current, projected, *limit, "scaled_greek", fresh ? "greek_limit" : "greeks_stale");
    };
    const GreekSnapshot empty{};
    const auto& greeks = snapshot.greek_snapshot ? *snapshot.greek_snapshot : empty;
    greek_check("delta", configuration_.greeks.maximum_absolute_delta,
                greeks.current_delta, greeks.delta_per_unit);
    greek_check("gamma", configuration_.greeks.maximum_absolute_gamma,
                greeks.current_gamma, greeks.gamma_per_unit);
    greek_check("vega", configuration_.greeks.maximum_absolute_vega,
                greeks.current_vega, greeks.vega_per_unit);
    const bool pnl_authoritative = snapshot.daily_loss_paise && snapshot.drawdown_paise &&
        snapshot.pnl_timestamp_ns && snapshot.now_ns >= *snapshot.pnl_timestamp_ns &&
        snapshot.now_ns - *snapshot.pnl_timestamp_ns <= configuration_.maximum_observation_age_ns &&
        snapshot.pnl_source == "paper" && snapshot.pnl_provenance == "simulated_proxy";
    check("pnl_authority", pnl_authoritative, 0, pnl_authoritative ? 0 : 1, 0, "state",
          "pnl_not_authoritative");
    check("daily_loss", snapshot.daily_loss_paise.value_or(std::numeric_limits<std::uint64_t>::max()) <= configuration_.maximum_daily_loss_paise,
          bounded_uint(snapshot.daily_loss_paise.value_or(std::numeric_limits<std::uint64_t>::max())), bounded_uint(snapshot.daily_loss_paise.value_or(std::numeric_limits<std::uint64_t>::max())),
          bounded_uint(configuration_.maximum_daily_loss_paise), "paise", "daily_loss_limit");
    check("drawdown", snapshot.drawdown_paise.value_or(std::numeric_limits<std::uint64_t>::max()) <= configuration_.maximum_drawdown_paise,
          bounded_uint(snapshot.drawdown_paise.value_or(std::numeric_limits<std::uint64_t>::max())), bounded_uint(snapshot.drawdown_paise.value_or(std::numeric_limits<std::uint64_t>::max())),
          bounded_uint(configuration_.maximum_drawdown_paise), "paise", "drawdown_limit");
  }

  decision.decision = rejection ? "rejected" : "approved";
  if (rejection) {
    decision.rejection_code = rejection;
    decision.rejection_reason = rejection;
  }
  std::string seed = intent.semantic_fingerprint() + configuration_.configuration_digest +
                     std::to_string(snapshot.now_ns) + decision.decision;
  for (const auto& rule : decision.rules_checked)
    seed += rule.rule + rule.outcome + std::to_string(rule.before_value) +
            std::to_string(rule.projected_value);
  decision.decision_id = deterministic_uuid(seed);
  return decision;
}

bool risk_approved(const RiskDecision& decision) noexcept { return decision.decision == "approved"; }

}  // namespace shaurya::execution
