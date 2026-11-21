"""Verify the V6 experiment changes only goal selection and its state/name."""
import argparse
import ast
import hashlib
import json
import tempfile
from pathlib import Path

from build_standalone import build

ROOT = Path(__file__).resolve().parents[1]


def methods(source):
    bot = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'Bot')
    return {n.name: ast.dump(n, include_attributes=False) for n in bot.body if isinstance(n, ast.FunctionDef)}


def check(baseline):
    results = {}
    for name in ('world.py', 'combat.py', 'mechfight.py', 'Dockerfile'):
        results[name + '_unchanged'] = (ROOT/name).read_bytes() == (baseline/name).read_bytes()
    old = methods((baseline/'strategy.py').read_text())
    new = methods((ROOT/'strategy.py').read_text())
    results['methods_unchanged'] = {name: new.get(name) == code for name, code in old.items()
                                    if name not in ('__init__', 'strategic_goal')}
    results['no_extra_methods'] = set(new) == set(old)
    # Initialization is the same except for the two fields owned by the selector.
    trees = [ast.parse((root/'strategy.py').read_text()) for root in (baseline, ROOT)]
    inits = [next(m for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Bot'
                  for m in n.body if isinstance(m, ast.FunctionDef) and m.name == '__init__') for tree in trees]
    inits[1].body = [n for n in inits[1].body if not (isinstance(n, ast.Assign) and
                     any(isinstance(t, ast.Attribute) and t.attr in ('goal_key','goal_decision') for t in n.targets))]
    results['other_initialization_unchanged'] = ast.dump(inits[0]) == ast.dump(inits[1])
    results['generated_methods_match_source'] = methods((ROOT/'bot.py').read_text()) == new
    with tempfile.TemporaryDirectory() as folder:
        temporary = Path(folder)
        for name in ('mechfight.py','world.py','combat.py','strategy.py'):
            (temporary/name).write_bytes((ROOT/name).read_bytes())
        build(temporary)
        results['standalone_reproducible'] = (temporary/'bot.py').read_bytes() == (ROOT/'bot.py').read_bytes()
    results['bot_sha256'] = hashlib.sha256((ROOT/'bot.py').read_bytes()).hexdigest()
    results['pass'] = all(value if not isinstance(value, dict) else all(value.values())
                          for key, value in results.items() if key != 'bot_sha256')
    return results


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, default=ROOT.parent/'bot-v5-control')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = check(args.baseline)
    print(json.dumps(result, indent=2))
    if args.output:
        args.output.write_text(json.dumps(result, indent=2)+'\n')
    raise SystemExit(0 if result['pass'] else 1)
