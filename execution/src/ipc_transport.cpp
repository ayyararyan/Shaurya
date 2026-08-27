#include "shaurya/execution/ipc_transport.hpp"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <limits.h>
#include <poll.h>
#include <cstdio>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#if defined(__linux__)
#include <linux/fs.h>
#include <sys/syscall.h>
#endif
#if defined(__APPLE__)
#include <sys/stdio.h>
#endif

namespace shaurya::execution {
namespace {
[[noreturn]] void fail(std::string code) { throw IpcError(std::move(code)); }

IpcDeadline absolute_deadline(std::chrono::milliseconds timeout) {
  if (timeout.count() < 0 || timeout.count() > std::numeric_limits<int>::max())
    fail("invalid_timeout");
  return std::chrono::steady_clock::now() + timeout;
}

int remaining_milliseconds(IpcDeadline deadline) {
  const auto now = std::chrono::steady_clock::now();
  if (now >= deadline) return 0;
  const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now);
  const auto rounded = remaining + (remaining < deadline - now ? std::chrono::milliseconds(1)
                                                                : std::chrono::milliseconds(0));
  return static_cast<int>(std::min<std::int64_t>(rounded.count(),
                                                 std::numeric_limits<int>::max()));
}

void await(int descriptor, short events, IpcDeadline deadline) {
  pollfd item{descriptor, events, 0};
  while (true) {
    const int timeout = remaining_milliseconds(deadline);
    if (timeout == 0) fail("ipc_timeout");
    const int result = ::poll(&item, 1, timeout);
    if (result < 0 && errno == EINTR) continue;
    if (result == 0) fail("ipc_timeout");
    if (result < 0 || (item.revents & (POLLERR | POLLNVAL)) != 0) fail("ipc_io_error");
    if ((item.revents & events) != 0 || (item.revents & POLLHUP) != 0) return;
  }
}

void read_exact(int descriptor, char* output, std::size_t size,
                IpcDeadline deadline, std::string_view truncation_code) {
  std::size_t offset = 0;
  while (offset < size) {
    await(descriptor, POLLIN, deadline);
    std::array<char, 256U> control{};
    iovec payload{output + offset, size - offset};
    msghdr message{}; message.msg_iov = &payload; message.msg_iovlen = 1U;
    message.msg_control = control.data(); message.msg_controllen = control.size();
    const auto count = ::recvmsg(descriptor, &message, 0);
    if (count < 0 && errno == EINTR) continue;
    if (count == 0) fail(offset == 0U ? "ipc_eof" : std::string(truncation_code));
    if (count < 0) fail("ipc_read_error");
    bool ancillary = (message.msg_flags & MSG_CTRUNC) != 0;
    for (cmsghdr* header = CMSG_FIRSTHDR(&message); header != nullptr;
         header = CMSG_NXTHDR(&message, header)) {
      ancillary = true;
      if (header->cmsg_level == SOL_SOCKET && header->cmsg_type == SCM_RIGHTS &&
          header->cmsg_len >= CMSG_LEN(0)) {
        const auto bytes = header->cmsg_len - CMSG_LEN(0);
        const auto count_fds = bytes / sizeof(int);
        const auto* descriptors = reinterpret_cast<const int*>(CMSG_DATA(header));
        for (std::size_t index = 0; index < count_fds; ++index)
          if (descriptors[index] >= 0) (void)::close(descriptors[index]);
      }
    }
    if (ancillary)
      fail("ipc_ancillary_data_refused");
    offset += static_cast<std::size_t>(count);
  }
}

void write_exact(int descriptor, const std::uint8_t* input, std::size_t size,
                 IpcDeadline deadline) {
  std::size_t offset = 0;
  while (offset < size) {
    await(descriptor, POLLOUT, deadline);
    const auto count = ::send(descriptor, input + offset, size - offset,
                              static_cast<int>(MSG_NOSIGNAL));
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) fail("ipc_write_error");
    offset += static_cast<std::size_t>(count);
  }
}

int socket_type(IpcSocketMode mode) {
  return mode == IpcSocketMode::SeqPacket ? SOCK_SEQPACKET : SOCK_STREAM;
}
void close_on_exec(int descriptor) {
  const int flags = ::fcntl(descriptor, F_GETFD);
  if (flags < 0 || ::fcntl(descriptor, F_SETFD, flags | FD_CLOEXEC) != 0) fail("ipc_cloexec_failed");
}

void validate_parent(const std::filesystem::path& directory, struct stat& metadata) {
  if (!directory.is_absolute() || directory.lexically_normal() != directory ||
      ::lstat(directory.c_str(), &metadata) != 0 || !S_ISDIR(metadata.st_mode) ||
      metadata.st_uid != ::geteuid() || (metadata.st_mode & 07777U) != 0700U) fail("runtime_directory_unsafe");
  std::error_code error;
  if (std::filesystem::canonical(directory, error) != directory || error) fail("runtime_directory_unsafe");
}

int open_directory_absolute(const std::filesystem::path& directory) {
  if (!directory.is_absolute() || directory.lexically_normal() != directory)
    fail("runtime_directory_unsafe");
  int current = ::open("/", O_RDONLY | O_CLOEXEC | O_DIRECTORY);
  if (current < 0) fail("runtime_directory_unsafe");
  for (const auto& component : directory.relative_path()) {
    const auto name = component.string();
    if (name.empty() || name == "." || name == "..") {
      (void)::close(current);
      fail("runtime_directory_unsafe");
    }
    const int next = ::openat(current, name.c_str(),
                              O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
    (void)::close(current);
    if (next < 0) fail("runtime_directory_unsafe");
    current = next;
  }
  return current;
}

int rename_exclusive(int directory, const char* from, const char* to) {
#if defined(__linux__)
  return static_cast<int>(::syscall(SYS_renameat2, directory, from, directory, to,
                                    RENAME_NOREPLACE));
#elif defined(__APPLE__)
  return ::renameatx_np(directory, from, directory, to, RENAME_EXCL);
#else
  (void)directory; (void)from; (void)to;
  errno = ENOTSUP;
  return -1;
#endif
}

bool retire_owned_entry(int parent, std::string_view basename,
                        std::uint64_t device, std::uint64_t inode) noexcept {
  struct stat before{};
  const std::string name(basename);
  if (::fstatat(parent, name.c_str(), &before, AT_SYMLINK_NOFOLLOW) != 0 ||
      static_cast<std::uint64_t>(before.st_dev) != device ||
      static_cast<std::uint64_t>(before.st_ino) != inode)
    return false;
  for (unsigned attempt = 0; attempt < 16U; ++attempt) {
    const std::string quarantine = ".shaurya-retire-" + std::to_string(::getpid()) + "-" +
                                   std::to_string(inode) + "-" + std::to_string(attempt);
    if (rename_exclusive(parent, name.c_str(), quarantine.c_str()) != 0) {
      if (errno == EEXIST) continue;
      return false;
    }
    struct stat moved{};
    if (::fstatat(parent, quarantine.c_str(), &moved, AT_SYMLINK_NOFOLLOW) == 0 &&
        static_cast<std::uint64_t>(moved.st_dev) == device &&
        static_cast<std::uint64_t>(moved.st_ino) == inode)
      return ::unlinkat(parent, quarantine.c_str(), 0) == 0;
    (void)rename_exclusive(parent, quarantine.c_str(), name.c_str());
    return false;
  }
  return false;
}

bool safe_basename(std::string_view value) {
  if (value.empty() || value.size() > 80U || value == "." || value == "..") return false;
  for (const char item : value)
    if (!((item >= 'A' && item <= 'Z') || (item >= 'a' && item <= 'z') ||
          (item >= '0' && item <= '9') || item == '.' || item == '_' || item == '-')) return false;
  return true;
}
}

IpcError::IpcError(std::string code) : std::runtime_error(code), code_(std::move(code)) {}

IpcFrameCodec::IpcFrameCodec(std::size_t maximum_payload_bytes) : maximum_(maximum_payload_bytes) {
  if (maximum_ == 0U || maximum_ > kMaximumIpcPayloadBytes) fail("ipc_maximum_unsafe");
}

std::vector<std::uint8_t> IpcFrameCodec::encode_stream(std::string_view payload) const {
  if (payload.empty()) fail("ipc_empty_frame");
  if (payload.size() > maximum_) fail("ipc_frame_oversized");
  const auto length = static_cast<std::uint32_t>(payload.size());
  std::vector<std::uint8_t> output(4U + payload.size());
  output[0] = static_cast<std::uint8_t>(length >> 24U);
  output[1] = static_cast<std::uint8_t>(length >> 16U);
  output[2] = static_cast<std::uint8_t>(length >> 8U);
  output[3] = static_cast<std::uint8_t>(length);
  std::memcpy(output.data() + 4U, payload.data(), payload.size());
  return output;
}

std::string IpcFrameCodec::decode_stream(std::string_view frame) const {
  if (frame.size() < 4U) fail("ipc_truncated_prefix");
  const auto length = (static_cast<std::uint32_t>(static_cast<unsigned char>(frame[0])) << 24U) |
                      (static_cast<std::uint32_t>(static_cast<unsigned char>(frame[1])) << 16U) |
                      (static_cast<std::uint32_t>(static_cast<unsigned char>(frame[2])) << 8U) |
                      static_cast<std::uint32_t>(static_cast<unsigned char>(frame[3]));
  if (length == 0U) fail("ipc_empty_frame");
  if (length > maximum_) fail("ipc_frame_oversized");
  if (frame.size() < 4U + length) fail("ipc_truncated_payload");
  if (frame.size() != 4U + length) fail("ipc_extra_bytes");
  return std::string(frame.substr(4U));
}

std::string IpcFrameCodec::decode_packet(std::string_view packet, bool truncated) const {
  if (truncated) fail("ipc_packet_truncated");
  if (packet.empty()) fail("ipc_empty_frame");
  if (packet.size() > maximum_) fail("ipc_frame_oversized");
  return std::string(packet);
}

IpcSocketMode select_unix_mode(bool seqpacket_supported) noexcept {
  return seqpacket_supported ? IpcSocketMode::SeqPacket : IpcSocketMode::Stream;
}

std::pair<int, int> create_unix_socketpair(IpcSocketMode mode) {
  int pair[2]{-1, -1};
  if (::socketpair(AF_UNIX, socket_type(mode), 0, pair) != 0)
    fail("ipc_socketpair_failed");
  try { close_on_exec(pair[0]); close_on_exec(pair[1]); }
  catch (...) { (void)::close(pair[0]); (void)::close(pair[1]); throw; }
  return {pair[0], pair[1]};
}

std::string read_ipc_frame(int descriptor, IpcSocketMode mode, const IpcFrameCodec& codec,
                           std::chrono::milliseconds timeout) {
  return read_ipc_frame_until(descriptor, mode, codec, absolute_deadline(timeout));
}

std::string read_ipc_frame_until(int descriptor, IpcSocketMode mode,
                                 const IpcFrameCodec& codec, IpcDeadline deadline) {
  if (mode == IpcSocketMode::Stream) {
    char prefix[4]{};
    read_exact(descriptor, prefix, sizeof(prefix), deadline, "ipc_truncated_prefix");
    const auto length = (static_cast<std::uint32_t>(static_cast<unsigned char>(prefix[0])) << 24U) |
                        (static_cast<std::uint32_t>(static_cast<unsigned char>(prefix[1])) << 16U) |
                        (static_cast<std::uint32_t>(static_cast<unsigned char>(prefix[2])) << 8U) |
                        static_cast<std::uint32_t>(static_cast<unsigned char>(prefix[3]));
    if (length == 0U) fail("ipc_empty_frame");
    if (length > codec.maximum_payload_bytes()) fail("ipc_frame_oversized");
    std::string payload(length, '\0');
    read_exact(descriptor, payload.data(), payload.size(), deadline, "ipc_truncated_payload");
    return payload;
  }
  await(descriptor, POLLIN, deadline);
  std::vector<char> packet(codec.maximum_payload_bytes() + 1U);
  std::array<char, 256U> control{};
  iovec payload{packet.data(), packet.size()};
  msghdr message{}; message.msg_iov = &payload; message.msg_iovlen = 1U;
  message.msg_control = control.data(); message.msg_controllen = control.size();
  ssize_t count = -1;
  while (true) {
    count = ::recvmsg(descriptor, &message, 0);
    if (count < 0 && errno == EINTR) {
      await(descriptor, POLLIN, deadline);
      continue;
    }
    break;
  }
  if (count == 0) fail("ipc_eof");
  if (count < 0) fail("ipc_read_error");
  bool ancillary = (message.msg_flags & MSG_CTRUNC) != 0;
  for (cmsghdr* header = CMSG_FIRSTHDR(&message); header != nullptr;
       header = CMSG_NXTHDR(&message, header)) {
    ancillary = true;
    if (header->cmsg_level == SOL_SOCKET && header->cmsg_type == SCM_RIGHTS &&
        header->cmsg_len >= CMSG_LEN(0)) {
      const auto bytes = header->cmsg_len - CMSG_LEN(0);
      const auto count_fds = bytes / sizeof(int);
      const auto* descriptors = reinterpret_cast<const int*>(CMSG_DATA(header));
      for (std::size_t index = 0; index < count_fds; ++index)
        if (descriptors[index] >= 0) (void)::close(descriptors[index]);
    }
  }
  if (ancillary)
    fail("ipc_ancillary_data_refused");
  const auto size = static_cast<std::size_t>(count);
  return codec.decode_packet(std::string_view(packet.data(), size),
                             size > codec.maximum_payload_bytes() ||
                                 (message.msg_flags & MSG_TRUNC) != 0);
}

void write_ipc_frame(int descriptor, IpcSocketMode mode, const IpcFrameCodec& codec,
                     std::string_view payload, std::chrono::milliseconds timeout) {
  write_ipc_frame_until(descriptor, mode, codec, payload, absolute_deadline(timeout));
}

void write_ipc_frame_until(int descriptor, IpcSocketMode mode, const IpcFrameCodec& codec,
                           std::string_view payload, IpcDeadline deadline) {
  if (mode == IpcSocketMode::Stream) {
    const auto frame = codec.encode_stream(payload);
    write_exact(descriptor, frame.data(), frame.size(), deadline);
    return;
  }
  if (payload.empty()) fail("ipc_empty_frame");
  if (payload.size() > codec.maximum_payload_bytes()) fail("ipc_frame_oversized");
  await(descriptor, POLLOUT, deadline);
  ssize_t count = -1;
  while (true) {
    count = ::send(descriptor, payload.data(), payload.size(), MSG_NOSIGNAL);
    if (count < 0 && errno == EINTR) {
      await(descriptor, POLLOUT, deadline);
      continue;
    }
    break;
  }
  if (count < 0 || static_cast<std::size_t>(count) != payload.size()) fail("ipc_write_error");
}

ProtectedUnixListener::ProtectedUnixListener(int descriptor, std::filesystem::path path,
                                             int parent_descriptor, std::string basename,
                                             std::uint64_t device, std::uint64_t inode)
    : descriptor_(descriptor), path_(std::move(path)), parent_descriptor_(parent_descriptor),
      basename_(std::move(basename)), device_(device), inode_(inode) {}

ProtectedUnixListener ProtectedUnixListener::create(
    const std::filesystem::path& runtime_directory, std::string socket_basename,
    IpcSocketMode mode) {
  struct stat parent_before{};
  validate_parent(runtime_directory, parent_before);
  const int parent_descriptor = open_directory_absolute(runtime_directory);
  try {
    auto result = create_at(parent_descriptor, runtime_directory, std::move(socket_basename), mode);
    (void)::close(parent_descriptor);
    return result;
  } catch (...) {
    (void)::close(parent_descriptor);
    throw;
  }
}

ProtectedUnixListener ProtectedUnixListener::create_at(
    int runtime_directory_descriptor,
    const std::filesystem::path& display_runtime_directory,
    std::string socket_basename, IpcSocketMode mode) {
  if (runtime_directory_descriptor < 0 || !display_runtime_directory.is_absolute() ||
      display_runtime_directory.lexically_normal() != display_runtime_directory ||
      !safe_basename(socket_basename))
    fail("runtime_directory_unsafe");
  const int parent_descriptor =
      ::fcntl(runtime_directory_descriptor, F_DUPFD_CLOEXEC, 0);
  if (parent_descriptor < 0) fail("runtime_directory_unsafe");
  struct ParentGuard {
    int value;
    ~ParentGuard() { if (value >= 0) (void)::close(value); }
    int release() noexcept { return std::exchange(value, -1); }
  } parent_guard{parent_descriptor};
  struct stat parent_opened{};
  if (::fstat(parent_descriptor, &parent_opened) != 0 || !S_ISDIR(parent_opened.st_mode) ||
      parent_opened.st_uid != ::geteuid() || (parent_opened.st_mode & 07777U) != 0700U)
    fail("runtime_directory_unsafe");
  const auto path = display_runtime_directory / socket_basename;
#if defined(__linux__)
  const std::string anchored_path = "/proc/self/fd/" + std::to_string(parent_descriptor) +
                                    "/" + socket_basename;
#elif defined(__APPLE__)
  std::array<char, PATH_MAX> retained_directory_path{};
  if (::fcntl(parent_descriptor, F_GETPATH, retained_directory_path.data()) != 0)
    fail("runtime_directory_unverifiable");
  const std::string anchored_path = std::string(retained_directory_path.data()) +
                                    "/" + socket_basename;
#else
#error "Protected descriptor-anchored Unix socket paths require Linux or Darwin"
#endif
  struct stat existing{};
  if (::fstatat(parent_descriptor, socket_basename.c_str(), &existing,
                AT_SYMLINK_NOFOLLOW) == 0) {
    if (!S_ISSOCK(existing.st_mode) || existing.st_uid != ::geteuid() ||
        (existing.st_mode & 07777U) != 0600U) fail("socket_path_occupied");
    const int probe = ::socket(AF_UNIX, socket_type(mode), 0);
    if (probe < 0) fail("socket_probe_failed");
    try { close_on_exec(probe); } catch (...) { (void)::close(probe); throw; }
    sockaddr_un address{}; address.sun_family = AF_UNIX;
    if (anchored_path.size() >= sizeof(address.sun_path)) { ::close(probe); fail("socket_path_invalid"); }
    std::memcpy(address.sun_path, anchored_path.c_str(), anchored_path.size() + 1U);
    const int connected = ::connect(probe, reinterpret_cast<const sockaddr*>(&address), sizeof(address));
    const int connect_error = errno; (void)::close(probe);
    if (connected == 0 || connect_error != ECONNREFUSED) fail("socket_active_or_unverifiable");
    struct stat unchanged{};
    if (::fstatat(parent_descriptor, socket_basename.c_str(), &unchanged,
                  AT_SYMLINK_NOFOLLOW) != 0 || unchanged.st_dev != existing.st_dev ||
        unchanged.st_ino != existing.st_ino ||
        !retire_owned_entry(parent_descriptor, socket_basename,
                            static_cast<std::uint64_t>(existing.st_dev),
                            static_cast<std::uint64_t>(existing.st_ino))) {
      fail("socket_replaced");
    }
  } else if (errno != ENOENT) {
    fail("socket_path_unverifiable");
  }
  const int descriptor = ::socket(AF_UNIX, socket_type(mode), 0);
  if (descriptor < 0) fail("socket_create_failed");
  try { close_on_exec(descriptor); } catch (...) { (void)::close(descriptor); throw; }
  sockaddr_un address{}; address.sun_family = AF_UNIX;
  if (anchored_path.size() >= sizeof(address.sun_path)) { ::close(descriptor); fail("socket_path_invalid"); }
  std::memcpy(address.sun_path, anchored_path.c_str(), anchored_path.size() + 1U);
  if (::bind(descriptor, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) != 0) {
    (void)::close(descriptor); fail("socket_bind_failed");
  }
  struct stat bound_socket{};
  if (::fstatat(parent_descriptor, socket_basename.c_str(), &bound_socket,
                AT_SYMLINK_NOFOLLOW) != 0 || !S_ISSOCK(bound_socket.st_mode)) {
    (void)::close(descriptor); fail("socket_replaced");
  }
  const auto unlink_owned = [&] {
    (void)retire_owned_entry(parent_descriptor, socket_basename,
                             static_cast<std::uint64_t>(bound_socket.st_dev),
                             static_cast<std::uint64_t>(bound_socket.st_ino));
  };
  if (::fchmodat(parent_descriptor, socket_basename.c_str(), 0600, 0) != 0 ||
      ::listen(descriptor, 2) != 0) {
    (void)::close(descriptor); unlink_owned(); fail("socket_bind_failed");
  }
  struct stat parent_after{}, socket_info{};
  if (::fstat(parent_descriptor, &parent_after) != 0 ||
      parent_after.st_dev != parent_opened.st_dev ||
      parent_after.st_ino != parent_opened.st_ino ||
      ::fstatat(parent_descriptor, socket_basename.c_str(), &socket_info,
                AT_SYMLINK_NOFOLLOW) != 0 || !S_ISSOCK(socket_info.st_mode) ||
      socket_info.st_uid != ::geteuid() || (socket_info.st_mode & 07777U) != 0600U) {
    (void)::close(descriptor); unlink_owned(); fail("socket_replaced");
  }
  return ProtectedUnixListener(descriptor, path, parent_guard.release(), std::move(socket_basename),
                               static_cast<std::uint64_t>(socket_info.st_dev),
                               static_cast<std::uint64_t>(socket_info.st_ino));
}

ProtectedUnixListener::ProtectedUnixListener(ProtectedUnixListener&& other) noexcept
    : descriptor_(std::exchange(other.descriptor_, -1)), path_(std::move(other.path_)),
      parent_descriptor_(std::exchange(other.parent_descriptor_, -1)),
      basename_(std::move(other.basename_)),
      device_(other.device_), inode_(other.inode_) {}
ProtectedUnixListener& ProtectedUnixListener::operator=(ProtectedUnixListener&& other) noexcept {
  if (this != &other) { close(); descriptor_ = std::exchange(other.descriptor_, -1);
    path_ = std::move(other.path_);
    parent_descriptor_ = std::exchange(other.parent_descriptor_, -1);
    basename_ = std::move(other.basename_);
    device_ = other.device_; inode_ = other.inode_; }
  return *this;
}
ProtectedUnixListener::~ProtectedUnixListener() { close(); }
int ProtectedUnixListener::accept_one(std::chrono::milliseconds timeout) const {
  return accept_one_until(absolute_deadline(timeout));
}

int ProtectedUnixListener::accept_one_until(IpcDeadline deadline) const {
  if (descriptor_ < 0) fail("listener_closed");
  int accepted = -1;
  while (true) {
    await(descriptor_, POLLIN, deadline);
    accepted = ::accept(descriptor_, nullptr, nullptr);
    if (accepted < 0 && errno == EINTR) continue;
    break;
  }
  if (accepted < 0) fail("ipc_accept_failed");
  try { close_on_exec(accepted); }
  catch (...) { (void)::close(accepted); throw; }
  return accepted;
}
void ProtectedUnixListener::close() noexcept {
  if (descriptor_ >= 0) { (void)::close(descriptor_); descriptor_ = -1; }
  if (parent_descriptor_ >= 0 && !basename_.empty())
    (void)retire_owned_entry(parent_descriptor_, basename_, device_, inode_);
  if (parent_descriptor_ >= 0) { (void)::close(parent_descriptor_); parent_descriptor_ = -1; }
  basename_.clear();
  path_.clear();
}

}  // namespace shaurya::execution
