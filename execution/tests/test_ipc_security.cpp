#include "shaurya/execution/ipc_transport.hpp"
#include "shaurya/execution/peer_identity.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <chrono>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <thread>
#include <sys/stat.h>
#include <unistd.h>

using namespace shaurya::execution;

namespace {
template <typename Function> bool refused(Function action) {
  try { action(); } catch (const std::exception&) { return true; }
  return false;
}
void ignore_signal(int) {}
}

int main() {
  int failures = 0;
  const auto expect = [&](bool value, const char* message) {
    if (!value) { std::cerr << message << '\n'; ++failures; }
  };
  char pattern[] = "/private/tmp/shaurya-ipc-security-XXXXXX";
  const char* made = ::mkdtemp(pattern);
  if (made == nullptr) return 1;
  const std::filesystem::path runtime(made);
  (void)::chmod(runtime.c_str(), 0700);
  const auto socket_path = runtime / "market.sock";
  {
    auto listener = ProtectedUnixListener::create(runtime, "market.sock", IpcSocketMode::Stream);
    struct stat metadata{};
    expect(::lstat(socket_path.c_str(), &metadata) == 0 && S_ISSOCK(metadata.st_mode) &&
           (metadata.st_mode & 07777U) == 0600U, "socket protections invalid");
  }
  expect(!std::filesystem::exists(socket_path), "owned socket not removed");
  const auto preserved_path = runtime / "owned-renamed.sock";
  {
    auto listener = ProtectedUnixListener::create(runtime, "market.sock", IpcSocketMode::Stream);
    std::filesystem::rename(socket_path, preserved_path);
    { std::ofstream replacement(socket_path); replacement << "foreign"; }
    (void)::chmod(socket_path.c_str(), 0600);
    listener.close();
  }
  expect(std::filesystem::is_regular_file(socket_path) &&
         std::filesystem::is_socket(preserved_path),
         "listener cleanup removed or overwrote a replacement inode");
  std::filesystem::remove(socket_path);

  {
    auto listener = ProtectedUnixListener::create(runtime, "eintr.sock", IpcSocketMode::Stream);
    bool accepted = false;
    std::thread accepting([&] {
      try {
        const int descriptor = listener.accept_one(std::chrono::milliseconds(250));
        accepted = descriptor >= 0;
        if (descriptor >= 0) (void)::close(descriptor);
      } catch (const IpcError&) {}
    });
    struct sigaction action{};
    action.sa_handler = ignore_signal;
    (void)sigemptyset(&action.sa_mask);
    expect(::sigaction(SIGUSR1, &action, nullptr) == 0, "EINTR signal handler setup failed");
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    expect(::pthread_kill(accepting.native_handle(), SIGUSR1) == 0,
           "EINTR signal delivery failed");
    const int client = ::socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un address{}; address.sun_family = AF_UNIX;
    const auto eintr_path = (runtime / "eintr.sock").string();
    std::memcpy(address.sun_path, eintr_path.c_str(), eintr_path.size() + 1U);
    expect(client >= 0 && ::connect(client, reinterpret_cast<const sockaddr*>(&address),
                                    sizeof(address)) == 0,
           "EINTR accept fixture connection failed");
    accepting.join();
    if (client >= 0) (void)::close(client);
    expect(accepted, "accept did not retry after EINTR");
  }
  std::filesystem::remove(preserved_path);
  (void)::chmod(runtime.c_str(), 0755);
  expect(refused([&] { (void)ProtectedUnixListener::create(runtime, "bad.sock",
                                                                 IpcSocketMode::Stream); }),
         "unsafe runtime directory accepted");
  (void)::chmod(runtime.c_str(), 0700);
  { std::ofstream file(socket_path); file << "foreign"; }
  expect(refused([&] { (void)ProtectedUnixListener::create(runtime, "market.sock",
                                                                 IpcSocketMode::Stream); }),
         "regular socket path accepted");
  std::filesystem::remove(socket_path);

  const auto retained_runtime = runtime / "retained";
  const auto moved_runtime = runtime / "retained-moved";
  std::filesystem::create_directory(retained_runtime);
  (void)::chmod(retained_runtime.c_str(), 0700);
  const int retained_descriptor =
      ::open(retained_runtime.c_str(), O_RDONLY | O_CLOEXEC | O_DIRECTORY);
  expect(retained_descriptor >= 0, "retained runtime descriptor open failed");
  std::filesystem::rename(retained_runtime, moved_runtime);
  std::filesystem::create_directory(retained_runtime);
  (void)::chmod(retained_runtime.c_str(), 0700);
  {
    auto listener = ProtectedUnixListener::create_at(
        retained_descriptor, retained_runtime, "anchored.sock", IpcSocketMode::Stream);
    expect(std::filesystem::is_socket(moved_runtime / "anchored.sock") &&
               !std::filesystem::exists(retained_runtime / "anchored.sock"),
           "listener bind escaped retained directory descriptor");
  }
  expect(!std::filesystem::exists(moved_runtime / "anchored.sock") &&
             !std::filesystem::exists(retained_runtime / "anchored.sock"),
         "descriptor-relative listener cleanup failed");
  (void)::close(retained_descriptor);
  std::filesystem::remove(retained_runtime);
  std::filesystem::remove(moved_runtime);

  const std::string executable(64U, 'a'), configuration(64U, 'b');
  ExpectedPeerIdentity expected{PeerRole::StrategyClient, 10U, 20U, executable, configuration,
                                "1.0.0", "session"};
  PeerHandshakeBindings handshake{PeerRole::StrategyClient, "1.0.0", "session", configuration,
                                   executable, "start-1", "fresh"};
  PeerEvidence evidence{PeerPlatform::Linux, 10U, 20U, 42, "start-1", executable, true};
  validate_peer_identity(expected, handshake, evidence);
  auto bad = evidence; bad.uid = 11U;
  expect(refused([&] { validate_peer_identity(expected, handshake, bad); }),
         "wrong uid accepted");
  PeerEvidence darwin{PeerPlatform::Darwin, 10U, 20U, -1, "start-1", {}, false};
  expect(refused([&] { validate_peer_identity(expected, handshake, darwin, true); }),
         "missing Darwin executable evidence accepted in production");
  validate_peer_identity(expected, handshake, darwin, false);
  bad = evidence; bad.process_start_identity = "start-2";
  expect(refused([&] { validate_peer_continuity(evidence, bad); }), "PID reuse accepted");
  std::filesystem::remove(runtime);
  return failures == 0 ? 0 : 1;
}
