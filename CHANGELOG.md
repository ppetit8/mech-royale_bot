# V4 candidate: evidence and score ledger

## Reported scores

| Upload | Score |
| --- | --- |
| v1 | 2.50 |
| v2 | 3.27 |
| Latest bot-only V3 upload with older world.py | 3.46 |
| Complete V3 | Unmeasured |
| V4 | Unmeasured |

The reported leader is 5.7+. Repository commits and match-level logs are unknown.
The local V3 bot / V2 world combination raises a navigator argument TypeError.
V4 prevents that specific mismatch through one self-contained runtime.

## Final measured checks

| Check | Result |
| --- | --- |
| Regression suite | 50 passed, including standalone and obsolete-module protocol tests |
| Official conformance | 300/300 on time; p50 1.1 ms; p99 11.7 ms; max 14.0 ms |
| Bad lines / wrong ticks / stale replies | 0 / 0 / 0 |
| Replay, 900 decisions | p99 9.655 ms; max 13.23 ms |
| Synthetic load, 200 decisions | p99 15.006 ms; max 15.099 ms |
| Workload budget overruns / schema errors | 0 / 0 |
| Initialization | 2512.9 ms |
| Peak benchmark RSS | 25.5 MiB |

Conformance and timing benchmarks ran pinned to one logical CPU on this host.
Container CPU quota and Docker filesystem/network isolation were not available.

## Six-second movement-only probe

| Version | Minimum separation | Final separation | Boost energy spent |
| --- | --- | --- | --- |
| Complete V3 | 0.0 m | 0.0 m | 0 |
| V4 | 29.42 m | 33.13 m | 74.8 |

The probe includes a visible cube toward a constant-speed pursuing opponent on
flat ground. It applies movement acceleration and energy drain/regeneration.
There is no damage, weapon model, collision push-apart, zone pressure, map
navigation, or opponent decision model. These values demonstrate movement policy
in that constructed scenario, not a practice score, win probability, or measured
combat survival. In particular, V3's zero separation is model contact.

The 10 new test scenarios cover quiet holding, collecting visible cubes, retreat
with an energy reserve, replacing a mortar, preserving a charging laser, farming
past hidden tracked enemies, farming before a distant neutral target, prioritizing
immediate hostiles, responding to a distant attacker, and isolated single-file
protocol operation with obsolete modules present.

Deploy bot.py and Dockerfile together. Preserve prior submissions and compare the
next official score before drawing a conclusion about V4 strength.
