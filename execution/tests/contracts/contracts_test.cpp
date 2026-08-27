#include "shaurya/execution/contracts.hpp"

#include <iostream>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

using namespace shaurya::execution;

namespace {
const std::string kPlace =
    R"({"schema_version":"1.0.0","intent_id":"00000000-0000-4000-8000-000000000001","strategy_id":"d51","strategy_run_id":"00000000-0000-4000-8000-000000000002","execution_session_id":"00000000-0000-4000-8000-000000000003","created_at_ns":100,"expires_at_ns":200,"canonical_instrument_id":"NSE:NSE_FNO:NIFTY:future:2026-08-27","action":"place","side":"BUY","quantity":65,"limit_price_paise":2500000,"product":"NRML","time_in_force":"DAY"})";

std::string read_file(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  std::ostringstream output;
  output << input.rdbuf();
  if (!input || output.str().empty()) throw std::runtime_error("fixture read failed");
  return output.str();
}

std::string parse_and_serialize(const std::string& contract, const std::string& payload) {
  if (contract == "order_intent") return OrderIntent::parse(payload).to_json();
  if (contract == "execution_event") return ExecutionEvent::parse(payload).to_json();
  if (contract == "risk_decision") return RiskDecision::parse(payload).to_json();
  if (contract == "position_snapshot") return PositionSnapshot::parse(payload).to_json();
  if (contract == "market_observation") return MarketObservation::parse(payload).to_json();
  throw std::runtime_error("unknown fixture contract");
}

std::string without_final_newline(std::string value) {
  if (!value.empty() && value.back() == '\n') value.pop_back();
  return value;
}
}

int main() {
  int failures = 0;
  const char* stage = "place";
  try {
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
  };
  const auto intent = OrderIntent::parse(kPlace);
  expect(intent.quantity == 65, "quantity");
  expect(OrderIntent::parse(intent.to_json()) == intent, "intent roundtrip");
  const auto changed_id = std::string(kPlace).replace(kPlace.find("000000000001"), 12, "000000000009");
  expect(OrderIntent::parse(changed_id).semantic_fingerprint() == intent.semantic_fingerprint(),
         "fingerprint excludes id");
  for (const auto& invalid : {
           kPlace.substr(0, kPlace.size() - 1) + ",\"unknown\":1}",
           kPlace.substr(0, kPlace.size() - 1) + ",\"quantity\":65}",
           std::string(kPlace).replace(kPlace.find("expires_at_ns\":200") + 15, 3, "050"),
           std::string(kPlace).replace(kPlace.find("00000000-0000-4000"), 1, "A"),
           std::string(kPlace).replace(kPlace.find("\"d51\""), 5, "\"d 1\"")}) {
    try { (void)OrderIntent::parse(invalid); expect(false, "invalid intent accepted"); }
    catch (const JsonError&) {}
  }

  const auto event = ExecutionEvent::parse(
      R"({"schema_version":"1.0.0","event_id":"00000000-0000-4000-8000-000000000011","event_type":"session_started","timestamp_ns":100,"execution_session_id":"00000000-0000-4000-8000-000000000003","payload":{}})");
  expect(ExecutionEvent::parse(event.to_json()) == event, "event roundtrip");
  for (const auto& invalid_event : {
           R"({"schema_version":"1.0.0","event_id":"00000000-0000-4000-8000-000000000011","event_type":"session_started","timestamp_ns":100,"execution_session_id":"00000000-0000-4000-8000-000000000003","intent_id":"00000000-0000-4000-8000-000000000001","payload":{}})",
           R"({"schema_version":"1.0.0","event_id":"00000000-0000-4000-8000-000000000011","event_type":"session_started","timestamp_ns":100,"execution_session_id":"00000000-0000-4000-8000-000000000003","payload":{"raw_http_body":"forbidden"}})"}) {
    try { (void)ExecutionEvent::parse(invalid_event); expect(false, "unsafe event accepted"); }
    catch (const JsonError&) {}
  }

  stage = "risk";
  const auto risk = RiskDecision::parse(
      R"({"schema_version":"1.0.0","decision_id":"00000000-0000-4000-8000-000000000021","intent_id":"00000000-0000-4000-8000-000000000001","decision":"approved","timestamp_ns":100,"rule_set_version":"risk-v1","configuration_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","rules_checked":[{"rule":"mapping","outcome":"pass","before_value":0,"projected_value":65,"limit_value":130,"unit":"units"}],"mapping_age_ns":1,"market_age_ns":2,"session_state":"ready"})");
  expect(RiskDecision::parse(risk.to_json()) == risk, "risk roundtrip");
  try {
    auto invalid_risk = risk.to_json();
    invalid_risk.replace(invalid_risk.find("\"ready\""), 7, "\"unknown\"");
    (void)RiskDecision::parse(invalid_risk);
    expect(false, "unknown risk session state accepted");
  } catch (const JsonError&) {}

  stage = "positions";
  const auto positions = PositionSnapshot::parse(
      R"({"schema_version":"1.0.0","snapshot_id":"00000000-0000-4000-8000-000000000031","execution_session_id":"00000000-0000-4000-8000-000000000003","timestamp_ns":100,"source":"paper","provenance":"simulated","reconciliation_status":"matched","positions":[{"canonical_instrument_id":"NSE:NSE_FNO:NIFTY:future:2026-08-27","instrument_token":"58072","strategy_desired":65,"ledger_reconstructed":65,"broker_authoritative":65}]})");
  expect(PositionSnapshot::parse(positions.to_json()) == positions, "position roundtrip");
  try {
    auto invalid_positions = positions.to_json();
    invalid_positions.replace(invalid_positions.find("\"matched\""), 9, "\"assumed\"");
    (void)PositionSnapshot::parse(invalid_positions);
    expect(false, "unknown reconciliation status accepted");
  } catch (const JsonError&) {}

  stage = "observation";
  const auto observation = MarketObservation::parse(
      R"({"schema_version":"1.0.0","canonical_instrument_id":"NSE:NSE_FNO:NIFTY:future:2026-08-27","best_bid_paise":2500000,"best_ask_paise":2500010,"last_trade_paise":2500005,"cumulative_volume":1000,"exchange_timestamp_ns":90,"receive_timestamp_ns":100,"source":"dhan","provenance":"observed","quality_flags":[]})");
  expect(MarketObservation::parse(observation.to_json()) == observation, "observation roundtrip");
  try {
    auto invalid_observation = observation.to_json();
    invalid_observation.replace(invalid_observation.find("\"dhan\""), 6, "\"kotak\"");
    (void)MarketObservation::parse(invalid_observation);
    expect(false, "non-Dhan observation source accepted");
  } catch (const JsonError&) {}

  stage = "schema documents";
  const auto contract_root = std::filesystem::path(SHAURYA_EXECUTION_SOURCE_ROOT) / "contracts/v1";
  for (const auto* schema : {"execution_event.schema.json", "market_observation.schema.json",
                             "order_intent.schema.json", "position_snapshot.schema.json",
                             "risk_decision.schema.json"}) {
    const auto document = parse_json(read_file(contract_root / schema));
    expect(json_object(document, schema).contains("$schema"), "malformed schema document");
  }

  stage = "fixture corpus";
  const auto fixture_root = std::filesystem::path(SHAURYA_EXECUTION_SOURCE_ROOT) /
                            "contracts/fixtures/v1";
  const auto manifest_document = parse_json(read_file(fixture_root / "manifest.json"));
  const auto& manifest = json_object(manifest_document, "manifest");
  expect(json_string(manifest.at("schema_version"), "schema_version") == "1.0.0",
         "fixture manifest version");
  for (const auto& fixture_value : json_array(manifest.at("fixtures"), "fixtures")) {
    const auto& fixture = json_object(fixture_value, "fixture");
    const auto path = json_string(fixture.at("path"), "path");
    const auto contract = json_string(fixture.at("contract"), "contract");
    const auto expected = json_string(fixture.at("expect"), "expect");
    const auto payload = read_file(fixture_root / path);
    if (expected == "valid") {
      const auto encoded = parse_and_serialize(contract, payload);
      expect(parse_and_serialize(contract, encoded) == encoded, "fixture roundtrip");
      if (const auto golden = fixture.find("golden"); golden != fixture.end()) {
        expect(encoded == without_final_newline(read_file(
                              fixture_root / json_string(golden->second, "golden"))),
               "golden fixture mismatch");
      }
    } else {
      try {
        (void)parse_and_serialize(contract, payload);
        expect(false, "invalid fixture accepted");
      } catch (const JsonError& error) {
        expect(error.code() == json_string(fixture.at("error"), "error"),
               "invalid fixture error mismatch");
      }
    }
  }
  } catch (const JsonError& error) {
    std::cerr << stage << ": " << error.code() << '\n';
    return 2;
  }
  return failures == 0 ? 0 : 1;
}
