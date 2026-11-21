# Aegis V12

V12 is a pursuit-aware survival candidate based on V11. It keeps quiet combat and hiding, adds recovery under sustained closing pressure, holds a sheltered position briefly, and migrates toward the next zone earlier.

## What changed

During recovery or sustained pressure from multiple tracked opponents, V12 considers up to 25 short ground routes. It checks geometry, exposure along the route, and whether a moving opponent may reopen an angle at the destination. It favors the current route briefly to reduce direction changes. The search has a 3 ms soft limit.

After a recent hit below 78% HP, two tracked enemies must be within 100 m and closing at 3.5 m/s or more before V12 enters pursuit recovery. This avoids treating every low-health frame as a retreat while responding to genuine pressure.

## Tests

| Check | Result |
| --- | --- |
| Fresh paired simulation | 96 scenarios per bot, 35 survivors for V12 versus 33 for V8 |
| Mean simulated survival | V12 9.608 s and V8 9.256 s |
| Fresh holdout | V12 +0.477 s versus V8 and 20 versus 16 survivors across 48 scenarios |
| Gain by opponent | Pursuit +1.708 s, flank +0.200 s, duel 0.000 s, rotation 0.000 s |
| Final real-clock simulation | 6.202 ms maximum decision time and zero late decisions for V12 |
| Local official protocol checker | 300/300 replies on time, 11.4 ms maximum |
| Heavy synthetic workload | 300 decisions, 10.97 ms maximum and zero overruns or schema errors |
| Regression tests | 87 passed |

The model uses scripted opponents, simplified weapon and movement behavior, and 16-second scenarios. The fresh holdout gain is strong in pursuit scenarios, with no timing overruns. This is a local simulation, not an official placement score. Timing checks used one logical CPU on the local host.

## Run

The archive includes the standalone runtime and Dockerfile. For a practice trial, put `bot.py` and `Dockerfile` at the root of the existing submission repository and submit its new commit. The runtime identifies itself as `Aegis-v12`.

Run a local comparison or the regression tests from the extracted directory:

```sh
python3 tools/compare_v8.py --seed 93500 --trials 96
python3 -m unittest discover -s tests
```

The archive includes the V8 comparison runtime and all fixture files. Detailed measurements are under reports/. To regenerate the standalone bot after editing source modules, run `python3 tools/build_standalone.py`.
