#include "shaurya/execution/build_attestation.hpp"

#include <string>

int main() {
  const std::string value = shaurya::execution::build_attestation();
  if (value.find("project=shaurya-execution") == std::string::npos) return 1;
  if (value.find("live_router=off") == std::string::npos) return 2;
  if (std::string(shaurya::execution::kLiveRouter) != "off") return 3;
  if (value.find('\n') != std::string::npos || value.find('\r') != std::string::npos) return 4;
  return 0;
}
