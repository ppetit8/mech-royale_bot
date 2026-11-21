# Aegis V6 — strategic goal selection

V6 replaces V5's strategic goal selector. It compares recovery, repair drops,
useful loot, cover, exploration and safe-zone rotations. A nearby safe repair
drop can now beat passive regeneration. Previously, entering recovery bypassed
all drop evaluation.

The experiment preserves V5's combat, aiming, weapon control, upgrade ranking,
navigation, local movement and action dispatch. `tools/check_scope.py` verifies
unchanged source files and method syntax trees. Only the selector, its two
state fields and the display name change. All previous versions are preserved.

## Submit

1. Extract this archive.
2. Replace **bot.py and Dockerfile** at the root of
   https://github.com/ppetit8/mech-royale_bot and commit them together.
3. Resubmit that repository URL to the Mech Royale practice track.
4. Record the exact submitted commit and the official score.

`bot.py` is the complete standalone runtime. It imports only the standard
library; old companion modules in the repository do not affect it. The Dockerfile
is unchanged from V5. No repository changes or submissions were made automatically.

The user-reported V5 control score is **3.42**, the prior reported best is
**3.46**, and the reported leading score is **5.7+**. V6 has no official score yet.
Its local checks establish behavior and decision cost, not placement improvement.

## Strategy and relevant battle-royale principles

| Principle | V6 implementation |
| --- | --- |
| Reset a losing fight | Compare sheltered recovery against the remaining time and benefit of a repair drop. |
| Anticipate an opponent's response | Reject drops an observed enemy could reach before capture completes plus a 2 s buffer; use maximum speed supported by the public upgrade catalog or faster observed motion. Reject contestable loot too. |
| Rotate before the deadline | Mandatory rotation overrides optional objectives. Optional objectives must fit the future circle and leave estimated time to reach the next one. |
| Value hard cover and exits | Sample nearby positions and building corners; score endpoint and midpoint line of sight, proximity to every tracked enemy, and verified outgoing steps. |
| Account for opportunity cost | Discount rewards by travel, waiting/capture/farming time, danger, sound sectors and low escape energy. Cubes lose much of their value after the stat cap; upgrade thresholds retain value. |
| Avoid indecision | Keep a valid current goal unless another beats it by at least 3 utility points or 15% of its utility magnitude. Re-evaluate danger and object validity; emergencies override commitment. |

These are heuristic utilities, not calibrated win probabilities or a Nash-equilibrium
solver. The opponent-response test assumes enemies can head toward the objective;
it does not depend on enemies fighting one another. That fits the cooperative
house-bot practice opponents.

Optional destinations need free ground, compatible map connectivity and a verified
direct movement segment. This deliberately rejects some objectives that would
require a detour. Mandatory rotations retain the existing navigator's detours.
Roof drops and loot more than 4 m above terrain are rejected.

The selector checks a 4 ms wall-clock budget between candidate evaluations and
considers at most 32 candidates. One evaluation can finish after that deadline.
Drops and a safe baseline receive early consideration, with some cover evaluations
ahead of loot. Under load it uses the best checked option or a survival fallback.
It normally runs at the existing 2 Hz cadence, with existing emergency overrides.

## Measured validation

Python 3.12.3 on this host; timing processes pinned to one logical CPU. The
deployment Dockerfile uses Python 3.13. Docker was unavailable, so the image build
and exact competition CPU/memory sandbox remain untested.

| Check | Result |
| --- | --- |
| Regression tests | 67 passed, including 26 new strategic/integration regressions |
| Official conformance recording | PASS; 300/300 on time; p99 11.5 ms; maximum 11.6 ms |
| Conformance protocol errors, wrong/stale ticks | 0 |
| In-process recorded replay, 900 decisions | p50 0.777 ms; p99 10.718 ms; maximum 14.019 ms |
| Synthetic combat load, 200 decisions | p50 6.873 ms; p99 12.302 ms; maximum 13.081 ms |
| Loot-heavy strategic load, 300 decisions | p50 13.115 ms; p99 13.747 ms; maximum 14.415 ms |
| Decisions over 50 ms across those four timing checks | 0 / 1,700 |
| In-process action schema errors/non-finite values | 0 |
| Map initialization in benchmark | 2462.1 ms |
| Peak benchmark process memory | 25.7 MiB |
| Scope isolation / reproducible standalone build | PASS |

The extra strategic workload forces selection on every frame, with 192 cubes,
40 pickups, 36 crates, 3 drops, up to 15 enemies and 40 projectiles, alternating
health, energy and zone emergencies. It reached the selector's time cutoff on
all 300 frames, checking at most four candidates. This demonstrates bounded
fallback behavior; it does **not** show exhaustive goal evaluation under load.

`reports/goal-comparison.json` records eight controlled V5/V6 diagnostics.
For example, with 500 HP and an uncontested landed drop 15 m away, V5 stays in
recovery while V6 chooses the drop. V6 also retains an almost-complete safe
capture, rejects an enclosed drop and keeps a loot goal through a tiny value
change. These hand-selected regressions are not a win rate or match simulator.

Raw test output, scope audit, timings and replay actions are in `reports/`.
Some strategic tests freeze the decision clock for reproducibility; the timing
and conformance measurements use the real clock.

## Run the checks

From this directory, with the unchanged official kit at `../mechfight-kit`:

```sh
python3 -m unittest discover -s tests -v
python3 ../mechfight-kit/check/check.py -- python3 -u bot.py
python3 tools/benchmark.py --output reports/local
python3 tools/strategic_load.py --output reports/strategic-local.json
```

The tests themselves create small synthetic maps and need no extra packages.
The checker and benchmarks need the official kit's arena and recorded stream.
The checker replays observations; it does not respond to the bot's actions.

With a separate preserved V5 control directory:

```sh
python3 tools/check_scope.py --baseline ../bot-v5-control
python3 tools/compare_goals.py --baseline ../bot-v5-control
```

After editing `strategy.py` or another source module, regenerate the runtime:

```sh
python3 tools/build_standalone.py
```

For an environment with Docker installed:

```sh
docker build -t aegis-v6 .
python3 ../mechfight-kit/check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --pids-limit 128 --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/../mechfight-kit/arena:/arena:ro" aegis-v6
```

## Limits and next measurement

The official kit contains no authoritative simulator. Obtain the official practice
score before calling V6 stronger. Keep the previous best submission available;
48 practice matches still introduce sampling noise. Prefer repeated runs or paired
seeds if the platform permits them, with survival time, deaths, damage and captures
to explain the score change.

Global roof routing is still incomplete. The unchanged local predictor assumes
walk speed even when boosting or charging a laser. The unchanged combat policy
can refuse farming while a tracked enemy is behind cover. Cover risk uses sampled
lines, not a full path integral, and unseen enemies remain uncertain. Under heavy
load, candidate ordering affects which goals are evaluated. These are separate
future experiments, not changes hidden in V6.

Code was developed with AI assistance. `mechfight.py` remains the unmodified
official starter wrapper. See LICENSE for the MIT license.
