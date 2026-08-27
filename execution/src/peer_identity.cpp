#include "shaurya/execution/peer_identity.hpp"

#include "shaurya/execution/canonical_json.hpp"

#include <array>
#include <cerrno>
#include <fcntl.h>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

#if defined(__linux__)
#include <sys/types.h>
#endif

namespace shaurya::execution {
namespace {
[[noreturn]] void fail(std::string code) { throw PeerIdentityError(std::move(code)); }
bool digest_shape(std::string_view value) {
  if (value.size() != 64U) return false;
  for (const char item : value)
    if (!((item >= '0' && item <= '9') || (item >= 'a' && item <= 'f'))) return false;
  return true;
}

#if defined(__linux__)
std::string linux_start_identity(std::int64_t pid) {
  std::ifstream input("/proc/" + std::to_string(pid) + "/stat");
  std::string line; std::getline(input, line);
  const auto close = line.rfind(')');
  if (!input || close == std::string::npos || close + 2U >= line.size()) fail("peer_process_unverifiable");
  std::istringstream fields(line.substr(close + 2U));
  std::string value;
  for (int field = 3; field <= 22; ++field)
    if (!(fields >> value)) fail("peer_process_unverifiable");
  return value;
}

std::string linux_executable_digest(std::int64_t pid) {
  const std::string link = "/proc/" + std::to_string(pid) + "/exe";
  const int descriptor = ::open(link.c_str(), O_RDONLY | O_CLOEXEC);
  if (descriptor < 0) fail("peer_executable_unverifiable");
  struct Guard { int value; ~Guard() { if (value >= 0) (void)::close(value); } } guard{descriptor};
  struct stat metadata{};
  if (::fstat(descriptor, &metadata) != 0 || !S_ISREG(metadata.st_mode) ||
      metadata.st_size <= 0 || metadata.st_size > 256 * 1024 * 1024)
    fail("peer_executable_unverifiable");
  std::string bytes(static_cast<std::size_t>(metadata.st_size), '\0');
  std::size_t offset = 0;
  while (offset < bytes.size()) {
    const auto read_count = ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (read_count < 0 && errno == EINTR) continue;
    if (read_count <= 0) fail("peer_executable_unverifiable");
    offset += static_cast<std::size_t>(read_count);
  }
  return sha256_hex(bytes);
}
#endif
}

PeerIdentityError::PeerIdentityError(std::string code)
    : std::runtime_error(code), code_(std::move(code)) {}

bool constant_time_equal(std::string_view left, std::string_view right) noexcept {
  std::size_t difference = left.size() ^ right.size();
  const std::size_t count = left.size() > right.size() ? left.size() : right.size();
  for (std::size_t index = 0; index < count; ++index) {
    const unsigned char a = index < left.size() ? static_cast<unsigned char>(left[index]) : 0U;
    const unsigned char b = index < right.size() ? static_cast<unsigned char>(right[index]) : 0U;
    difference |= static_cast<std::size_t>(a ^ b);
  }
  return difference == 0U;
}

PeerEvidence SystemPeerInspector::inspect(int accepted_socket) const {
#if defined(__linux__)
  struct ucred credentials{}; socklen_t length = sizeof(credentials);
  if (::getsockopt(accepted_socket, SOL_SOCKET, SO_PEERCRED, &credentials, &length) != 0 ||
      length != sizeof(credentials)) fail("peer_credentials_unavailable");
  PeerEvidence evidence{PeerPlatform::Linux, credentials.uid, credentials.gid, credentials.pid};
  evidence.process_start_identity = linux_start_identity(evidence.pid);
  evidence.executable_digest = linux_executable_digest(evidence.pid);
  evidence.executable_evidence_available = true;
  if (linux_start_identity(evidence.pid) != evidence.process_start_identity)
    fail("peer_process_replaced");
  return evidence;
#elif defined(__APPLE__)
  uid_t uid{}; gid_t gid{};
  if (::getpeereid(accepted_socket, &uid, &gid) != 0) fail("peer_credentials_unavailable");
  return {PeerPlatform::Darwin, uid, gid, -1, {}, {}, false};
#else
  (void)accepted_socket;
  fail("peer_platform_unsupported");
#endif
}

void validate_peer_identity(const ExpectedPeerIdentity& expected,
                            const PeerHandshakeBindings& handshake,
                            const PeerEvidence& evidence, bool production_required) {
  if (!digest_shape(expected.executable_digest) || !digest_shape(expected.configuration_digest) ||
      expected.execution_session_id.empty() || handshake.nonce.empty() || handshake.nonce.size() > 128U)
    fail("peer_policy_invalid");
  if (expected.uid != evidence.uid || expected.gid != evidence.gid) fail("peer_credentials_mismatch");
  if (expected.role != handshake.role) fail("peer_role_mismatch");
  if (expected.protocol_version != handshake.protocol_version) fail("peer_protocol_mismatch");
  if (expected.execution_session_id != handshake.execution_session_id) fail("peer_session_mismatch");
  if (!constant_time_equal(expected.configuration_digest, handshake.configuration_digest))
    fail("peer_configuration_mismatch");
  if (!evidence.executable_evidence_available) {
    if (production_required) fail("peer_executable_evidence_unavailable");
  } else if (!constant_time_equal(expected.executable_digest, evidence.executable_digest) ||
             !constant_time_equal(handshake.executable_digest, evidence.executable_digest)) {
    fail("peer_executable_mismatch");
  }
  if (evidence.process_start_identity.empty() ||
      !constant_time_equal(handshake.process_start_identity, evidence.process_start_identity))
    fail("peer_start_identity_mismatch");
}

void validate_peer_continuity(const PeerEvidence& authenticated, const PeerEvidence& current) {
  if (authenticated.uid != current.uid || authenticated.gid != current.gid ||
      authenticated.pid != current.pid ||
      !constant_time_equal(authenticated.process_start_identity, current.process_start_identity) ||
      !constant_time_equal(authenticated.executable_digest, current.executable_digest))
    fail("peer_identity_changed");
}

}  // namespace shaurya::execution
