# Aegis V4 — standalone runtime

## Deploy

Replace **bot.py and Dockerfile** at the root of the existing GitHub repository,
commit the update, then resubmit the repository URL on the Mech Royale track page.
V4's bot.py is self-contained and imports only the Python standard library.
Older world.py, combat.py or mechfight.py files cannot change this runtime.
The Dockerfile copies only bot.py. No third-party dependencies are needed.

## Source and build

bot.py is readable generated Python. Its source modules are included for review:

| Source | Role |
| --- | --- |
| mechfight.py | Unmodified official generated types and transport wrapper |
| world.py | V3 geometry, ground navigation and mandatory-route fallback |
| combat.py | V4 target choice, farming, defensive fire and weapon control |
| strategy.py | V4 goals, threat assessment, kiting, recovery and pickups |

After editing a source module, rebuild the single runtime:

```sh
python3 tools/build_standalone.py
```

The builder flattens source ASTs, removes local imports and intermediate main
entry points, adds the official wrapper as the runtime module, and writes one
entry point. It preserves source hashes in bot.py. It does not compress or
encode executable code. All runtime code is directly readable.

## V4 behavior

- Seek safe nearby cubes and useful weapons; hold position and scan when no
  worthwhile objective exists, instead of making random footstep-producing patrols.
- Farm an accessible crate when tracked enemies are behind solid cover, or when
  a distant unengaged enemy poses no immediate pressure. Nearby hostiles, charging
  enemies and recent attackers take priority.
- Avoid initiating distant fights with healthy opponents. Recent attackers,
  low-HP finishing opportunities and the last few survivors remain valid targets.
- Blend route direction with deliberate strafing and separation from close
  threats. Preferred spacing depends on held weapons. Keep the existing energy
  reserve and use ground boost to open distance from very close pressure.
- Replace a mortar with a nearby laser or lightning pickup while preserving the
  gun. Do not drop a charging laser.
- Preserve V3 zone forecasting, route retries, progress detection and bounded jets.

These are candidate policies, not proven score improvements. V4 has no official
practice score yet. Reported history: v1 2.50; v2 3.27; latest mixed upload 3.46.
The user reported the leading score as 5.7+. No submitted commits or match-level
records were provided. V4's standalone runtime prevents the companion-module
mismatch found when only V3's bot.py was uploaded.

## Validate locally

Keep the official extracted kit at ../mechfight-kit, or pass --kit to the tools.

```sh
python3 -m unittest discover -s tests -v
python3 ../mechfight-kit/check/check.py -- python3 -u bot.py
python3 tools/benchmark.py --output reports/local
```

The tests include a process-level hello/observation/end exchange with bot.py alone,
and with deliberately broken companion modules beside it. Both must return a
full strategy action (move, aim and fire), not a tick-only idle fallback.

On Linux, taskset -c 0 can pin a command and its child to one allowed logical CPU.
Choose an allowed CPU if 0 is unavailable. This does not reproduce Docker quotas.

```sh
docker build -t aegis-v4 .
python3 ../mechfight-kit/check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --pids-limit 128 --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/../mechfight-kit/arena:/arena:ro" aegis-v4
```

Docker is unavailable in this development environment, so image build and the
exact scorer sandbox remain untested. The assistant has not published or
submitted V4. Compare the next official result with the existing submissions.

## Additional probes and limits

The timing benchmark uses the official 300-observation recording (36.8 s) and
synthetic observations with 15 enemies and 40 projectiles. These are workload
and correctness measurements; observations do not react to actions.

The optional pursuit probe isolates movement toward loot under a single pursuer:

```sh
python3 tools/pursuit_probe.py --version ../bot-v3
python3 tools/pursuit_probe.py --version .
```

It models six seconds on flat ground with acceleration and boost energy. It omits
weapon damage, projectiles, terrain, authoritative sliding and body separation,
so zero separation means model contact, not a legal overlapping server state.
It is not a simulator for match score or combat success.

Navigation geometry is unchanged from V3; its earlier ground-only campus result
was 11/12 routes. This probe was not repeated for V4 because its navigation code
and tested movement scorer are unchanged. Full strategy behavior differs and
requires actual games. Global roof transition planning remains incomplete.

Official track and starter kit: https://www.joinbuilders.org/buildathon/tracks/builders

The original official wrapper is included unchanged as mechfight.py. The generated
runtime contains its code together with our strategy. Project code and tests were
developed with AI assistance. See LICENSE for the MIT license.
