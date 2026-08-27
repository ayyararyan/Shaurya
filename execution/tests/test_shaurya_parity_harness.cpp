#include "shaurya/execution/canonical_json.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <filesystem>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

using namespace shaurya::execution;

namespace {

struct ProcessResult { int status{}; std::string output; std::string error; };

std::string read_file(const std::filesystem::path& path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) throw std::runtime_error("test_read_failed");
  return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

void write_file(const std::filesystem::path& path, std::string_view bytes, mode_t mode = 0600) {
  const int descriptor = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, mode);
  if (descriptor < 0) throw std::runtime_error("test_write_failed");
  std::size_t offset = 0U;
  while (offset < bytes.size()) {
    const auto count = ::write(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) { (void)::close(descriptor); throw std::runtime_error("test_write_failed"); }
    offset += static_cast<std::size_t>(count);
  }
  if (::close(descriptor) != 0) throw std::runtime_error("test_write_failed");
}

std::string read_descriptor(int descriptor) {
  std::string result;
  std::array<char, 4096> buffer{};
  for (;;) {
    const auto count = ::read(descriptor, buffer.data(), buffer.size());
    if (count < 0 && errno == EINTR) continue;
    if (count < 0) throw std::runtime_error("test_pipe_read_failed");
    if (count == 0) break;
    result.append(buffer.data(), static_cast<std::size_t>(count));
  }
  return result;
}

ProcessResult execute(const std::filesystem::path& program,
                      const std::vector<std::string>& arguments) {
  int output_pipe[2]{};
  int error_pipe[2]{};
  if (::pipe(output_pipe) != 0 || ::pipe(error_pipe) != 0)
    throw std::runtime_error("test_pipe_failed");
  const pid_t process = ::fork();
  if (process < 0) throw std::runtime_error("test_fork_failed");
  if (process == 0) {
    (void)::close(output_pipe[0]);
    (void)::close(error_pipe[0]);
    if (::dup2(output_pipe[1], STDOUT_FILENO) < 0 ||
        ::dup2(error_pipe[1], STDERR_FILENO) < 0) _exit(126);
    (void)::close(output_pipe[1]);
    (void)::close(error_pipe[1]);
    std::vector<std::string> storage;
    storage.reserve(arguments.size() + 1U);
    storage.push_back(program.string());
    storage.insert(storage.end(), arguments.begin(), arguments.end());
    std::vector<char*> values;
    values.reserve(storage.size() + 1U);
    for (auto& value : storage) values.push_back(value.data());
    values.push_back(nullptr);
    ::execv(program.c_str(), values.data());
    _exit(127);
  }
  (void)::close(output_pipe[1]);
  (void)::close(error_pipe[1]);
  int status{};
  while (::waitpid(process, &status, 0) < 0) {
    if (errno != EINTR) throw std::runtime_error("test_wait_failed");
  }
  const auto output = read_descriptor(output_pipe[0]);
  const auto error = read_descriptor(error_pipe[0]);
  (void)::close(output_pipe[0]);
  (void)::close(error_pipe[0]);
  return {WIFEXITED(status) ? WEXITSTATUS(status) : 255, output, error};
}

bool lower_hex(std::string_view value, std::size_t expected) {
  return value.size() == expected && std::all_of(value.begin(), value.end(), [](char item) {
    return (item >= '0' && item <= '9') || (item >= 'a' && item <= 'f');
  });
}

const JsonValue& field(const JsonObject& object, std::string_view name) {
  const auto found = object.find(name);
  if (found == object.end()) throw std::runtime_error("test_missing_field");
  return found->second;
}

std::filesystem::path temporary_directory() {
  const char* base = std::getenv("TMPDIR");
  const std::filesystem::path parent = base && *base ? base : "/private/tmp";
  auto pattern = (parent / "shaurya-parity-test-XXXXXX").string();
  if (::mkdtemp(pattern.data()) == nullptr) throw std::runtime_error("test_mkdtemp_failed");
  return std::filesystem::canonical(pattern);
}

JsonObject mutable_fixture(const std::filesystem::path& path) {
  return json_object(parse_json(read_file(path)), "fixture");
}

std::filesystem::path write_manifested_fixture(const std::filesystem::path& root,
                                                std::string_view directory_name,
                                                std::string_view bytes) {
  const auto directory = root / directory_name;
  if (::mkdir(directory.c_str(), 0700) != 0) throw std::runtime_error("test_mkdir_failed");
  const auto fixture = directory / "scenario.json";
  write_file(fixture, bytes);
  write_file(directory / "MANIFEST.sha256",
             sha256_hex(bytes) + "  scenario.json\n");
  return fixture;
}

}  // namespace

int main(int argc, char** argv) {
  int failures = 0;
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
  };
  try {
    if (argc != 4) throw std::runtime_error("usage: test HARNESS FIXTURE_ROOT CLIENT_CONTRACT");
    const std::filesystem::path harness = argv[1];
    const std::filesystem::path fixtures = argv[2];
    const std::filesystem::path client_contract = argv[3];
    expect(harness.is_absolute(), "harness path is absolute");
    const auto root = temporary_directory();
    struct Cleanup {
      std::filesystem::path root;
      ~Cleanup() { std::error_code error; std::filesystem::remove_all(root, error); }
    } cleanup{root};

    const auto version = execute(harness, {"version"});
    expect(version.status == 0 && version.error.empty(), "version succeeds without stderr");
    expect(!version.output.empty() && version.output.back() == '\n', "version ends once with newline");
    const auto version_bytes = version.output.substr(0, version.output.size() - 1U);
    const auto version_document = parse_json(version_bytes);
    expect(canonical_json(version_document) == version_bytes, "version is canonical JSON");
    const auto& version_object = json_object(version_document, "version");
    expect(version_object.size() == 8U, "version has exact closed shape");
    expect(json_string(field(version_object, "executable"), "executable") ==
               "shaurya-parity-harness", "version executable binding");
    expect(json_string(field(version_object, "protocol_version"), "protocol_version") == "1.0.0" &&
               json_string(field(version_object, "schema_version"), "schema_version") == "1.0.0",
           "version protocol/schema binding");
    expect(lower_hex(json_string(field(version_object, "source_commit"), "source_commit"), 40U),
           "version source commit attested");
    expect(lower_hex(json_string(field(version_object, "build_sha256"), "build_sha256"), 64U) &&
               lower_hex(json_string(field(version_object, "contract_schema_sha256"),
                                     "contract_schema_sha256"), 64U) &&
               lower_hex(json_string(field(version_object, "client_contract_sha256"),
                                     "client_contract_sha256"), 64U),
           "version build/schema/client digests attested");
    const auto& models = json_array(field(version_object, "model_versions"), "model_versions");
    expect(models.size() == 2U && json_string(models[0], "model") == "d51_proxy_v1" &&
               json_string(models[1], "model") == "scripted_v1", "version models exact");
    const auto client_contract_bytes = read_file(client_contract);
    expect(!client_contract_bytes.empty() && client_contract_bytes.back() == '\n',
           "client contract has one line terminator");
    const auto client_contract_document = parse_json(client_contract_bytes);
    expect(canonical_json(client_contract_document) + "\n" == client_contract_bytes,
           "client contract is canonical JSON");
    expect(sha256_hex(client_contract_bytes) ==
               json_string(field(version_object, "client_contract_sha256"),
                           "client_contract_sha256"),
           "version binds exact aggregate client contract bytes");
    const auto& client_contract_object = json_object(client_contract_document, "client_contract");
    expect(client_contract_object.size() == 7U &&
               json_string(field(client_contract_object, "contract_version"),
                           "contract_version") == "1.0.0" &&
               client_contract_object.contains("harness_result_contract") &&
               client_contract_object.contains("harness_step_contract") &&
               client_contract_object.contains("paper_broker_models") &&
               client_contract_object.contains("risk_configuration_contract") &&
               client_contract_object.contains("strategy_book_contract"),
           "aggregate client contract has every required semantic domain");
    const auto& artifacts = json_object(field(client_contract_object, "artifacts"), "artifacts");
    const auto execution_root =
        client_contract.parent_path().parent_path().parent_path();
    for (const auto& [name, artifact_value] : artifacts) {
      (void)name;
      const auto& artifact = json_object(artifact_value, "artifact");
      const auto artifact_path = execution_root /
          json_string(field(artifact, "path"), "path");
      expect(sha256_hex(read_file(artifact_path)) ==
                 json_string(field(artifact, "sha256"), "sha256"),
             "aggregate client contract artifact digest matches source");
    }

    const auto extra_version = execute(harness, {"version", "extra"});
    expect(extra_version.status == 2 && extra_version.output.empty(),
           "version rejects extra arguments");
    if (::setenv("SHAURYA_SOURCE_REVISION", std::string(40U, '0').c_str(), 1) != 0 ||
        ::setenv("SHAURYA_PARITY_CLIENT_CONTRACT_DIGEST", std::string(64U, '0').c_str(), 1) != 0)
      throw std::runtime_error("test_setenv_failed");
    const auto environment_spoof = execute(harness, {"version"});
    (void)::unsetenv("SHAURYA_SOURCE_REVISION");
    (void)::unsetenv("SHAURYA_PARITY_CLIENT_CONTRACT_DIGEST");
    expect(environment_spoof.status == 0 && environment_spoof.output == version.output,
           "version identity ignores mutable environment spoofing");

    const auto copied_harness = root / "copied-harness";
    std::filesystem::copy_file(harness, copied_harness,
                               std::filesystem::copy_options::none);
    if (::chmod(copied_harness.c_str(), 0700) != 0)
      throw std::runtime_error("test_chmod_failed");
    const int copied_descriptor = ::open(copied_harness.c_str(), O_WRONLY | O_APPEND | O_CLOEXEC);
    const char appended = '\0';
    if (copied_descriptor < 0 || ::write(copied_descriptor, &appended, 1U) != 1 ||
        ::close(copied_descriptor) != 0)
      throw std::runtime_error("test_copy_mutation_failed");
    const auto copied_version = execute(copied_harness, {"version"});
    expect(copied_version.status == 0 && copied_version.error.empty(),
           "copied executable remains locally attestable");
    if (copied_version.status == 0) {
      const auto copied_bytes = copied_version.output.substr(0U, copied_version.output.size() - 1U);
      const auto copied_document = parse_json(copied_bytes);
      const auto& copied_object = json_object(copied_document, "copied_version");
      expect(json_string(field(copied_object, "build_sha256"), "build_sha256") ==
                 sha256_hex(read_file(copied_harness)) &&
                 json_string(field(copied_object, "build_sha256"), "build_sha256") !=
                 json_string(field(version_object, "build_sha256"), "build_sha256") &&
                 json_string(field(copied_object, "source_commit"), "source_commit") ==
                 json_string(field(version_object, "source_commit"), "source_commit"),
             "version hashes the currently opened executable and preserves compiled source identity");
    }

    const auto run_fixture = [&](std::string_view fixture_name, std::string_view output_name) {
      const auto fixture = fixtures / fixture_name;
      const auto output = root / output_name;
      const auto process = execute(harness, {"run", "--fixture", fixture.string(),
                                             "--output", output.string()});
      expect(process.status == 0 && process.error.empty(), "valid scenario succeeds");
      expect(process.output.starts_with("[SHAURYA_PARITY_OK] fixture_sha256=") &&
                 process.output.size() == 100U && process.output.back() == '\n',
             "success marker exact and bounded");
      struct stat metadata{};
      expect(::lstat(output.c_str(), &metadata) == 0 && S_ISREG(metadata.st_mode) &&
                 (metadata.st_mode & 07777U) == 0600U, "result is new protected regular file");
      const auto bytes = read_file(output);
      expect(!bytes.empty() && bytes.back() == '\n', "result ends once with newline");
      const auto canonical = bytes.substr(0, bytes.size() - 1U);
      const auto document = parse_json(canonical);
      expect(canonical_json(document) == canonical, "result is canonical JSON");
      const auto& result = json_object(document, "parity_result");
      expect(result.size() == 16U &&
                 json_string(field(result, "client_contract_sha256"),
                             "client_contract_sha256") ==
                     json_string(field(version_object, "client_contract_sha256"),
                                 "client_contract_sha256") &&
                 json_string(field(result, "contract_schema_sha256"),
                             "contract_schema_sha256") ==
                     json_string(field(version_object, "contract_schema_sha256"),
                                 "contract_schema_sha256"),
             "result has exact shape and compiled contract bindings");
      std::uint64_t prior_incident_sequence = 0U;
      for (const auto& value : json_array(field(result, "incidents"), "incidents")) {
        const auto& incident = json_object(value, "incident");
        const auto sequence = json_uint64(field(incident, "event_sequence"), "event_sequence");
        const auto severity = json_string(field(incident, "severity"), "severity");
        expect(incident.size() == 5U && sequence > prior_incident_sequence &&
                   (severity == "critical" || severity == "warning"),
               "typed incidents retain strict authoritative order");
        prior_incident_sequence = sequence;
      }
      for (const auto& value : json_array(field(result, "inventory"), "inventory")) {
        const auto& inventory = json_object(value, "inventory");
        const auto boundary = json_string(field(inventory, "boundary"), "boundary");
        expect(inventory.size() == 5U &&
                   (boundary == "step" || boundary == "scripted_update"),
               "inventory boundary has exact typed shape");
      }
      return std::pair{output, document};
    };
    const auto result_object = [](const JsonValue& document) -> const JsonObject& {
      return json_object(document, "parity_result");
    };
    const auto incident_code_present = [&](const JsonObject& result, std::string_view code) {
      const auto& incidents = json_array(field(result, "incidents"), "incidents");
      return std::any_of(incidents.begin(), incidents.end(), [&](const auto& value) {
        const auto& incident = json_object(value, "incident");
        return json_string(field(incident, "code"), "code") == code;
      });
    };
    const auto exact_terminal_safety_state = [&](const JsonObject& result) {
      const auto& final_state = json_object(field(result, "final_state"), "final_state");
      return std::get<bool>(field(final_state, "safety_stopped").value) &&
             !std::get<bool>(field(final_state, "session_ready").value);
    };

    const auto [d51_output, d51_document] = run_fixture("d51_full_fill.json", "d51-one.json");
    const auto& d51 = json_object(d51_document, "d51_result");
    expect(d51.size() == 16U, "result has exact closed shape");
    const auto& d51_fills = json_array(field(d51, "fills"), "fills");
    expect(d51_fills.size() == 1U, "D51 proxy emits one complete fill");
    if (d51_fills.size() == 1U) {
      const auto& fill = json_object(d51_fills.front(), "fill");
      expect(json_uint64(field(fill, "last_fill_quantity"), "last_fill_quantity") == 65U &&
                 json_uint64(field(fill, "cumulative_filled_quantity"),
                             "cumulative_filled_quantity") == 65U,
             "D51 qualifying cross fills entire remainder");
    }
    const auto& d51_final = json_object(field(d51, "final_state"), "final_state");
    const auto& d51_positions = json_array(field(d51_final, "positions"), "positions");
    expect(d51_positions.size() == 1U &&
               json_int64(field(json_object(d51_positions[0], "position"), "quantity"),
                          "quantity") == 65,
           "D51 exact-token inventory is 65");
    const auto [d51_repeat_output, d51_repeat_document] =
        run_fixture("d51_full_fill.json", "d51-two.json");
    (void)d51_repeat_document;
    expect(read_file(d51_output) == read_file(d51_repeat_output),
           "same fixture produces byte-identical result");

    const auto [restart_output, restart_document] =
        run_fixture("restart_reconcile.json", "restart.json");
    (void)restart_output;
    const auto& restart = json_object(restart_document, "restart_result");
    const auto& restart_inventory = json_array(field(restart, "inventory"), "inventory");
    expect(restart_inventory.size() == 5U, "restart scenario records every state boundary");
    if (restart_inventory.size() == 5U) {
      expect(json_array(field(json_object(restart_inventory[3], "inventory"), "positions"),
                        "positions").empty(),
             "first post-restart observation establishes baseline without fill");
      const auto& final_positions = json_array(
          field(json_object(restart_inventory[4], "inventory"), "positions"), "positions");
      expect(final_positions.size() == 1U &&
                 json_int64(field(json_object(final_positions[0], "position"), "quantity"),
                            "quantity") == 65,
             "later volume advance completes restored order");
    }

    const auto [scripted_output, scripted_document] =
        run_fixture("scripted_partial_fill.json", "scripted.json");
    (void)scripted_output;
    const auto& scripted = json_object(scripted_document, "scripted_result");
    const auto& scripted_fills = json_array(field(scripted, "fills"), "fills");
    expect(scripted_fills.size() == 2U, "scripted lifecycle preserves partial then complete fill");
    if (scripted_fills.size() == 2U) {
      const auto& partial = json_object(scripted_fills[0], "partial");
      const auto& complete = json_object(scripted_fills[1], "complete");
      expect(json_uint64(field(partial, "cumulative_filled_quantity"), "cumulative") == 20U &&
                 json_uint64(field(partial, "last_fill_quantity"), "delta") == 20U &&
                 json_uint64(field(complete, "cumulative_filled_quantity"), "cumulative") == 65U &&
                 json_uint64(field(complete, "last_fill_quantity"), "delta") == 45U,
             "scripted cumulative and delta fills exact");
    }
    const auto& scripted_inventory = json_array(field(scripted, "inventory"), "inventory");
    expect(scripted_inventory.size() == 6U, "scripted restart records every state boundary");
    if (scripted_inventory.size() == 6U) {
      const auto quantity_at = [&](std::size_t index) {
        const auto& positions = json_array(
            field(json_object(scripted_inventory[index], "inventory"), "positions"),
            "positions");
        return positions.size() == 1U
            ? json_int64(field(json_object(positions[0], "position"), "quantity"), "quantity")
            : std::int64_t{};
      };
      expect(quantity_at(2U) == 20 && quantity_at(3U) == 20 && quantity_at(4U) == 20 &&
                 quantity_at(5U) == 65,
             "scripted partial inventory and P&L state survive restart exactly");
    }
    const auto& scripted_final = json_object(field(scripted, "final_state"), "final_state");
    expect(std::get<bool>(field(scripted_final, "pnl_authoritative").value),
           "scripted final P&L remains authoritative after restart");

    const auto [no_quote_output, no_quote_document] =
        run_fixture("no_eligible_quote.json", "no-quote.json");
    (void)no_quote_output;
    const auto& no_quote = result_object(no_quote_document);
    expect(json_array(field(no_quote, "actions"), "actions").empty() &&
               json_array(field(no_quote, "fills"), "fills").empty() &&
               json_array(field(json_object(field(no_quote, "final_state"), "final"),
                                "orders"), "orders").empty(),
           "no-eligible-quote scenario creates no order or fill");

    const auto [ack_output, ack_document] =
        run_fixture("place_ack_no_fill.json", "ack-no-fill.json");
    (void)ack_output;
    const auto& ack = result_object(ack_document);
    const auto& ack_actions = json_array(field(ack, "actions"), "actions");
    const auto& ack_final = json_object(field(ack, "final_state"), "final");
    const auto& ack_orders = json_array(field(ack_final, "orders"), "orders");
    expect(ack_actions.size() == 1U &&
               json_string(field(json_object(ack_actions[0], "action"), "broker_status"),
                           "broker_status") == "acknowledged" &&
               json_array(field(ack, "fills"), "fills").empty() && ack_orders.size() == 1U &&
               json_string(field(json_object(ack_orders[0], "order"), "state"), "state") ==
                   "working",
           "place acknowledgement remains working without qualifying evidence");

    const auto [idempotent_output, idempotent_document] =
        run_fixture("idempotent_fill_replay.json", "idempotent.json");
    (void)idempotent_output;
    const auto& idempotent = result_object(idempotent_document);
    const auto& idempotent_fills = json_array(field(idempotent, "fills"), "fills");
    const auto& idempotent_inventory = json_array(field(idempotent, "inventory"), "inventory");
    expect(idempotent_fills.size() == 2U && idempotent_inventory.size() == 6U,
           "duplicate and out-of-order updates add no extra fills or boundaries");
    if (idempotent_fills.size() == 2U && idempotent_inventory.size() == 6U) {
      const auto quantity_at = [&](std::size_t index) {
        const auto& positions = json_array(
            field(json_object(idempotent_inventory[index], "inventory"), "positions"),
            "positions");
        return positions.size() == 1U
            ? json_int64(field(json_object(positions[0], "position"), "quantity"), "quantity")
            : std::int64_t{};
      };
      expect(quantity_at(2U) == 20 && quantity_at(3U) == 20 && quantity_at(4U) == 20 &&
                 quantity_at(5U) == 65 &&
                 json_int64(field(json_object(idempotent_inventory[2], "inventory"),
                                  "timestamp_ns"), "timestamp") == 960 &&
                 json_int64(field(json_object(idempotent_inventory[3], "inventory"),
                                  "timestamp_ns"), "timestamp") == 960 &&
                 json_int64(field(json_object(idempotent_inventory[4], "inventory"),
                                  "timestamp_ns"), "timestamp") == 970 &&
                 json_int64(field(json_object(idempotent_inventory[5], "inventory"),
                                  "timestamp_ns"), "timestamp") == 980 &&
                 json_int64(field(json_object(idempotent_fills[0], "fill"),
                                  "evidence_timestamp_ns"), "timestamp") == 960 &&
                 json_int64(field(json_object(idempotent_fills[1], "fill"),
                                  "evidence_timestamp_ns"), "timestamp") == 980,
             "scripted updates preserve individual timestamps and inventory after every update");
    }

    const auto [replacement_output, replacement_document] =
        run_fixture("quote_replacement.json", "replacement.json");
    (void)replacement_output;
    const auto& replacement = result_object(replacement_document);
    const auto& replacement_actions = json_array(field(replacement, "actions"), "actions");
    const auto& replacement_orders = json_array(
        field(json_object(field(replacement, "final_state"), "final"), "orders"), "orders");
    expect(replacement_actions.size() == 2U && replacement_orders.size() == 1U &&
               json_string(field(json_object(replacement_actions[1], "action"), "action"),
                           "action") == "modify" &&
               json_uint64(field(json_object(replacement_orders[0], "order"),
                                 "limit_price_paise"), "price") == 995U,
           "same-instrument quote replacement is an exact modify");

    const auto [cancel_output, cancel_document] =
        run_fixture("cancellation_race.json", "cancel-race.json");
    (void)cancel_output;
    const auto& cancel = result_object(cancel_document);
    const auto& cancel_actions = json_array(field(cancel, "actions"), "actions");
    const auto& cancel_fills = json_array(field(cancel, "fills"), "fills");
    expect(cancel_actions.size() == 4U && cancel_fills.size() == 1U &&
               json_uint64(field(json_object(cancel_fills[0], "fill"),
                                 "cumulative_filled_quantity"), "cumulative") == 20U,
           "cancel-before-fill and partial-fill race remain distinct factual actions");

    const auto [token_output, token_document] =
        run_fixture("token_change_cancel_place.json", "token-change.json");
    (void)token_output;
    const auto& token = result_object(token_document);
    const auto& token_actions = json_array(field(token, "actions"), "actions");
    const auto& token_orders = json_array(
        field(json_object(field(token, "final_state"), "final"), "orders"), "orders");
    expect(token_actions.size() == 3U && token_orders.size() == 2U &&
               json_string(field(json_object(token_actions[1], "action"), "action"), "action") ==
                   "cancel" &&
               json_string(field(json_object(token_actions[2], "action"), "action"), "action") ==
                   "place",
           "token change cancels old order and places a distinct new order");

    const auto [unauthorized_output, unauthorized_document] =
        run_fixture("unauthorized_sell.json", "unauthorized-sell.json");
    (void)unauthorized_output;
    const auto& unauthorized = result_object(unauthorized_document);
    const auto& unauthorized_actions = json_array(field(unauthorized, "actions"), "actions");
    expect(unauthorized_actions.size() == 2U &&
               json_string(field(json_object(unauthorized_actions[1], "action"), "decision"),
                           "decision") == "rejected" &&
               incident_code_present(unauthorized, "token_inventory_unavailable"),
           "exact-token inventory rejects a sell of a different instrument");

    const auto [authorized_output, authorized_document] =
        run_fixture("authorized_sell.json", "authorized-sell.json");
    (void)authorized_output;
    const auto& authorized = result_object(authorized_document);
    const auto& authorized_actions = json_array(field(authorized, "actions"), "actions");
    const auto& authorized_positions = json_array(
        field(json_object(field(authorized, "final_state"), "final"), "positions"), "positions");
    expect(authorized_actions.size() == 2U && authorized_positions.size() == 1U &&
               json_int64(field(json_object(authorized_positions[0], "position"), "quantity"),
                          "quantity") == 0,
           "authorized matching-token sell returns inventory to zero");

    const auto [reject_output, reject_document] =
        run_fixture("broker_reject.json", "broker-reject.json");
    (void)reject_output;
    const auto& reject = result_object(reject_document);
    expect(std::get<bool>(field(json_object(field(reject, "final_state"), "final"),
                                "safety_stopped").value) &&
               incident_code_present(reject, "FSM_CONTRADICTORY_REJECTION"),
           "late contradictory broker rejection is reported factually as a safety incident");

    const auto [ambiguous_output, ambiguous_document] =
        run_fixture("ambiguous_submission.json", "ambiguous.json");
    (void)ambiguous_output;
    const auto& ambiguous = result_object(ambiguous_document);
    expect(std::get<bool>(field(json_object(field(ambiguous, "final_state"), "final"),
                                "safety_stopped").value) &&
               json_string(field(json_object(field(ambiguous, "final_state"), "final"),
                                 "broker_health"), "broker_health") == "unknown" &&
               incident_code_present(ambiguous, "FSM_ILLEGAL_TRANSITION"),
           "late ambiguous broker update succeeds with factual unknown-health safety incident");

    const auto [loss_output, loss_document] =
        run_fixture("broker_session_loss.json", "broker-session-loss.json");
    (void)loss_output;
    const auto& loss = result_object(loss_document);
    expect(exact_terminal_safety_state(loss) &&
               json_string(field(json_object(field(loss, "final_state"), "final"), "broker_health"),
                           "broker_health") == "lost" &&
               incident_code_present(loss, "broker_session_lost"),
           "broker session loss ends not-ready and safety-stopped with factual lost state");

    const auto [ipc_output, ipc_document] = run_fixture("ipc_loss.json", "ipc-loss.json");
    (void)ipc_output;
    const auto& ipc = result_object(ipc_document);
    expect(exact_terminal_safety_state(ipc) &&
               incident_code_present(ipc, "market_peer_disconnected"),
           "IPC loss ends not-ready and safety-stopped with typed peer-disconnect incident");

    const auto [stop_output, stop_document] =
        run_fixture("explicit_safety_stop.json", "explicit-stop.json");
    (void)stop_output;
    const auto& explicit_stop = result_object(stop_document);
    expect(exact_terminal_safety_state(explicit_stop) &&
               incident_code_present(explicit_stop, "operator_fixture_stop"),
           "explicit stop ends not-ready and safety-stopped with typed reason");

    const auto [cutoff_output, cutoff_document] =
        run_fixture("market_session_cutoff.json", "market-cutoff.json");
    (void)cutoff_output;
    const auto& cutoff = result_object(cutoff_document);
    expect(exact_terminal_safety_state(cutoff) &&
               incident_code_present(cutoff, "market_session_cutoff"),
           "derived market/session cutoff ends not-ready and safety-stopped");

    const auto refuse_case = [&](const std::vector<std::string>& arguments, const char* message) {
      const auto process = execute(harness, arguments);
      expect(process.status == 2 && process.output.empty() &&
                 process.error.starts_with("[SHAURYA_PARITY_REFUSED] code=") &&
                 process.error.ends_with("\n"), message);
    };
    refuse_case({"run", "--fixture", "relative.json", "--output", (root / "relative-out").string()},
                "relative fixture refused");
    refuse_case({"run", "--fixture", (fixtures / "d51_full_fill.json").string(),
                 "--output", "relative.json"}, "relative output refused");
    refuse_case({"run", "--fixture", (fixtures / "missing.json").string(),
                 "--output", (root / "missing-out").string()}, "missing fixture refused");
    refuse_case({"run", "--fixture", (fixtures / "d51_full_fill.json").string(),
                 "--output", d51_output.string()}, "output overwrite refused");

    const auto source_fixture = fixtures / "d51_full_fill.json";
    auto unknown = mutable_fixture(source_fixture);
    unknown.emplace("unknown", JsonValue(true));
    const auto unknown_path = write_manifested_fixture(root, "unknown",
        canonical_json(JsonValue(std::move(unknown))) + "\n");
    refuse_case({"run", "--fixture", unknown_path.string(), "--output",
                 (root / "unknown-out").string()}, "unknown field refused");

    auto live = mutable_fixture(source_fixture);
    live["mode"] = JsonValue(std::string("live"));
    const auto live_path = write_manifested_fixture(root, "live",
        canonical_json(JsonValue(std::move(live))) + "\n");
    refuse_case({"run", "--fixture", live_path.string(), "--output",
                 (root / "live-out").string()}, "live mode refused");

    auto wrong_version = mutable_fixture(source_fixture);
    wrong_version["schema_version"] = JsonValue(std::string("2.0.0"));
    const auto wrong_version_path = write_manifested_fixture(root, "wrong-version",
        canonical_json(JsonValue(std::move(wrong_version))) + "\n");
    refuse_case({"run", "--fixture", wrong_version_path.string(), "--output",
                 (root / "wrong-version-out").string()}, "wrong version refused");

    auto supplied_cutoff_reason = mutable_fixture(fixtures / "market_session_cutoff.json");
    auto& cutoff_steps = std::get<JsonArray>(supplied_cutoff_reason.at("steps").value);
    std::get<JsonObject>(cutoff_steps.back().value)
        .emplace("reason", JsonValue(std::string("fixture_controlled_reason")));
    const auto supplied_cutoff_reason_path = write_manifested_fixture(root, "cutoff-reason",
        canonical_json(JsonValue(std::move(supplied_cutoff_reason))) + "\n");
    refuse_case({"run", "--fixture", supplied_cutoff_reason_path.string(), "--output",
                 (root / "cutoff-reason-out").string()},
                "market/session cutoff reason cannot be fixture supplied");

    const auto noncanonical_path = write_manifested_fixture(root, "noncanonical",
        read_file(source_fixture) + "\n");
    refuse_case({"run", "--fixture", noncanonical_path.string(), "--output",
                 (root / "noncanonical-out").string()}, "noncanonical fixture refused");

    const auto writable_path = root / "writable.json";
    write_file(writable_path, read_file(source_fixture), 0660);
    refuse_case({"run", "--fixture", writable_path.string(), "--output",
                 (root / "writable-out").string()}, "group-writable fixture refused");

    const auto symlink_path = root / "fixture-link.json";
    if (::symlink(source_fixture.c_str(), symlink_path.c_str()) != 0)
      throw std::runtime_error("test_symlink_failed");
    refuse_case({"run", "--fixture", symlink_path.string(), "--output",
                 (root / "symlink-out").string()}, "symlink fixture refused");
    const auto fixture_directory_link = root / "fixture-directory-link";
    if (::symlink(fixtures.c_str(), fixture_directory_link.c_str()) != 0)
      throw std::runtime_error("test_symlink_failed");
    refuse_case({"run", "--fixture", (fixture_directory_link / "d51_full_fill.json").string(),
                 "--output", (root / "fixture-ancestor-symlink-out").string()},
                "fixture intermediate-ancestor symlink refused");
    const auto real_output_directory = root / "real-output-directory";
    if (::mkdir(real_output_directory.c_str(), 0700) != 0)
      throw std::runtime_error("test_mkdir_failed");
    const auto output_directory_link = root / "output-directory-link";
    if (::symlink(real_output_directory.c_str(), output_directory_link.c_str()) != 0)
      throw std::runtime_error("test_symlink_failed");
    refuse_case({"run", "--fixture", source_fixture.string(), "--output",
                 (output_directory_link / "result.json").string()},
                "output intermediate-ancestor symlink refused");

    const auto bad_manifest_root = root / "bad-manifest";
    if (::mkdir(bad_manifest_root.c_str(), 0700) != 0)
      throw std::runtime_error("test_mkdir_failed");
    const auto bad_manifest_fixture = bad_manifest_root / "scenario.json";
    write_file(bad_manifest_fixture, read_file(source_fixture));
    write_file(bad_manifest_root / "MANIFEST.sha256",
               std::string(64U, '0') + "  scenario.json\n");
    refuse_case({"run", "--fixture", bad_manifest_fixture.string(), "--output",
                 (root / "bad-manifest-out").string()}, "manifest digest mismatch refused");

    bool hidden_runtime_artifact = false;
    for (const auto& item : std::filesystem::directory_iterator(root)) {
      if (item.path().filename().string().starts_with(".shaurya-parity-"))
        hidden_runtime_artifact = true;
    }
    expect(!hidden_runtime_artifact, "temporary ledger/result artifacts are cleaned truthfully");
  } catch (const std::exception& exception) {
    std::cerr << exception.what() << '\n';
    ++failures;
  }
  return failures == 0 ? 0 : 1;
}
