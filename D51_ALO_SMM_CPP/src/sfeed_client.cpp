#include "alosmm/sfeed_client.hpp"
#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/ssl/context.hpp>
#include <boost/asio/ssl/stream.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/property_tree/json_parser.hpp>
#include <boost/property_tree/ptree.hpp>
#include <openssl/ssl.h>
namespace alosmm {
namespace pt=boost::property_tree;
namespace asio=boost::asio;namespace beast=boost::beast;namespace websocket=beast::websocket;namespace pt=boost::property_tree;using tcp=asio::ip::tcp;
struct WsUrl{std::string host,port,path;};
static WsUrl parse_ws(const std::string&u){std::string s=u;auto p=s.find("://");if(p!=std::string::npos)s=s.substr(p+3);auto slash=s.find('/');std::string hp=slash==std::string::npos?s:s.substr(0,slash),path=slash==std::string::npos?"/":s.substr(slash);auto colon=hp.find(':');return {colon==std::string::npos?hp:hp.substr(0,colon),colon==std::string::npos?"443":hp.substr(colon+1),path};}
static std::string jesc2(const std::string&s){std::ostringstream o;for(char c:s){if(c=='\\'||c=='\"')o<<'\\'<<c;else o<<c;}return o.str();}
SFeedClient::SFeedClient(const Config&c,const KotakSession&s,std::vector<uint32_t>t,Callback cb):cfg_(c),session_(s),tokens_(std::move(t)),cb_(std::move(cb)){}
void SFeedClient::run(std::atomic<bool>&stop){int backoff=1;while(!stop.load()){try{std::string url=!session_.feed_url.empty()?session_.feed_url:cfg_.market_feed_url;auto w=parse_ws(url);asio::io_context ioc;asio::ssl::context ctx(asio::ssl::context::tls_client);ctx.set_default_verify_paths();ctx.set_verify_mode(asio::ssl::verify_peer);tcp::resolver res(ioc);websocket::stream<beast::ssl_stream<beast::tcp_stream>>ws(ioc,ctx);if(!SSL_set_tlsext_host_name(ws.next_layer().native_handle(),w.host.c_str()))throw std::runtime_error("SNI failed");auto ep=res.resolve(w.host,w.port);beast::get_lowest_layer(ws).connect(ep);beast::get_lowest_layer(ws).socket().set_option(tcp::no_delay(true));ws.next_layer().handshake(asio::ssl::stream_base::client);ws.set_option(websocket::stream_base::timeout::suggested(beast::role_type::client));ws.handshake(w.host,w.path);
            std::ostringstream auth;auth<<"{\"user\":\""<<jesc2(session_.ucc)<<"\",\"auth\":\""<<jesc2(session_.edit_sid)<<"\",\"format\":\"native_batch\",\"source\":\"NEOTRADEAPI\",\"platform\":\"Web\",\"version\":\"1.2.3\",\"sdk_version\":2,\"sdk_date\":\"2026-08-25\",\"conn_req_time\":"<<now_unix_ms()<<",\"sessionValidation\":false}";ws.text(true);ws.write(asio::buffer(auth.str()));
            beast::flat_buffer b;ws.read(b);if(!ws.got_text())throw std::runtime_error("unexpected binary auth response");std::string ar=beast::buffers_to_string(b.data());b.consume(b.size());
            try{
                std::istringstream iss(ar);boost::property_tree::ptree pt;boost::property_tree::read_json(iss,pt);
                const int code=pt.get<int>("message_code",0);
                if(code!=1117&&code!=1119)std::cerr<<"SFeed auth response code="<<code<<"\n";
                if(pt.get<std::string>("format","")=="native_fallback")throw std::runtime_error("SFeed downgraded to native_fallback");
                if(auto exchanges=pt.get_child_optional("exchanges")){
                    for(const auto& kv:*exchanges){
                        const auto& info=kv.second;
                        auto ex=info.get_optional<int>("value");
                        const double div=info.get<double>("divider",100.0);
                        if(ex)decoder_.set_price_divider(static_cast<int8_t>(*ex),div);
                    }
                }
            }catch(const std::runtime_error&){throw;}catch(const std::exception&e){
                std::cerr<<"SFeed auth metadata parse warning: "<<e.what()<<" response="<<ar.substr(0,240)<<"\n";
            }
            std::ostringstream inputs;for(size_t i=0;i<tokens_.size();++i){if(i)inputs<<',';inputs<<"nse_fo|"<<tokens_[i];}std::string sub="{\"event\":\"subscribeFullDepth\",\"inputtoken\":\""+inputs.str()+"\",\"ack_symbol\":true}";ws.text(true);ws.write(asio::buffer(sub));backoff=1;
            while(!stop.load()){b.consume(b.size());ws.read(b);int64_t recv=now_unix_ns();if(ws.got_text()){std::string txt=beast::buffers_to_string(b.data());if(txt.find("price")!=std::string::npos&&txt.find("divider")!=std::string::npos){/* current SDK auth metadata varies; binary precision remains authoritative */}continue;}std::string raw=beast::buffers_to_string(b.data());std::vector<uint8_t> data(raw.begin(),raw.end());for(auto&q:decoder_.decode_binary(data,recv))cb_(q);}beast::error_code ec;ws.close(websocket::close_code::normal,ec);
        }catch(const std::exception&e){if(stop.load())break;std::cerr<<"SFeed reconnect after error: "<<e.what()<<"\n";std::this_thread::sleep_for(std::chrono::seconds(backoff));backoff=std::min(30,backoff*2);}}
}

std::optional<OrderUpdate> OrderUpdateClient::parse_message(std::string_view text,int64_t recv_ts_ns){
    try{
        std::istringstream is{std::string(text)}; pt::ptree p; pt::read_json(is,p);
        if(p.get<std::string>("type","")!="order")return std::nullopt;
        auto d=p.get_child_optional("data"); if(!d)return std::nullopt;
        OrderUpdate u; u.recv_ts_ns=recv_ts_ns?recv_ts_ns:now_unix_ns();
        u.order_id=d->get<std::string>("nOrdNo",""); u.status=d->get<std::string>("ordSt",""); u.symbol=d->get<std::string>("trdSym",d->get<std::string>("sym",""));
        auto tok=d->get<std::string>("tok",""); if(!tok.empty())try{u.token=static_cast<uint32_t>(std::stoul(tok));}catch(...){u.token=0;}
        auto side=d->get<std::string>("trnsTp","B"); u.side=(side=="S"||side=="SELL")?Side::Sell:Side::Buy;
        auto num=[&](const char*k)->double{auto v=d->get<std::string>(k,"");if(v.empty())return d->get<double>(k,0.0);try{return std::stod(v);}catch(...){return 0.0;}};
        u.avg_price=num("avgPrc"); u.total_qty=static_cast<int>(num("qty")); u.filled_qty=static_cast<int>(num("fldQty")); u.remaining_qty=static_cast<int>(num("unFldSz"));
        if(u.order_id.empty())return std::nullopt;
        return u;
    }catch(...){return std::nullopt;}
}

void OrderUpdateClient::run(std::atomic<bool>&stop){if(session_.base_url.empty())return;std::string h=session_.base_url;auto p=h.find("://");if(p!=std::string::npos)h=h.substr(p+3);auto slash=h.find('/');if(slash!=std::string::npos)h=h.substr(0,slash);WsUrl w{h,"443","/realtime"};int backoff=1;while(!stop.load()){try{asio::io_context ioc;asio::ssl::context ctx(asio::ssl::context::tls_client);ctx.set_default_verify_paths();ctx.set_verify_mode(asio::ssl::verify_peer);tcp::resolver res(ioc);websocket::stream<beast::ssl_stream<beast::tcp_stream>>ws(ioc,ctx);SSL_set_tlsext_host_name(ws.next_layer().native_handle(),w.host.c_str());beast::get_lowest_layer(ws).connect(res.resolve(w.host,w.port));beast::get_lowest_layer(ws).socket().set_option(tcp::no_delay(true));ws.next_layer().handshake(asio::ssl::stream_base::client);ws.handshake(w.host,w.path);std::string auth="{type:cn,Authorization:"+session_.edit_token+",Sid:"+session_.edit_sid+",src:WEB}";ws.text(true);ws.write(asio::buffer(auth));beast::flat_buffer b;backoff=1;while(!stop.load()){b.consume(b.size());ws.read(b);if(ws.got_text()){auto txt=beast::buffers_to_string(b.data());if(auto u=parse_message(txt,now_unix_ns()))cb_(*u);}}beast::error_code ec;ws.close(websocket::close_code::normal,ec);}catch(const std::exception&e){if(stop.load())break;std::cerr<<"Order stream reconnect: "<<e.what()<<"\n";std::this_thread::sleep_for(std::chrono::seconds(backoff));backoff=std::min(30,backoff*2);}}}
} // namespace alosmm
