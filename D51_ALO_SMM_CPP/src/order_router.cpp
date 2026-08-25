#include "alosmm/order_router.hpp"
#include <cctype>
namespace alosmm {
void LiveGate::require(const Config&cfg){if(cfg.mode!=Mode::Live)return;if(!compiled())throw std::runtime_error("LIVE BLOCKED: rebuild with -DALO_ENABLE_LIVE_ROUTER=ON");if(env_or(cfg.live_ack_env)!=cfg.live_ack_phrase)throw std::runtime_error("LIVE BLOCKED: missing exact live-order acknowledgement");if(env_or(cfg.live_flat_ack_env)!=cfg.live_flat_ack_phrase)throw std::runtime_error("LIVE BLOCKED: startup-flat acknowledgement missing; reconcile broker positions before enabling live");}
OrderRouter::OrderRouter(const Config&c,const KotakSession&s):cfg_(c),session_(s),rest_(c){}
OrderRouter::~OrderRouter(){stop();}
void OrderRouter::start(){if(cfg_.mode!=Mode::Live)return;LiveGate::require(cfg_);if(running_.exchange(true))return;th_=std::thread([this]{run();});}
void OrderRouter::stop(){if(!running_.exchange(false))return;if(th_.joinable())th_.join();}
bool OrderRouter::submit_desired(const OrderIntent&i){if(cfg_.mode!=Mode::Live)return false;if(!q_.push(i)){++rejected_;return false;}return true;}
void OrderRouter::rate_limit(){auto now=Clock::now();while(!sent_.empty()&&now-sent_.front()>std::chrono::seconds(1))sent_.pop_front();if(static_cast<int>(sent_.size())>=cfg_.max_orders_per_second){auto wait=std::chrono::seconds(1)-(now-sent_.front())+Ms(2);if(wait>Ms(0))std::this_thread::sleep_for(wait);now=Clock::now();while(!sent_.empty()&&now-sent_.front()>std::chrono::seconds(1))sent_.pop_front();}sent_.push_back(Clock::now());}

void OrderRouter::on_order_update(const OrderUpdate&u){
    // Preserve single-writer ownership of working_: only the router thread mutates it.
    if(!updates_.push(u))throw std::runtime_error("LIVE SAFETY STOP: router order-update queue overflow");
}

void OrderRouter::run(){OrderIntent in;OrderUpdate up;while(running_){
    while(updates_.pop(up)){
        std::string st=up.status;std::transform(st.begin(),st.end(),st.begin(),[](unsigned char c){return static_cast<char>(std::tolower(c));});
        const bool terminal=st=="complete"||st=="cancelled"||st=="canceled"||st=="rejected";
        if(terminal)for(auto&w:working_)if(!w.id.empty()&&w.id==up.order_id){w={};break;}
    }
    if(!q_.pop(in)){std::this_thread::sleep_for(Ms(1));continue;}try{auto&w=working_[key(in.cp,in.side)];if(in.kind==OrderIntent::Kind::Cancel||in.price<=0||in.quantity<=0){if(!w.id.empty()){rate_limit();OrderIntent c=in;c.existing_order_id=w.id;rest_.cancel_order(session_,c);w={};}continue;}if(!w.id.empty()&&(w.token!=in.token||w.symbol!=in.symbol)){rate_limit();OrderIntent c=in;c.existing_order_id=w.id;c.kind=OrderIntent::Kind::Cancel;rest_.cancel_order(session_,c);w={};}if(w.id.empty()){rate_limit();auto id=rest_.place_order(session_,in);w={id,in.price,in.quantity,in.symbol,in.token};}else if(std::abs(w.price-in.price)>1e-9||w.qty!=in.quantity){rate_limit();OrderIntent m=in;m.existing_order_id=w.id;rest_.modify_order(session_,m);w.price=in.price;w.qty=in.quantity;}}catch(const std::exception&e){std::cerr<<"ORDER ROUTER ERROR: "<<e.what()<<"\n";}}
    // Cancel all outstanding quotes before exit.
    for(size_t k=0;k<working_.size();++k){auto&w=working_[k];if(w.id.empty())continue;try{OrderIntent c;c.cp=static_cast<CP>(k/2);c.side=static_cast<Side>(k%2);c.existing_order_id=w.id;c.kind=OrderIntent::Kind::Cancel;rate_limit();rest_.cancel_order(session_,c);}catch(...){ }w={};}}
} // namespace alosmm
