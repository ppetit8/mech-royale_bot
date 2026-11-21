# Aegis V10

V10 is a practice candidate based on V8, whose reported score is 3.56. It selects short retreat routes against threats on the same side and falls back to V8’s route selection when nearby opponents are on opposite sides.

## What changed

During recovery or sustained pressure from multiple tracked opponents, V10 considers up to 25 short ground routes. It checks geometry, exposure along the route, and whether a moving opponent may reopen an angle at the destination. It favors the current route briefly to reduce direction changes. The search has a 3 ms soft limit. The zone and repair drop decisions run first. V8 supplies the original recovery threshold, combat, boost, jet and ordinary goal handling. This build leaves out the experimental cover pause and earlier recovery trigger.

Two additional forecast weights for the middle of the retreat were screened on 48 paired scenarios. Both produced the same measured outcomes as the simpler planner. The package uses the simpler one.

## Tests

| Check | Result |
| --- | --- |
| Fresh paired simulation | 96 scenarios per bot, 35 survivors for V10 versus 33 for V8 |
| Mean simulated survival | V10 9.608 s and V8 9.256 s |
| Paired gain | +0.352 s with a 95% bootstrap interval of +0.108 to +0.630 s |
| Gain by opponent | Pursuit +1.392 s, flank +0.029 s, duel 0.000 s, rotation −0.013 s |
| Final real-clock simulation | 5.40 ms maximum decision time and zero late decisions for V10 |
| Local official protocol checker | 300/300 replies on time, 11.4 ms maximum |
| Heavy synthetic workload | 300 decisions, 10.97 ms maximum and zero overruns or schema errors |
| Regression tests | 86 passed |

The model uses scripted opponents, simplified weapon and movement behavior, and 16-second scenarios. Simulation suggests a modest pursuit benefit. V10’s official placement score is pending. The measured overall gain was below the lab’s +0.5 s promotion threshold, so V8 remains the recorded practice baseline. Timing checks used one logical CPU on the local host. The exact competition container has yet to be measured.

## Run

The archive includes the standalone runtime and Dockerfile. For a practice trial, put `bot.py` and `Dockerfile` at the root of the existing submission repository and submit its new commit. The runtime identifies itself as `Aegis-v10`.

Run a local comparison or the regression tests from the extracted directory:

```sh
python3 tools/compare_v8.py --seed 93500 --trials 96
python3 -m unittest discover -s tests
```

The archive includes the V8 comparison runtime and all fixture files. Detailed measurements are under reports/. To regenerate the standalone bot after editing source modules, run `python3 tools/build_standalone.py`.
