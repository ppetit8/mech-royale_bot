# Aegis V14

V14 starts from V8, which scored 3.56 in official practice according to the reported result. V14 is a local-test candidate.

## Enemy tracking

Mech Royale continues sending a mech's current position for five seconds after it leaves view. V14 keeps each mech's last reported position for ten more seconds, with a wider estimate of where it could be as time passes. A confirmed kill clears the track. Recently lost enemies can veto crate farming and experimental weapon swaps. Combat targeting uses positions from the current observation.

## Crate farming under cover

V8 skipped farming whenever a mech was tracked. V14 can farm near one distant enemy when solid cover blocks the enemy's line to both the bot and the crate. The crate must be nearby and at ground level. Recent damage, nearby gunfire, a lost enemy that could be nearby, a zone emergency, or recovery can prevent the exception.

The mortar-to-laser swap remains available in the local probe. It reduced survival when tested by itself on both seed batches, so the default build keeps the existing pickup policy.

## Local results

The final build and V8 each played the same 60 cases at seed offset 32500.

| Metric | V8 | V14 |
| --- | ---: | ---: |
| Crates broken | 17 | 36 |
| First hunter kills | 60 | 60 |
| Total hunter kills | 114 | 118 |
| Alive at 30 seconds | 55/60 | 58/60 |
| Mean HP just after first kill | 1,016.7 | 1,049.2 |

Guarded farming also improved survival in the earlier 30- and 60-case batches. On the 60-case validation batch, the covered-crate layout improved from 8/12 to 11/12 alive, with one cube before first contact on every run versus zero for V8. Results for the open-crate and no-loot layouts matched V8 in this batch.

The probe covers five scripted flat-ground layouts and two waves of gun hunters. It uses simplified weapon and movement physics and omits real arena rotations, opponents with mixed loadouts, and the full 15-hunter practice match. Enemy memory is bundled with guarded farming. The experiment leaves its individual contribution unmeasured.

V14 passed all 87 regressions and answered all 300 observations from the official starter checker within 50 ms. The checker peaked at 12.6 ms, and the 300-frame synthetic loot and threat stress test peaked at 13.9 ms. These are local timings.

## Run and reproduce

Use the root-level `bot.py` and `Dockerfile` in the submission repository. The runtime identifies itself as `Aegis-v14`. The generated bot only imports the Python standard library.

```sh
python3 -m unittest discover -s tests -v
python3 tools/wave_probe.py --seed 32500 --trials 12 --variant release
python3 tools/wave_probe.py --seed 22500 --trials 12
```

The second probe command compares farming, swapping, and both combined to the bundled V8 baseline. Use `--output path.json` to save individual cases and breakdowns by layout. The pilot, validation, final-build runs, and checker output are under `reports/`.

With the official starter kit extracted beside this folder:

```sh
python3 ../mechfight-kit/check/check.py -- python3 -u bot.py
python3 tools/strategic_load.py --kit ../mechfight-kit
```

Edit the source modules and run `python3 tools/build_standalone.py` to regenerate `bot.py`.
