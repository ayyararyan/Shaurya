#include "shaurya/execution/instrument_resolver.hpp"

#include "shaurya/execution/canonical_json.hpp"
#include "shaurya/execution/contracts.hpp"

#include <cerrno>
#include <fcntl.h>
#include <limits>
#include <set>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>

namespace shaurya::execution {
namespace {
[[noreturn]] void routing_fail(RoutingErrorCode code) { throw RoutingError(code); }
const JsonValue& field(const JsonObject& object, std::string_view key) {
  const auto iterator=object.find(key); if(iterator==object.end()) routing_fail(RoutingErrorCode::Malformed); return iterator->second;
}
void fields(const JsonObject& object, std::initializer_list<std::string_view> wanted) {
  if(object.size()!=wanted.size()) routing_fail(RoutingErrorCode::Malformed);
  for(const auto key:wanted) if(!object.contains(key)) routing_fail(RoutingErrorCode::Malformed);
}
bool lowercase_hex(std::string_view value) {
  return value.size()==64 && std::all_of(value.begin(),value.end(),[](char item){ return (item>='0'&&item<='9')||(item>='a'&&item<='f'); });
}
bool bounded_route_text(std::string_view value, std::size_t maximum, bool allow_ampersand) {
  return !value.empty() && value.size() <= maximum &&
         std::all_of(value.begin(), value.end(), [allow_ampersand](char item) {
           return (item >= 'A' && item <= 'Z') || (item >= 'a' && item <= 'z') ||
                  (item >= '0' && item <= '9') || item == '.' || item == '_' ||
                  item == '-' || (allow_ampersand && item == '&');
         });
}
bool symlink_free_ancestors(const std::filesystem::path& path) {
  auto current = path.root_path();
  for (const auto& component : path.relative_path().parent_path()) {
    current /= component;
    struct stat info {};
    if (::lstat(current.c_str(), &info) != 0 || S_ISLNK(info.st_mode) ||
        !S_ISDIR(info.st_mode)) {
      return false;
    }
  }
  return true;
}
std::string read_regular(const std::filesystem::path& path) {
  if (!path.is_absolute() || path.lexically_normal() != path ||
      !symlink_free_ancestors(path)) {
    routing_fail(RoutingErrorCode::Unsafe);
  }
  struct stat parent_info {};
  if (::lstat(path.parent_path().c_str(), &parent_info) != 0 ||
      !S_ISDIR(parent_info.st_mode) || parent_info.st_uid != ::geteuid() ||
      (parent_info.st_mode & 077U) != 0U) {
    routing_fail(RoutingErrorCode::Unsafe);
  }
  const int descriptor = ::open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (descriptor < 0) routing_fail(RoutingErrorCode::Unsafe);
  struct DescriptorGuard {
    int value;
    ~DescriptorGuard() { if (value >= 0) (void)::close(value); }
  } guard{descriptor};
  struct stat opened {};
  if (::fstat(descriptor, &opened) != 0 || !S_ISREG(opened.st_mode) ||
      opened.st_uid != ::geteuid() || (opened.st_mode & 077U) != 0U) {
    routing_fail(RoutingErrorCode::Unsafe);
  }
  if (opened.st_size <= 0 ||
      static_cast<std::uint64_t>(opened.st_size) > kMaximumJsonBytes) {
    routing_fail(RoutingErrorCode::Malformed);
  }
  std::string bytes(static_cast<std::size_t>(opened.st_size), '\0');
  std::size_t offset = 0;
  while (offset < bytes.size()) {
    const auto count = ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) routing_fail(RoutingErrorCode::Malformed);
    offset += static_cast<std::size_t>(count);
  }
  char extra = '\0';
  while (true) {
    const auto count = ::read(descriptor, &extra, 1);
    if (count < 0 && errno == EINTR) continue;
    if (count != 0) routing_fail(RoutingErrorCode::Malformed);
    break;
  }
  struct stat after {};
  if (::lstat(path.c_str(), &after) != 0 || !S_ISREG(after.st_mode) ||
      after.st_dev != opened.st_dev || after.st_ino != opened.st_ino ||
      after.st_size != opened.st_size || after.st_uid != opened.st_uid ||
      (after.st_mode & 07777U) != (opened.st_mode & 07777U)) {
    routing_fail(RoutingErrorCode::Unsafe);
  }
  return bytes;
}
std::string string_field(const JsonObject& object,std::string_view key) { try{return json_string(field(object,key),key);}catch(const JsonError&){routing_fail(RoutingErrorCode::Malformed);} }
std::uint64_t uint_field(const JsonObject& object,std::string_view key) { try{return json_uint64(field(object,key),key);}catch(const JsonError&){routing_fail(RoutingErrorCode::Malformed);} }
}

RoutingError::RoutingError(RoutingErrorCode code) : std::runtime_error("NO ORDER: routing verification failed"), code_(code) {}
RoutingErrorCode RoutingError::code() const noexcept { return code_; }

InstrumentResolver InstrumentResolver::load(const std::filesystem::path& snapshot_path,
                                            const std::filesystem::path& manifest_path,
                                            std::string_view expected_trading_date) {
  const bool snapshot_exists=std::filesystem::exists(snapshot_path);
  const bool manifest_exists=std::filesystem::exists(manifest_path);
  if(snapshot_exists!=manifest_exists) routing_fail(RoutingErrorCode::Partial);
  if(!snapshot_exists) routing_fail(RoutingErrorCode::Missing);
  const auto snapshot_bytes=read_regular(snapshot_path); const auto manifest_bytes=read_regular(manifest_path);
  try {
    const auto manifest_document=parse_json(manifest_bytes); const auto& manifest=json_object(manifest_document,"manifest");
    fields(manifest,{"bytes","exporter_version","record_count","requested_universe_sha256","schema_version","snapshot_file","snapshot_sha256","sources","trading_date"});
    if(string_field(manifest,"schema_version")!="1.0.0"||string_field(manifest,"exporter_version")!="1.0.0") routing_fail(RoutingErrorCode::Unsupported);
    if(string_field(manifest,"trading_date")!=expected_trading_date) routing_fail(RoutingErrorCode::Stale);
    if(string_field(manifest,"snapshot_file")!=snapshot_path.filename().string()) routing_fail(RoutingErrorCode::Tampered);
    const auto digest=string_field(manifest,"snapshot_sha256"); if(!lowercase_hex(digest)) routing_fail(RoutingErrorCode::Malformed);
    if(!lowercase_hex(string_field(manifest,"requested_universe_sha256"))) routing_fail(RoutingErrorCode::Malformed);
    const auto& manifest_sources=json_array(field(manifest,"sources"),"sources"); if(manifest_sources.size()!=2) routing_fail(RoutingErrorCode::Malformed);
    if(uint_field(manifest,"bytes")!=snapshot_bytes.size()||sha256_hex(snapshot_bytes)!=digest) routing_fail(RoutingErrorCode::Tampered);
    if(canonical_json(manifest_document)+"\n"!=manifest_bytes) routing_fail(RoutingErrorCode::Malformed);
    const auto snapshot_document=parse_json(snapshot_bytes); const auto& snapshot=json_object(snapshot_document,"snapshot");
    fields(snapshot,{"records","requested_universe_sha256","schema_version","sources","trading_date"});
    if(string_field(snapshot,"schema_version")!="1.0.0") routing_fail(RoutingErrorCode::Unsupported);
    if(string_field(snapshot,"trading_date")!=expected_trading_date) routing_fail(RoutingErrorCode::Stale);
    if(!lowercase_hex(string_field(snapshot,"requested_universe_sha256"))) routing_fail(RoutingErrorCode::Malformed);
    if(canonical_json(snapshot_document)+"\n"!=snapshot_bytes) routing_fail(RoutingErrorCode::Malformed);
    const auto& sources=json_array(field(snapshot,"sources"),"sources"); if(sources.size()!=2) routing_fail(RoutingErrorCode::Malformed);
    std::set<std::string> brokers; for(const auto& source_value:sources) { const auto& source=json_object(source_value,"source"); fields(source,{"broker","sha256"}); const auto broker=string_field(source,"broker"); if((broker!="dhan"&&broker!="kotak")||!brokers.insert(broker).second||!lowercase_hex(string_field(source,"sha256"))) routing_fail(RoutingErrorCode::Malformed); }
    if(canonical_json(JsonValue(manifest_sources))!=canonical_json(JsonValue(sources))||string_field(manifest,"requested_universe_sha256")!=string_field(snapshot,"requested_universe_sha256")) routing_fail(RoutingErrorCode::Tampered);
    InstrumentResolver resolver; resolver.digest_=digest; std::string previous; std::set<std::pair<std::string,std::string>> routes;
    const auto& records=json_array(field(snapshot,"records"),"records"); if(records.empty()||records.size()>4096U||records.size()!=uint_field(manifest,"record_count")) routing_fail(RoutingErrorCode::Malformed);
    for(const auto& record_value:records) { const auto& item=json_object(record_value,"record"); fields(item,{"canonical_instrument_id","exchange_segment","instrument_token","lot_size","tick_size_paise","trading_symbol"}); RoutingRecord record{string_field(item,"canonical_instrument_id"),string_field(item,"instrument_token"),string_field(item,"exchange_segment"),string_field(item,"trading_symbol"),uint_field(item,"lot_size"),uint_field(item,"tick_size_paise")};
      if(!is_canonical_instrument_id(record.canonical_instrument_id)||
         !bounded_route_text(record.instrument_token,64,false)||
         record.exchange_segment!="nse_fo"||
         !bounded_route_text(record.trading_symbol,128,true)||
         record.lot_size==0||record.tick_size_paise==0||
         record.lot_size>static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())||
         record.tick_size_paise>static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) routing_fail(RoutingErrorCode::Malformed);
      if(!previous.empty()&&record.canonical_instrument_id<=previous) routing_fail(RoutingErrorCode::Duplicate); previous=record.canonical_instrument_id;
      if(!routes.emplace(record.exchange_segment,record.trading_symbol).second||resolver.by_canonical_.contains(record.canonical_instrument_id)||resolver.by_token_.contains(record.instrument_token)) routing_fail(RoutingErrorCode::Duplicate);
      resolver.by_token_.emplace(record.instrument_token,record); resolver.by_canonical_.emplace(record.canonical_instrument_id,std::move(record)); }
    return resolver;
  } catch(const RoutingError&) { throw; } catch(const JsonError&) { routing_fail(RoutingErrorCode::Malformed); }
}
ResolutionResult InstrumentResolver::resolve(std::string_view canonical_instrument_id) const { const auto iterator=by_canonical_.find(std::string(canonical_instrument_id)); if(iterator==by_canonical_.end()) return {{},RoutingErrorCode::NotFound}; return {iterator->second,{}}; }
ResolutionResult InstrumentResolver::resolve_token(std::string_view instrument_token) const { const auto iterator=by_token_.find(std::string(instrument_token)); if(iterator==by_token_.end()) return {{},RoutingErrorCode::NotFound}; return {iterator->second,{}}; }
const std::string& InstrumentResolver::snapshot_digest() const noexcept { return digest_; }
}  // namespace shaurya::execution
