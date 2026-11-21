# Aegis V5 control — V3 policy, standalone runtime

This is a rollback/control build after V4's reported score fell to 2.98. It
restores the complete V3 decision policy and keeps the single-file packaging
introduced in V4. The display name is Aegis-v5-control. There are no intentional
new tactical improvements in this candidate.

## Deploy

Replace **bot.py and Dockerfile** in the existing GitHub repository, commit, and
resubmit its repository URL. bot.py contains the entire runtime. Older companion
modules beside it cannot affect the deployed behavior. Preserve the existing
best-scoring submission and record the exact scored commit for each new run.

## What the repository audit established

Repository: https://github.com/ppetit8/mech-royale_bot

- Current commit 09987a453e4a22cabc0172af7fd459c49363a113 contains the supplied V4
  standalone runtime and a Dockerfile that copies and runs that bot.py.
- Commit 57eb6150f2f3bf7395c25264c0317d9c43f55f7b contains both the compatible V3
  bot and V3 world module. Their UI-visible source matches our preserved sources.
- The precise submission commit IDs corresponding to user-reported scores are
  still unknown. Thus the earlier claim that 3.46 probably represented idle
  fallback was too strong. The supplied mixed V3-bot/V2-world combination does
  fail locally, but the repository history includes a corrected compatible pair.
- The user reported V4 at 2.98, below the prior reported best of 3.46. The score
  alone does not isolate which V4 policy changes caused that regression.

The audit was read-only. No GitHub changes or track submissions were made by the
assistant. Details and source consistency fingerprints are in reports/.

## Validation

- 41 regression tests pass, including a process-level exchange with deliberately
  broken companion modules beside the standalone runtime.
- The source ASTs of 63 functions/classes match complete V3, excluding the display
  name. All 300 replay actions match V3 under a fixed decision clock.
- Separate wall-clock conformance and benchmark results are in reports/.

The fixed clock in the parity test permits a deterministic comparison of bounded
path search logic. It is not a latency measurement or proof that every action
will match in real games; wall-time scheduling, runtime environment and match
observations still vary.

With the official extracted kit alongside this directory:

```sh
python3 -m unittest discover -s tests -v
python3 ../mechfight-kit/check/check.py -- python3 -u bot.py
python3 tools/benchmark.py --output reports/local
```

Optional policy parity check requires a separate preserved complete V3 directory:

```sh
python3 tools/check_parity.py --baseline ../bot-v3 --output reports/parity_local.json
```

Readable source modules are included: strategy.py, combat.py, world.py and the
unmodified official mechfight.py wrapper. After editing a source module:

```sh
python3 tools/build_standalone.py
```

The generated bot.py is readable Python and imports only the standard library.
It includes source hashes and one entry point.

## Docker check

```sh
docker build -t aegis-control .
python3 ../mechfight-kit/check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --pids-limit 128 --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/../mechfight-kit/arena:/arena:ro" aegis-control
```

Docker was unavailable here; the exact scorer sandbox remains unverified. Local
CPU affinity is not equivalent to Docker's CPU quota. No new official score has
been obtained for this control build.

## Limits and next experiment

The official checker is a recorded observation stream, not a game simulator.
Replay and synthetic tests establish protocol correctness, parity and workload
cost, not placement strength. Global roof routing remains incomplete, and V3's
previous ground probe completed 11/12 routes. Navigation was not changed or
retested in this packaging-only control.

Establish the control score first. Then change one policy per candidate, keeping
commit-to-score records and any available match breakdown. V4's flat-ground
pursuit probe did not predict the official regression, so it is insufficient as
an optimization objective.

The user reported a 5.7+ leading score. This remains a target, not a result of
any of our local tests. Official track:
https://www.joinbuilders.org/buildathon/tracks/builders

Code was developed with AI assistance. mechfight.py is the unmodified official
starter wrapper. See LICENSE for the MIT license.
