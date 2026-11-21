"""Compare timed resource pickups across a shrinking-circle transition."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_bot import FIXTURE, enemy, make_world, observation, wall

DT = .1
SHRINK_END = 8.
HORIZON = 14.


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def move_on_ground(world, me, move, boost):
    stats = me['stats']
    speed = stats['boost_speed'] if boost else stats['walk_speed']
    goal = [x * speed for x in move]
    delta = [goal[i] - me['vel'][i] for i in range(2)]
    factor = min(1., stats['ground_accel'] * DT / max(math.hypot(*delta), 1e-9))
    velocity = [me['vel'][i] + delta[i] * factor for i in range(2)]
    previous = me['pos']
    for vx, vy in (velocity, [0., velocity[1]], [velocity[0], 0.]):
        x, y = previous[0] + DT * vx, previous[1] + DT * vy
        destination = [x, y, world.ground(x, y)]
        if world.walk_clear(previous, destination, stats['radius'], stats['height']):
            me.update(pos=destination, vel=[vx, vy, 0.])
            return
    me['vel'] = [0., 0., 0.]


def play(module, hello, world, seed, scenario):
    rng = random.Random(seed)
    obs = observation()
    me = obs['self']
    me.update(pos=[12, rng.uniform(-4, 4), 0.], hp=1400, vel=[0., 0., 0.])
    if scenario == 'emergency':
        me['pos'][0] = -74
    elif scenario == 'outer-rim':
        me['pos'][0] = -18
    for key in ('crates','cubes','pickups','drops','sounds','events','mechs','projectiles','beams'):
        obs[key] = []
    if scenario == 'under-pressure':
        obs['mechs'] = [enemy((5,25,0))]
    resource = {'id': 5000, 'pos': [rng.uniform(29, 34), rng.uniform(-8, 8), 0.]}
    kind = 'cubes'
    if scenario == 'weapon':
        kind = 'pickups'
        resource.update(kind='laser', id=8000)
    elif scenario == 'drop':
        kind = 'drops'
        resource.update(id=20000, radius=8, lands_in=0, holder=None, progress=0., capture_s=4.)
    elif scenario == 'outside-next':
        resource['pos'][0] = 69
    elif scenario == 'elevated':
        resource['pos'][2] = 17
    obs[kind] = [resource]
    hello = {**hello, 'seed':seed}
    with patch.object(module, 'World', return_value=world):
        bot = module.Bot(hello)
    picked = None
    zone_damage = outside_s = 0.
    capture = 0.
    last_burst = -100.
    intent = []
    peak_ms = 0.
    late = 0
    for frame in range(round(HORIZON / DT)):
        t = frame*DT
        fraction = min(1., max(0., (t-2.)/(SHRINK_END-2.)))
        center, radius = [20*fraction, 0], 66 - 23*fraction
        if t < SHRINK_END:
            next_center, next_radius, shrink_start, shrink_end = [20,0],43,2.,SHRINK_END
        else:
            next_center, next_radius, shrink_start, shrink_end = [20,0],30,24.,32.
        obs['zone'].update(center=center, radius=radius, next_center=next_center,
                           next_radius=next_radius, shrink_start=shrink_start, shrink_end=shrink_end, dps=20)
        me['in_zone'] = math.dist(me['pos'][:2],center) <= radius
        obs.update(t=t,tick=frame*2)
        start = time.perf_counter()
        action = bot.act(obs)
        elapsed_ms = (time.perf_counter()-start)*1000
        peak_ms = max(peak_ms,elapsed_ms)
        late += elapsed_ms>50
        if frame==0 or intent[-1]['kind']!=bot.goal_kind:
            intent.append(dict(t=round(t,2),kind=bot.goal_kind))
        move_on_ground(world, me, action['move'], action['boost'] and me['energy']>0)
        stats = me['stats']
        if action['boost']:
            me['energy'] = max(0.,me['energy'] - DT*stats['boost_drain'])
            last_burst = t
        elif t-last_burst >= stats['energy_regen_delay']:
            me['energy'] = min(me['max_energy'],me['energy'] + DT*stats['energy_regen'])
        if math.dist(me['pos'][:2],center) > radius:
            outside_s += DT
            zone_damage += DT*obs['zone']['dps']
        if picked is not None:
            continue
        distance = math.dist(me['pos'][:2],resource['pos'][:2])
        low_enough = abs(me['pos'][2]-resource['pos'][2]) <= 4
        if kind=='drops':
            capture = capture + DT if distance<=resource['radius'] and low_enough else 0.
            resource.update(progress=round(capture,6), holder=me['id'] if capture else None)
            acquired = capture + 1e-8 >= resource['capture_s']
        elif kind=='pickups':
            acquired = action.get('take')==resource['id']
        else:
            acquired = distance<=hello['config']['cubes']['pickup_radius'] and low_enough
        if acquired:
            picked = round(t+DT,2)
            obs[kind] = []
            if kind=='pickups':
                me['weapons'][1] = dict(kind='laser', cooldown=0, charge=0,
                                       stats=hello['config']['weapons']['laser'])
            else:
                me['cubes'] += 3 if kind=='drops' else 1
    return dict(acquired_s=picked, outside_s=round(outside_s,2),
                zone_damage=round(zone_damage,2), initial_goal=intent[0]['kind'], transitions=intent,
                maximum_decision_ms=round(peak_ms,3), late_decisions=late)


def compare(seed, repeats):
    paths = [ROOT/'tools'/'baseline'/'bot.py',ROOT/'bot.py']
    versions = {name:load(path,'rotation_'+name)
                for name,path in zip(('V8','V13'),paths)}
    scenarios = ('cube','weapon','drop','blocked','outer-rim','outside-next','elevated','under-pressure','emergency')
    rows = []
    for index,scenario in enumerate(scenarios):
        geometry = [wall(20, 24, -26, 26)] if scenario=='blocked' else []
        temporary,world = make_world(geometry)
        with temporary:
            hello = copy.deepcopy(FIXTURE['hello'])
            hello['map']['dir'] = temporary.name
            for run in range(repeats):
                case_seed = seed+index*1000+run
                rows.append(dict(scenario=scenario,seed=case_seed,
                                 **{name:play(module,hello,world,case_seed,scenario) for name,module in versions.items()}))
    def summary(name, sample):
        values = [row[name] for row in sample]
        return dict(picked_before_shrink=sum(v['acquired_s'] is not None and v['acquired_s']<=SHRINK_END for v in values),
                    picked_by_end=sum(v['acquired_s'] is not None for v in values),
                    mean_zone_damage=round(statistics.mean(v['zone_damage'] for v in values),2),
                    maximum_decision_ms=max(v['maximum_decision_ms'] for v in values),
                    late_decisions=sum(v['late_decisions'] for v in values),
                    first_goals={kind:sum(v['initial_goal']==kind for v in values)
                                 for kind in sorted({v['initial_goal'] for v in values})})
    return dict(bot_sha256=hashlib.sha256(paths[1].read_bytes()).hexdigest(),
                profile={scenario:{name:summary(name,[row for row in rows if row['scenario']==scenario])
                                   for name in versions} for scenario in scenarios},rows=rows)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=2319)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    result = compare(args.seed,args.repeats)
    if args.output:
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({key:value for key,value in result.items() if key!='rows'},indent=2))
