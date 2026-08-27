#include "shaurya/execution/ipc_transport.hpp"

#include <array>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <thread>
#include <sys/socket.h>
#include <unistd.h>

using namespace shaurya::execution;

namespace {
template <typename Function> bool refused(Function action) {
  try { action(); } catch (const IpcError&) { return true; }
  return false;
}
std::size_t descriptor_count() {
#if defined(__linux__)
  const std::filesystem::path directory("/proc/self/fd");
#else
  const std::filesystem::path directory("/dev/fd");
#endif
  std::size_t count = 0;
  for (const auto& unused : std::filesystem::directory_iterator(directory)) {
    (void)unused;
    ++count;
  }
  return count;
}
}

int main() {
  int failures = 0;
  const auto expect = [&](bool value, const char* message) {
    if (!value) { std::cerr << message << '\n'; ++failures; }
  };
  IpcFrameCodec codec(32U);
  const auto encoded = codec.encode_stream("{}\n");
  expect(encoded.size() == 7U && encoded[3] == 3U, "big-endian frame invalid");
  expect(codec.decode_stream(std::string_view(reinterpret_cast<const char*>(encoded.data()),
                                               encoded.size())) == "{}\n", "frame round trip failed");
  expect(refused([&] { (void)codec.decode_stream(std::string("\0\0", 2)); }),
         "truncated prefix accepted");
  expect(refused([&] { (void)codec.decode_stream(std::string("\0\0\0\x21", 4)); }),
         "oversized declaration accepted");
  expect(refused([&] { (void)codec.decode_packet("x", true); }), "truncated packet accepted");
  expect(refused([] { IpcFrameCodec unsafe(kMaximumIpcPayloadBytes + 1U); }),
         "unsafe maximum accepted");

  for (const auto mode : {IpcSocketMode::Stream}) {
    const auto pair = create_unix_socketpair(mode);
    write_ipc_frame(pair.first, mode, codec, "payload", std::chrono::milliseconds(100));
    expect(read_ipc_frame(pair.second, mode, codec, std::chrono::milliseconds(100)) == "payload",
           "socket frame round trip failed");
    (void)::close(pair.first); (void)::close(pair.second);
  }
  try {
    const auto pair = create_unix_socketpair(IpcSocketMode::SeqPacket);
    write_ipc_frame(pair.first, IpcSocketMode::SeqPacket, codec, "payload",
                    std::chrono::milliseconds(100));
    expect(read_ipc_frame(pair.second, IpcSocketMode::SeqPacket, codec,
                          std::chrono::milliseconds(100)) == "payload",
           "seqpacket round trip failed");
    (void)::close(pair.first); (void)::close(pair.second);
  } catch (const IpcError&) {
    expect(select_unix_mode(false) == IpcSocketMode::Stream, "stream fallback unavailable");
  }
  const auto timeout_pair = create_unix_socketpair(IpcSocketMode::Stream);
  expect(refused([&] { (void)read_ipc_frame(timeout_pair.first, IpcSocketMode::Stream, codec,
                                             std::chrono::milliseconds(1)); }), "read timeout absent");
  (void)::close(timeout_pair.first); (void)::close(timeout_pair.second);
  const auto slow_pair = create_unix_socketpair(IpcSocketMode::Stream);
  std::thread slow_writer([&] {
    const std::array<unsigned char, 4U> prefix{0U, 0U, 0U, 1U};
    for (const auto byte : prefix) {
      (void)::send(slow_pair.first, &byte, 1U, MSG_NOSIGNAL);
      std::this_thread::sleep_for(std::chrono::milliseconds(15));
    }
  });
  const auto slow_start = std::chrono::steady_clock::now();
  expect(refused([&] { (void)read_ipc_frame(slow_pair.second, IpcSocketMode::Stream, codec,
                                             std::chrono::milliseconds(30)); }),
         "partial-frame slowloris renewed the deadline");
  const auto slow_elapsed = std::chrono::steady_clock::now() - slow_start;
  expect(slow_elapsed < std::chrono::milliseconds(55), "frame deadline was not absolute");
  slow_writer.join();
  (void)::close(slow_pair.first); (void)::close(slow_pair.second);
  const auto ancillary_pair = create_unix_socketpair(IpcSocketMode::Stream);
  const auto ancillary_frame = codec.encode_stream("x");
  iovec payload{const_cast<std::uint8_t*>(ancillary_frame.data()), ancillary_frame.size()};
  std::array<char, CMSG_SPACE(sizeof(int))> control{};
  msghdr message{}; message.msg_iov = &payload; message.msg_iovlen = 1U;
  message.msg_control = control.data(); message.msg_controllen = control.size();
  cmsghdr* header = CMSG_FIRSTHDR(&message); header->cmsg_level = SOL_SOCKET;
  header->cmsg_type = SCM_RIGHTS; header->cmsg_len = CMSG_LEN(sizeof(int));
  std::memcpy(CMSG_DATA(header), &ancillary_pair.first, sizeof(int));
  const auto descriptors_before = descriptor_count();
  expect(::sendmsg(ancillary_pair.first, &message, 0) > 0, "ancillary fixture send failed");
  expect(refused([&] { (void)read_ipc_frame(ancillary_pair.second, IpcSocketMode::Stream, codec,
                                             std::chrono::milliseconds(100)); }),
         "ancillary descriptor accepted");
  expect(descriptor_count() == descriptors_before, "refused ancillary descriptor leaked");
  (void)::close(ancillary_pair.first); (void)::close(ancillary_pair.second);
  expect(select_unix_mode(true) == IpcSocketMode::SeqPacket &&
         select_unix_mode(false) == IpcSocketMode::Stream, "mode selection failed");
  return failures == 0 ? 0 : 1;
}
