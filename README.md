# Aegis: Mech Royale bot

First playable, tested baseline for `mechfight/1`. Python standard library only.
It prioritizes placement, safe rotation and recovery over chasing kills. It has
not yet been scored in authoritative practice matches.

## Run and test

Python 3.12 or newer recommended (the submission image uses 3.13). From this
directory, with the official extracted kit alongside it:

```sh
python3 -m unittest discover -s tests -v
python3 ../mechfight-kit/check/check.py -- python3 -u bot.py
python3 tools/benchmark.py --kit ../mechfight-kit --output reports/local
python3 tools/navigation_benchmark.py --kit ../mechfight-kit --output reports/navigation_local.json
```

On Linux, prefix a check or benchmark command with `taskset -c 0` to pin the
checker and its bot child to one allowed CPU. Choose an allowed CPU if 0 is not
available. CPU affinity is not equivalent to the scorer's Docker CPU quota.
No package installation, network access, or virtual environment is required.

```sh
docker build -t aegis .
python3 ../mechfight-kit/check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --pids-limit 128 --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/../mechfight-kit/arena:/arena:ro" aegis
```

The Dockerfile is at this directory's top level, ready to be the root of a
submission repository. The runtime receives the map through `hello.map.dir`;
the map is not baked into the image. Tests and tools are development files,
excluded from the image. Container build/runtime validation remains pending
because Docker was unavailable in the development environment.

## Architecture

| File | Responsibility |
| --- | --- |
| `mechfight.py` | Unmodified official typed wrapper: JSON lines, latest-observation draining, flush, fallback and end handling |
| `world.py` | Bilinear height sampling, polygon holes and bridges, footprint clearance, swept cylinder checks, firing-line checks, resumable A* |
| `bot.py` | Zone forecast, safe objectives, recovery, threat-aware movement, energy reserve, loot and upgrades |
| `combat.py` | Target selection, lead and ballistics, actual-aim gates, per-weapon trigger semantics |
| `tests/` | Tactical, geometric and numerical regression scenarios |
| `tools/` | Replay timing/schema validation and closed-loop ground navigation probes |

Startup loads the terrain and 259 solid prisms and builds a 4 m ground grid
with continuous clearance values. This cost is paid in the hello budget.
Spatial buckets reduce repeated polygon checks. Ignored scenery, including
trees, never becomes a movement or projectile obstacle.

A* uses nonnegative clearance penalties, forbids diagonal corner cutting,
and caches exact checks for edges near obstacles. It advances for at most
600 heap pops / 6 ms per action and at most 8,000 closed nodes per search.
It can follow a frontier route while still searching. Targets in a separate
ground component are projected to that component's closest reachable point.
Targets unresolved within the search budget are stopped and remembered;
optional objectives are then avoided. Tactical movement is independently
checked against continuous geometry.

Strategy runs around 2 Hz, with immediate reaction to zone danger and entry
into recovery. Recovery starts below 65% HP and ends above 93%, preventing
rapid switching. It stops dealing damage as well as seeking separation:
dealing damage also resets health regeneration. Cover choices use shot geometry,
not merely distance to enemies. Future circles are interpolated from the
current circle and remaining shrink time. Safe rotation has priority over loot.

Movement scores a fixed set of directions plus stopping, predicts acceleration,
and penalizes upcoming zone exposure, projectile closest approach, nearby
lightning carriers and charging-laser lines. Recent weapon sounds contribute
weak directional risk; they never become exact target positions. Energy is
reserved for escapes. Jump/jet recovery is bounded rather than periodic.

Combat independently checks firing lines because observations include tracked
actors behind cover. Gun lead solves a constant-velocity intercept; barrel
offset is included, and unadvertised shooter-velocity inheritance is not assumed.
Mortar aim uses an iterative low arc with trajectory obstruction checks and a
self-splash safety margin. The gun waits for actual torso alignment. A laser
charges, then releases when full and aligned (or at a lethal partial charge).
Lightning requires a valid nearby target and leaves an energy reserve.
Weapon dimensions and combat/movement values come from the live configuration
and upgraded self stats. Policy weights, grid size and safety margins are tuning
parameters rather than game-rule constants.

## Test evidence and limits

See `reports/conformance.txt`, `reports/tests.txt`, `reports/final/benchmark.json`,
and `reports/navigation_final.json`. `reports/initial/` records an earlier
implementation before swept-corner and navigation refinements. Local timing
results are machine dependent. The replay has only 300 observations, 36.8 s of
match time, at most one observed actor and two projectiles. The synthetic load
adds 15 enemies and 40 projectiles; it is workload testing, not a real match.

The navigation probe feeds movement back into a simplified ground-only model
with acceleration and our own collision geometry. It compares against direct
steering, not a full opposing bot. It omits authoritative sliding, roof support,
jumping, jets, combat, loot and zone dynamics. It can reveal stuck routes; it
does not validate the server's physics or measure win rate.

Known priorities for the next iteration:

1. Obtain 48-match practice placement scores and failure observations from the
   official submission server; change one policy at a time against that baseline.
2. Add explicit roof/ground transition routes. One campus probe remains unresolved
   by the bounded ground grid. Jets currently serve as local escape, not global planning.
3. Evaluate target-velocity assumptions and mortar trajectory prediction against
   authoritative hits. Mortar currently requires an unobstructed direct target
   as well as a clear low arc; it does not blind-lob over cover.
4. Test late circles, sound inference and upgrade priorities across more streams.
   No local results establish competitive placement or a win rate yet.

No GitHub repository has been published and no track submission has been made.
