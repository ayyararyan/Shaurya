#include "shaurya/execution/build_attestation.hpp"

#include <sstream>

namespace shaurya::execution {
std::string build_attestation() {
  std::ostringstream output;
  output << "project=shaurya-execution"
         << " version=" << kProjectVersion
         << " revision=" << kSourceRevision
         << " source_state=" << kSourceState
         << " source_tree_sha256=" << kSourceTreeDigest
         << " compiler=" << kCompilerId
         << " build_type=" << kBuildType
         << " live_router=" << kLiveRouter;
  return output.str();
}
}  // namespace shaurya::execution
