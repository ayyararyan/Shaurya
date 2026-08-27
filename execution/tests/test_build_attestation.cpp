#include "shaurya/execution/build_attestation.hpp"

#include <string>

int main() {
  const std::string value = shaurya::execution::build_attestation();
  if (value.find("project=shaurya-execution") == std::string::npos) return 1;
  if (value.find("live_router=off") == std::string::npos) return 2;
  if (std::string(shaurya::execution::kLiveRouter) != "off") return 3;
  if (value.find('\n') != std::string::npos || value.find('\r') != std::string::npos) return 4;
  const std::string source_state = shaurya::execution::kSourceState;
  const std::string source_digest = shaurya::execution::kSourceTreeDigest;
  if (source_state != "clean" && source_state != "dirty") return 5;
  if (source_digest.size() != 64U ||
      source_digest.find_first_not_of("0123456789abcdef") != std::string::npos) return 6;
  if (value.find("source_state=" + source_state) == std::string::npos ||
      value.find("source_tree_sha256=" + source_digest) == std::string::npos) return 7;
  return 0;
}
