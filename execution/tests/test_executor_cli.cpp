#include "shaurya/execution/build_attestation.hpp"
#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/executor.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>

using namespace shaurya::execution;

namespace {
JsonValue integer(std::uint64_t value) { return JsonValue(JsonInteger{std::to_string(value)}); }
JsonObject peer(const std::filesystem::path& root, std::string filename) {
  constexpr std::string_view bytes = "{}";
  return {{"configuration_digest", JsonValue(sha256_hex(bytes))},
          {"configuration_path", JsonValue((root / std::move(filename)).string())},
          {"executable_digest", JsonValue(std::string(64U, 'e'))},
          {"gid", integer(20U)}, {"protocol_version", JsonValue(std::string("1.0.0"))},
          {"uid", integer(10U)}};
}
std::string configuration(const std::filesystem::path& root, std::string mode = "shadow") {
  JsonObject queues;
  for (const auto key : {"broker_submission", "broker_update", "ledger_command", "market_receive",
                         "outbound_event", "risk_work", "strategy_receive"})
    queues.emplace(key, integer(8U));
  const auto path = [&](std::string name) { return JsonValue((root / name).string()); };
  JsonObject document{
      {"configuration_version", JsonValue(std::string("fixture-v1"))},
      {"execution_session_id", JsonValue(std::string("00000000-0000-4000-8000-000000000003"))},
      {"expected_cli_release_digest", JsonValue(std::string(64U, 'a'))},
      {"expected_deployment_manifest_digest", JsonValue(std::string(64U, 'b'))},
      {"expected_executor_build_digest", JsonValue(std::string(64U, 'd'))},
      {"expected_strategy_id", JsonValue(std::string("d51"))},
      {"io_deadline_ms", integer(20U)},
      {"launch_attestation_root", path("attestations")}, {"ledger_path", path("events.ledger")},
      {"market_peer_identity", JsonValue(peer(root, "market-peer.json"))},
      {"market_socket_basename", JsonValue(std::string("market.sock"))},
      {"maximum_launch_attestation_age_ns", integer(100U)},
      {"maximum_packet_bytes", integer(65536U)}, {"mode", JsonValue(std::move(mode))},
      {"paper_model_path", path("paper.json")}, {"queue_capacities", JsonValue(std::move(queues))},
      {"protected_artifact_root", JsonValue(root.string())},
      {"reconnect_window_ms", integer(500U)},
      {"required_initial_observation_freshness_ns", integer(1000000000U)},
      {"risk_configuration_path", path("risk.json")}, {"routing_manifest", path("manifest.json")},
      {"routing_snapshot", path("routing.json")}, {"runtime_directory", JsonValue(root.string())},
      {"schema_version", JsonValue(std::string("1.0.0"))},
      {"shutdown_deadline_ms", integer(500U)},
      {"strategy_peer_identity", JsonValue(peer(root, "strategy-peer.json"))},
      {"strategy_socket_basename", JsonValue(std::string("strategy.sock"))},
      {"trading_date", JsonValue(std::string("2026-08-27"))}};
  const auto configuration_digest = sha256_hex(canonical_json(JsonValue(document)));
  document.emplace("configuration_digest", JsonValue(configuration_digest));
  return canonical_json(JsonValue(std::move(document)));
}
void write_protected(const std::filesystem::path& path, const std::string& bytes) {
  { std::ofstream output(path); output << bytes; }
  (void)::chmod(path.c_str(), 0600);
}
std::string attestation(std::string session = "00000000-0000-4000-8000-000000000003",
                        std::int64_t timestamp = 950) {
  return canonical_json(JsonValue(JsonObject{
      {"cli_release_digest", JsonValue(std::string(64U, 'a'))},
      {"confirmation_type", JsonValue(std::string("SHAURYA_SHADOW_LAUNCH"))},
      {"deployment_manifest_digest", JsonValue(std::string(64U, 'b'))},
      {"device_id", JsonValue(std::string("device-1"))},
      {"execution_session_id", JsonValue(std::move(session))},
      {"executor_build_digest", JsonValue(std::string(64U, 'd'))},
      {"invocation_id", JsonValue(std::string("00000000-0000-4000-8000-000000000004"))},
      {"launch_timestamp_ns", JsonValue(JsonInteger{std::to_string(timestamp)})},
      {"operator_id", JsonValue(std::string("operator-1"))},
      {"public_key_fingerprint", JsonValue(std::string("SHA256:fingerprint"))},
      {"requested_mode", JsonValue(std::string("shadow"))},
      {"schema_version", JsonValue(std::string("1.0.0"))}}));
}
}

int main() {
  int failures = 0;
  const auto expect = [&](bool value, const char* message) {
    if (!value) { std::cerr << message << '\n'; ++failures; }
  };
  std::ostringstream output, error;
  expect(executor_cli({"version"}, output, error) == 0 &&
         output.str() == "shaurya-executor 0.1.0 mode=shadow kotak_live=off commit=" +
                             std::string(kSourceRevision) + " source_state=" +
                             std::string(kSourceState) + " source_tree_sha256=" +
                             std::string(kSourceTreeDigest) + " build_sha256=" +
                             running_executable_digest() + "\n",
         "version does not expose exact opened-executable attestation");
  const auto executable_digest = running_executable_digest();
  expect(executable_digest.size() == 64U &&
             executable_digest.find_first_not_of("0123456789abcdef") == std::string::npos,
         "running executable evidence was not hashed from an opened image");
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"serve", "--mode", "live"}, output, error) != 0 &&
         error.str().find("EXECUTOR_REFUSED") != std::string::npos,
         "live-mode CLI path was not refused");
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"unknown"}, output, error) != 0, "unknown command accepted");
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"validate-config", "--config", "relative.json"}, output, error) != 0,
         "relative protected path accepted");
  char pattern[] = "/private/tmp/shaurya-executor-cli-XXXXXX";
  const char* made = ::mkdtemp(pattern); if (made == nullptr) return 1;
  const std::filesystem::path root(made); (void)::chmod(root.c_str(), 0700);
  write_protected(root / "market-peer.json", "{}");
  write_protected(root / "strategy-peer.json", "{}");
  std::filesystem::create_directory(root / "attestations");
  (void)::chmod((root / "attestations").c_str(), 0700);
  const auto config_path = root / "executor.json";
  write_protected(config_path, configuration(root));
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"validate-config", "--config", config_path.string()}, output, error) == 0,
         "valid exact configuration rejected");
  std::filesystem::create_directory(root / "config-real");
  (void)::chmod((root / "config-real").c_str(), 0700);
  const auto nested_config = root / "config-real" / "executor.json";
  write_protected(nested_config, configuration(root));
  std::filesystem::create_directory_symlink(root / "config-real", root / "config-link");
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"validate-config", "--config",
                       (root / "config-link" / "executor.json").string()}, output, error) != 0,
         "intermediate config ancestor symlink accepted");
  std::filesystem::remove(root / "config-link");
  std::filesystem::create_directory_symlink(root, root / "artifact-root-link");
  write_protected(nested_config, configuration(root / "artifact-root-link"));
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"validate-config", "--config", nested_config.string()}, output, error) != 0,
         "symlinked protected artifact root accepted");
  std::filesystem::remove(root / "artifact-root-link");
  write_protected(nested_config, configuration(root));
  const auto parsed = load_executor_configuration(config_path);
  write_protected(root / "market-peer.json", "{\"changed\":true}");
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"validate-config", "--config", config_path.string()}, output, error) != 0,
         "nested market peer configuration digest mismatch accepted");
  write_protected(root / "market-peer.json", "{}");
  const auto attestation_path = root / "attestations" /
      "00000000-0000-4000-8000-000000000004.json";
  write_protected(attestation_path, attestation());
  const auto evidence = validate_launch_attestation(parsed, attestation_path, 1000);
  expect(evidence.invocation_id == "00000000-0000-4000-8000-000000000004" &&
         evidence.launch_attestation_digest == sha256_hex(attestation()),
         "valid per-invocation attestation rejected");
  const auto displaced_attestations = root / "attestations-displaced";
  std::filesystem::rename(root / "attestations", displaced_attestations);
  std::filesystem::create_directory(root / "attestations");
  (void)::chmod((root / "attestations").c_str(), 0700);
  write_protected(attestation_path,
                  attestation("00000000-0000-4000-8000-000000000099"));
  bool root_swap_refused = false;
  try { (void)validate_launch_attestation(parsed, attestation_path, 1000); }
  catch (const IpcProtocolError&) { root_swap_refused = true; }
  expect(root_swap_refused, "replaced attestation root was followed after configuration load");
  std::filesystem::remove_all(root / "attestations");
  std::filesystem::rename(displaced_attestations, root / "attestations");
  write_protected(attestation_path, attestation("00000000-0000-4000-8000-000000000099"));
  bool wrong_session_refused = false;
  try { (void)validate_launch_attestation(parsed, attestation_path, 1000); }
  catch (const IpcProtocolError&) { wrong_session_refused = true; }
  expect(wrong_session_refused, "cross-session launch attestation accepted");
  write_protected(attestation_path, attestation());
  bool stale_refused = false;
  try { (void)validate_launch_attestation(parsed, attestation_path, 1100); }
  catch (const IpcProtocolError&) { stale_refused = true; }
  expect(stale_refused, "stale launch attestation accepted");
  (void)::chmod(attestation_path.c_str(), 0644);
  bool mode_refused = false;
  try { (void)validate_launch_attestation(parsed, attestation_path, 1000); }
  catch (const IpcProtocolError&) { mode_refused = true; }
  expect(mode_refused, "group-readable launch attestation accepted");
  (void)::chmod(attestation_path.c_str(), 0600);
  write_protected(config_path, configuration(root, "live"));
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"validate-config", "--config", config_path.string()}, output, error) != 0,
         "live configuration accepted");
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"serve", "--config", config_path.string(), "--launch-attestation",
                       attestation_path.string()}, output, error) != 0 &&
         !std::filesystem::exists(root / "market.sock") &&
         !std::filesystem::exists(root / "strategy.sock"),
         "live serve reached socket creation");
  write_protected(config_path, configuration(root));
  { auto ledger = ExecutionLedger::create_new(root / "events.ledger"); (void)ledger; }
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"verify-ledger", "--ledger", (root / "events.ledger").string()},
                      output, error) == 0, "clean ledger rejected");
  output.str({}); error.str({}); output.clear(); error.clear();
  expect(executor_cli({"replay", "--config", config_path.string(), "--ledger",
                       (root / "events.ledger").string()}, output, error) == 0,
         "offline replay rejected");
  std::filesystem::remove_all(root);
  return failures == 0 ? 0 : 1;
}
