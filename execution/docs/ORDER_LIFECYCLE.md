# Generic order lifecycle

The executor owns one `OrderAggregate` per internal order UUID. Aggregates are keyed by canonical
instrument and retain the exact routing-snapshot digest and broker token binding. There are no
fixed option-side or buy/sell slots.

```text
prepared -> submission_started -> acknowledged -> partially_filled -> filled
                    |                   |                 |
                    v                   +------ cancel ---+-> cancelled
          ambiguous_submission --------------------------> reconciliation_required
                    |                                      |
                    +--------- authoritative reconciliation+
```

`filled`, `cancelled`, and `rejected` are terminal. Modify and cancel are pending facts layered on
an acknowledged or partially-filled order, so fills can still advance while either mutation is in
flight. A full fill wins a cancel race and is applied to position exactly once. Repeated evidence
with the same update ID and bytes is idempotent; the same update ID with different content is a
safety incident. Compatible repeated cancellation or rejection evidence with a new stable update
ID preserves the existing terminal state. An unsolicited cancel acknowledgment is an incident;
late cancel evidence after a fill is accepted only when a durable cancel request was recorded.

Submission ambiguity is never resolved by retry. Only authoritative reconciliation evidence may
move an ambiguous order into a working or terminal state. A cancel refusal or unknown outcome
retains the working exposure and enters `reconciliation_required`.

Every cumulative fill must be monotonic and no greater than the effective quantity. Modify
requests retain their requested quantity and price in the aggregate; acceptance must match those
exact terms and cannot reduce quantity below intervening cumulative fills. All illegal transitions leave the
aggregate byte-for-byte unchanged and return a stable error code.
