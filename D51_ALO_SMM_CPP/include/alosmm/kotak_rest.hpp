#pragma once
#include "config.hpp"
#include <curl/curl.h>
namespace alosmm {
struct KotakSession {
    std::string consumer_key,ucc,view_sid,view_token,edit_sid,edit_token,base_url,data_center,feed_url;
    bool valid{false};
};
class HttpClient {
public:
    HttpClient(); ~HttpClient(); HttpClient(const HttpClient&)=delete;HttpClient&operator=(const HttpClient&)=delete;
    struct Response{long status{0};std::string body;double total_ms{0};};
    Response post(const std::string& url,const std::vector<std::string>& headers,const std::string& body,const std::string& content_type);
private:CURL* curl_{nullptr};
};
class KotakRestClient {
public:
    explicit KotakRestClient(const Config& c):cfg_(c){}
    KotakSession login();
    std::string place_order(const KotakSession&,const OrderIntent&);
    std::string modify_order(const KotakSession&,const OrderIntent&);
    void cancel_order(const KotakSession&,const OrderIntent&);
    static std::string generate_totp(std::string base32_secret,int64_t unix_seconds=0);
private:
    std::vector<std::string> order_headers(const KotakSession&)const;
    Config cfg_; HttpClient http_;
};
} // namespace alosmm
