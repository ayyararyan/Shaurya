#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/instrument_resolver.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
#include <unistd.h>

using namespace shaurya::execution;

namespace {

constexpr std::string_view kPrefix = R"({"records":[)";
constexpr std::string_view kRecord =
    R"({"canonical_instrument_id":"NSE:NSE_FNO:NIFTY:future:2026-08-27","exchange_segment":"nse_fo","instrument_token":"58072","lot_size":65,"tick_size_paise":10,"trading_symbol":"NIFTY26AUGFUT"})";
constexpr std::string_view kSuffix =
    R"(],"requested_universe_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","schema_version":"1.0.0","sources":[{"broker":"dhan","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},{"broker":"kotak","sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}],"trading_date":"2026-08-27"})";

void write_file(const std::filesystem::path& path, const std::string& bytes) {
  std::ofstream output(path, std::ios::binary);
  output << bytes;
  output.close();
  std::filesystem::permissions(path, std::filesystem::perms::owner_read |
                                         std::filesystem::perms::owner_write,
                               std::filesystem::perm_options::replace);
}

std::string snapshot_with(std::string record = std::string(kRecord)) {
  return std::string(kPrefix) + std::move(record) + std::string(kSuffix) + "\n";
}

void write_pair(const std::filesystem::path& root, const std::string& snapshot,
                std::size_t record_count = 1) {
  write_file(root / "routing_snapshot.json", snapshot);
  const std::string manifest =
      "{\"bytes\":" + std::to_string(snapshot.size()) +
      ",\"exporter_version\":\"1.0.0\",\"record_count\":" +
      std::to_string(record_count) +
      ",\"requested_universe_sha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"schema_version\":\"1.0.0\",\"snapshot_file\":\"routing_snapshot.json\",\"snapshot_sha256\":\"" +
      sha256_hex(snapshot) +
      "\",\"sources\":[{\"broker\":\"dhan\",\"sha256\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\"},{\"broker\":\"kotak\",\"sha256\":\"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\"}],\"trading_date\":\"2026-08-27\"}\n";
  write_file(root / "routing_snapshot.manifest.json", manifest);
}

void expect_error(const std::filesystem::path& root, RoutingErrorCode expected,
                  int& failures, const char* message) {
  try {
    (void)InstrumentResolver::load(root / "routing_snapshot.json",
                                   root / "routing_snapshot.manifest.json", "2026-08-27");
    std::cerr << message << " accepted\n";
    ++failures;
  } catch (const RoutingError& error) {
    if (error.code() != expected) {
      std::cerr << message << " returned wrong code\n";
      ++failures;
    }
  }
}

}  // namespace

int main() {
  int failures = 0;
  const auto expect = [&](bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; ++failures; }
  };
  const auto root = std::filesystem::path("/private/tmp") /
                    ("shaurya-routing-test-" + std::to_string(::getpid()));
  std::filesystem::remove_all(root);
  std::filesystem::create_directory(root);
  std::filesystem::permissions(root, std::filesystem::perms::owner_all,
                               std::filesystem::perm_options::replace);

  const auto snapshot = snapshot_with();
  write_pair(root, snapshot);
  const auto resolver = InstrumentResolver::load(root / "routing_snapshot.json",
                                                  root / "routing_snapshot.manifest.json",
                                                  "2026-08-27");
  expect(resolver.snapshot_digest() == sha256_hex(snapshot), "digest");
  expect(resolver.resolve("NSE:NSE_FNO:NIFTY:future:2026-08-27").order_allowed(),
         "canonical lookup");
  expect(resolver.resolve_token("58072").order_allowed(), "token lookup");
  expect(!resolver.resolve("NSE:NSE_FNO:NIFTY:future:2026-09-24").order_allowed(),
         "resolver guessed an absent route");

  try {
    (void)InstrumentResolver::load(root / "routing_snapshot.json",
                                   root / "routing_snapshot.manifest.json", "2026-08-28");
    expect(false, "stale accepted");
  } catch (const RoutingError& error) {
    expect(error.code() == RoutingErrorCode::Stale, "stale code");
  }

  write_file(root / "routing_snapshot.json", snapshot + " ");
  expect_error(root, RoutingErrorCode::Tampered, failures, "tampered snapshot");
  write_pair(root, snapshot);

  std::filesystem::permissions(root / "routing_snapshot.json",
                               std::filesystem::perms::owner_read |
                                   std::filesystem::perms::owner_write |
                                   std::filesystem::perms::group_read,
                               std::filesystem::perm_options::replace);
  expect_error(root, RoutingErrorCode::Unsafe, failures, "unsafe file mode");
  write_pair(root, snapshot);

  std::filesystem::remove(root / "routing_snapshot.manifest.json");
  expect_error(root, RoutingErrorCode::Partial, failures, "partial pair");
  write_pair(root, snapshot);

  auto changed = std::string(kRecord);
  changed.replace(changed.find("nse_fo"), 6, "unsafe");
  write_pair(root, snapshot_with(changed));
  expect_error(root, RoutingErrorCode::Malformed, failures, "invalid segment");

  changed = std::string(kRecord);
  changed.replace(changed.find("58072"), 5, "58 72");
  write_pair(root, snapshot_with(changed));
  expect_error(root, RoutingErrorCode::Malformed, failures, "invalid token");

  changed = std::string(kRecord);
  changed.replace(changed.find("\"lot_size\":65"), 13,
                  "\"lot_size\":9223372036854775808");
  write_pair(root, snapshot_with(changed));
  expect_error(root, RoutingErrorCode::Malformed, failures, "overflow lot");

  write_pair(root, snapshot);
  const auto real_parent = root / "real";
  std::filesystem::create_directory(real_parent);
  std::filesystem::permissions(real_parent, std::filesystem::perms::owner_all,
                               std::filesystem::perm_options::replace);
  std::filesystem::rename(root / "routing_snapshot.json", real_parent / "routing_snapshot.json");
  std::filesystem::rename(root / "routing_snapshot.manifest.json",
                          real_parent / "routing_snapshot.manifest.json");
  const auto linked_parent = root / "linked";
  std::filesystem::create_directory_symlink(real_parent, linked_parent);
  expect_error(linked_parent, RoutingErrorCode::Unsafe, failures, "symlinked ancestor");

  std::filesystem::remove_all(root);
  return failures == 0 ? 0 : 1;
}
