# Aegis V13

V13 is a practice candidate built from V8, the 3.56 baseline. It keeps the original 12-second migration buffer. Once safely inside the next circle, it can take a short detour for a visible cube, a weapon, or a landed supply drop before continuing its rotation.

The detour needs a clear ground route and a destination inside the next circle’s safety margin. The bot declines while an emergency rotation is active, while a nearby opponent is tracked, or when a route has already failed. It considers up to six candidate routes within a soft 1.5 ms budget. Recovery still uses V8’s repair-drop checks. V8’s combat, crate farming, emergency navigation, boost and jet logic are the foundation of this build.

| Check | Result |
| --- | --- |
| Reachable uncontested resources before shrink | V13 got all 18 versus 0 for V8. By scenario end, V8 got the 12 cubes and weapons, while V13 also captured all six drops. |
| Targeted scenarios | 54 paired runs including blocked paths, elevated loot, enemies, and boundary cases. Zone damage matched in every pair. |
| Forced zone entry | Both bots chose the zone goal first and averaged 10 HP of zone damage. |
| Resource-free combat control | Both survived 30/96 and averaged 8.923 s alive. All paired survival times matched. |
| Regression tests | 91 passed. |
| Starter-kit protocol check | 300/300 on time, 12.2 ms maximum against 50 ms. |
| Heavy action checks | 300 actions, zero schema errors, 12.35 ms maximum. |

The resource simulation uses simple ground movement and scripted inputs. It measures the effect of reaching resources before the circle closes, without modeling weapon fights or long-term loot progression in those scenarios. The competition score is pending.

Put the root-level `bot.py` and `Dockerfile` into the existing practice submission repository. The runtime reports `Aegis-v13`.

From the extracted directory, reproduce the resource simulations and test suite with:

```sh
python3 tools/rotation_probe.py --output reports/rotation-local.json
python3 -m unittest discover -s tests
```

The V8 comparison runtime and fixtures are bundled. Edit the source modules and run `python3 tools/build_standalone.py` to regenerate the submission runtime. The measurements are under reports/.
