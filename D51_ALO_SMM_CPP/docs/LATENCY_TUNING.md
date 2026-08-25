# Latency design and tuning

D51 ALO-SMM is deliberately not an ultra-HFT queue race. The D51 tape showed roughly sub-second-to-multi-second useful signal persistence. The implementation still avoids needless latency because stale fair value creates adverse selection.

## Hot-path architecture

- WebSocket feed thread decodes binary SFeed messages.
- decoded `Book` objects cross a preallocated SPSC ring.
- one strategy thread owns all books, signals, surfaces, model state and inventory; there are no hot-path locks.
- disk writes cross a separate SPSC queue to a stats thread.
- live order HTTP calls, when later enabled, run on a dedicated order thread using a persistent libcurl handle with HTTP/2, TCP keepalive and TCP_NODELAY; both WebSocket sockets also request TCP_NODELAY.

## Recommended AWS tuning

Shadow month first; measure before tuning.

Useful low-risk measures:

- `chrony` healthy and synchronized;
- non-burstable compute instance;
- Elastic IP/direct egress;
- `ulimit -n 65536`;
- no swap pressure;
- keep process/log files on local/persistent EBS with enough IOPS;
- avoid verbose logging on every book update;
- optional `taskset`/CPU isolation only after observing scheduler jitter.

Do not disable kernel security features or use dangerous real-time scheduling merely to chase microseconds. A 1-second decision loop makes that tradeoff irrational.

## Quote churn

A quote is not replaced merely because the model moved slightly. `update_threshold_points` defaults to one 0.05-point tick and the policy includes a churn penalty. This protects queue age and API-rate headroom.

## What to measure

`health.csv` already records maximum exchange-to-receive lag (when the exchange timestamp is usable), receive-to-strategy queue delay, surface-fit compute time and full decision-cycle compute time for each health interval. Supplement those with CloudWatch/system metrics for:

- process CPU and RSS;
- network RTT/jitter to API endpoints;
- feed reconnects;
- decoded messages/second;
- ring drops;
- feed reconnect frequency and host/network jitter;
- REST submit/response latency in later dry/live contract tests.
