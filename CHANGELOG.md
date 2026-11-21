# V5 control validation

This candidate intentionally restores complete V3 behavior and changes only the
display name and packaging. It is not a new strategy claimed to beat 3.46.

| Evidence | Result |
| --- | --- |
| Regression tests | 41 passed |
| AST policy definitions equivalent to V3 | 63 |
| Fixed-clock replay actions equivalent to V3 | 300/300; 0 differing actions |
| Official conformance | PASS; 300/300 on time; p50 0.8 ms; p99 9.2 ms; max 12.0 ms |
| Wrong ticks / stale responses / bad lines | 0 / 0 / 0 |
| Replay workload, 900 decisions | p99 7.272 ms; max 11.603 ms |
| Synthetic workload, 200 decisions | p99 11.656 ms; max 12.082 ms |
| Workload 50 ms overruns / schema errors | 0 / 0 |
| Initialization | 1980.4 ms |
| Peak benchmark RSS | 25.6 MiB |

Timing checks ran pinned to one logical CPU on this host. Docker sandbox tests
and an official score for this control are pending. The parity check used a
fixed clock and is deliberately separate from performance measurements.

Current reported best: 3.46. Reported V4 score: 2.98. Scored commit IDs and
match-level results have not been provided. Repository audit details and exact
observed GitHub commits are in reports/repository_audit.json.
