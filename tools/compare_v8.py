"""Paired local survival simulation for rapidly comparing strategy changes.

It models ground motion, perception, magazines, gun projectiles, scripted enemy
movement, health and a shrinking circle. A trial has no official placement.
"""
import argparse
import copy
from contextlib import nullcontext
import hashlib
import importlib.util
import json
import math
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_bot import FIXTURE, make_world, observation, wall

DT = .1
DURATION = 16.
REAL_CLOCK = time.perf_counter
TWO_PI = math.tau
GUN = FIXTURE['hello']['config']['weapons']['gun']
VISION = FIXTURE['hello']['config']['vision']


def load(directory, name):
    spec = importlib.util.spec_from_file_location(name, directory / 'bot.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def unit(dx, dy):
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else (0., 0.)


def angle(value):
    return (value + math.pi) % TWO_PI - math.pi


def yaw(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def gun_ray(shooter, aim, index, jitter):
    stats = shooter['stats']
    direction = [math.cos(aim[1]) * math.cos(aim[0] + jitter),
                 math.cos(aim[1]) * math.sin(aim[0] + jitter), math.sin(aim[1])]
    origin = list(shooter['pos'])
    origin[2] += stats['muzzle_height']
    origin = [x + v * (stats['radius'] + .5) for x, v in zip(origin, direction)]
    return dict(id=index, kind='gun', by=shooter['id'], pos=origin,
                vel=[value * GUN['speed'] for value in direction], remaining=GUN['range'])


def projectile_hit(origin, target, actor):
    vx, vy = (target[i] - origin[i] for i in range(2))
    dx, dy = (origin[i] - actor['pos'][i] for i in range(2))
    vv = vx*vx + vy*vy
    radius = actor['stats']['radius']
    dot = dx*vx + dy*vy
    discriminant = dot*dot - vv * (dx*dx + dy*dy - radius*radius)
    if vv <= 0 or discriminant < 0:
        return None
    delta = math.sqrt(discriminant)
    entry = max(0., (-dot - delta) / vv)
    exit = min(1., (-dot + delta) / vv)
    dz = target[2] - origin[2]
    low = actor['pos'][2]
    high = low + actor['stats']['height']
    if dz:
        lo, hi = sorted(((low-origin[2])/dz, (high-origin[2])/dz))
        entry, exit = max(entry, lo), min(exit, hi)
    elif not low <= origin[2] <= high:
        return None
    return entry if entry <= exit else None


def step_ground(world, actor, move, boost):
    stats = actor['stats']
    speed = stats['boost_speed'] if boost else stats['walk_speed']
    desired = [axis * speed for axis in move]
    delta = [desired[i] - actor['vel'][i] for i in range(2)]
    scale = min(1., stats['ground_accel'] * DT / max(math.hypot(*delta), 1e-9))
    velocity = [actor['vel'][i] + scale*delta[i] for i in range(2)]
    p = actor['pos']
    for v in (velocity, [0., velocity[1]], [velocity[0], 0.]):
        q = [p[i] + DT*v[i] for i in range(2)]
        q.append(world.ground(*q))
        if world.walk_clear(p, q, stats['radius'], stats['height']):
            actor.update(pos=q, vel=[*v, 0.])
            return v != velocity
    actor['vel'] = [0., 0., 0.]
    return True


def geometry(layout):
    if layout == 'yard':
        return [wall(-20, -11, -20, 4), wall(13, 27, 6, 22)]
    if layout == 'alleys':
        return [wall(-29, -19, -25, -8), wall(-20, -9, 11, 25), wall(10, 19, -11, 12)]
    return []


def play(module, bot_type, hello, world, seed, layout, opponent):
    rng = random.Random(seed)
    obs = observation()
    me = obs['self']
    me.update(pos=[-44, rng.uniform(-13, 13), 0.], hp=rng.choice((860, 1080, 1400)))
    actors = [me]
    if opponent == 'rotation':
        me['pos'][0] = -64
    for index in range(1 if opponent == 'duel' else 2):
        actor = copy.deepcopy(me)
        position = [-67 + rng.uniform(-5, 5), (-1)**index * rng.uniform(13, 27), 0.]
        if opponent == 'flank' and index == 1:
            position = [32, -30 + rng.uniform(-5, 5), 0.]
        actor.update(id=index + 5, pos=position, hp=800, max_hp=800,
                     aim=[yaw(position, me['pos']), 0.], vel=[0.,0.,0.])
        actors.append(actor)
    zone = obs['zone']
    initial_radius = 55 if opponent == 'rotation' else 76
    zone.update(radius=initial_radius, center=[0, 0], next_center=[20, 0],
                next_radius=43, shrink_start=6, shrink_end=16, dps=20)
    for key in ('drops', 'crates', 'cubes', 'pickups', 'sounds', 'beams', 'events'):
        obs[key] = []
    hello = {**hello, 'seed': seed}
    with patch.object(module, 'World', return_value=world):
        bot = bot_type(hello)
    seen = {}
    projectiles = []
    ammo = {a['id']: GUN['mag'] for a in actors}
    gun_ready = {a['id']: 0. for a in actors}
    reload_end = {a['id']: -1. for a in actors}
    last_combat = {a['id']: -100. for a in actors}
    last_boost = -100.
    damage_in = damage_out = zone_damage = contacts = jump_commands = cover_frames = 0
    shots = 0
    decision_ms = 0.
    late_decisions = 0
    alive_for = DURATION
    for frame in range(round(DURATION / DT)):
        now = frame * DT
        shrink = min(1., max(0., (now - 6) / 10))
        center, radius = [20*shrink, 0], initial_radius - (initial_radius - 43)*shrink
        zone.update(center=center, radius=radius)
        me['in_zone'] = math.dist(me['pos'][:2], center) <= radius
        foes = [a for a in actors[1:] if a['hp'] > 0]
        eye = [*me['pos'][:2], me['pos'][2] + me['stats']['eye_height']]
        obs['mechs'] = []
        exposed = False
        for actor in foes:
            point = [*actor['pos'][:2], actor['pos'][2] + actor['stats']['height'] / 2]
            distance = math.dist(point[:2], eye[:2])
            los = distance <= VISION['range'] and world.shot_clear(eye, point)
            if los:
                exposed = True
                within_fov = abs(angle(yaw(eye, point) - me['aim'][0])) <= math.radians(VISION['fov_deg']/2)
                if within_fov or distance <= VISION['near_range']:
                    seen[actor['id']] = now
            if now - seen.get(actor['id'], -100.) <= VISION['memory_s']:
                obs['mechs'].append({key: actor[key] for key in ('id','pos','vel','aim','hp','max_hp','cubes')}
                                    | dict(kind='mech', weapons=['gun'], charging=False))
        cover_frames += not exposed
        obs.update(t=now, tick=frame*2, alive=1+len(foes),
                   projectiles=[p for p in projectiles if p['by'] != me['id'] and
                                math.dist(p['pos'], me['pos']) <= 95])
        gun = me['weapons'][0]
        for actor in [me, *foes]:
            ident = actor['id']
            if 0 <= reload_end[ident] <= now + 1e-8:
                ammo[ident], reload_end[ident] = GUN['mag'], -1.
        gun.update(ammo=ammo[me['id']], cooldown=max(0., gun_ready[me['id']]-now),
                   reload=max(0., reload_end[me['id']]-now))
        started = REAL_CLOCK()
        action = bot.act(obs)
        elapsed = (REAL_CLOCK() - started) * 1000
        decision_ms = max(decision_ms, elapsed)
        late_decisions += elapsed > 50
        obs['events'] = []
        jump_commands += action['jump']
        controls = [(me, action['move'], action['boost'], action['aim'], action['fire'][0], action['reload'])]
        for actor in foes:
            p = actor['pos']
            distance = math.dist(p[:2], me['pos'][:2])
            source = [p[0],p[1],p[2]+actor['stats']['muzzle_height']]
            target = [me['pos'][0],me['pos'][1],me['pos'][2]+me['stats']['height']*.55]
            can_see = distance < 135 and world.shot_clear(source, target)
            bearing = yaw(p, me['pos'])
            lead = [target[i] + me['vel'][i] * distance / GUN['speed'] for i in range(3)]
            aim = [yaw(source,lead), math.atan2(lead[2]-source[2], max(1., distance))]
            move = [0., 0.]
            if opponent != 'duel' and distance > (20 if opponent == 'pursuit' else 36):
                # Seek the player, try a turn around an obstruction.
                for turn in (0, .8, -.8, 1.55, -1.55):
                    direction = [math.cos(bearing+turn), math.sin(bearing+turn)]
                    step = [p[i] + 2.5*direction[i] for i in range(2)] + [p[2]]
                    if world.walk_clear(p, step, actor['stats']['radius'], actor['stats']['height']):
                        move = [axis * (.82 if opponent == 'pursuit' else .60) for axis in direction]
                        break
            controls.append((actor, move, False, aim, can_see, ammo[actor['id']] == 0))
        for actor, move, boost, commanded, fire, reload in controls:
            ident = actor['id']
            stats = actor['stats']
            limit = stats['turn_rate'] * DT
            d_yaw = max(-limit, min(limit, angle(commanded[0]-actor['aim'][0])))
            d_pitch = max(-limit, min(limit, commanded[1]-actor['aim'][1]))
            actor['aim'] = [angle(actor['aim'][0]+d_yaw), actor['aim'][1]+d_pitch]
            if reload and reload_end[ident]<0 and ammo[ident]<GUN['mag']:
                reload_end[ident]=now+GUN['reload']
            if fire and ammo[ident] and reload_end[ident]<0 and gun_ready[ident]<=now+1e-8:
                jitter = random.Random(seed*100000 + frame*31 + ident).gauss(0., math.radians(.6 if actor is me else 1.2))
                shots += 1
                projectiles.append(gun_ray(actor, actor['aim'], shots, jitter))
                ammo[ident] -= 1
                gun_ready[ident] = now + GUN['cooldown']
            contact = step_ground(world, actor, move, boost)
            if actor is me:
                contacts += contact
                if boost:
                    me['energy']=max(0.,me['energy']-stats['boost_drain']*DT)
                    last_boost=now
                elif now-last_boost>=stats['energy_regen_delay']:
                    me['energy']=min(me['max_energy'],me['energy']+stats['energy_regen']*DT)
        pending = []
        for bullet in projectiles:
            p = bullet['pos']
            dt = min(DT, bullet['remaining'] / GUN['speed'])
            q = [p[i] + bullet['vel'][i]*dt for i in range(3)]
            targets = foes if bullet['by'] == me['id'] else [me]
            collisions = [(u, actor) for actor in targets
                          if actor['hp']>0 and (u := projectile_hit(p,q,actor)) is not None]
            if collisions:
                u, actor = min(collisions, key=lambda item:item[0])
                stop = [p[i]+u*(q[i]-p[i]) for i in range(3)]
                if world.shot_clear(p, stop):
                    rear = abs(angle(yaw(actor['pos'], p)-actor['aim'][0])) > math.pi/2
                    amount = GUN['damage'] * (1.5 if rear else 1.)
                    actor['hp'] -= amount
                    last_combat[actor['id']] = last_combat[bullet['by']] = now
                    if actor is me:
                        damage_in += amount
                        obs['events'].append(dict(type='damaged',amount=amount,weapon='gun',
                                                  by=bullet['by'],bearing=yaw(me['pos'],p),rear=rear))
                    else:
                        damage_out += amount
                        obs['events'].append(dict(type='hit',target=actor['id'],amount=amount,weapon='gun',rear=rear))
            elif bullet['remaining'] > DT*GUN['speed'] and world.shot_clear(p,q):
                bullet.update(pos=q, remaining=bullet['remaining']-DT*GUN['speed'])
                pending.append(bullet)
        projectiles = pending
        for actor in actors:
            if actor['hp'] <= 0:
                continue
            if math.dist(actor['pos'][:2], center) > radius:
                loss = DT * zone['dps']
                actor['hp'] -= loss
                last_combat[actor['id']] = now
                if actor is me:
                    zone_damage += loss
            elif now-last_combat[actor['id']] >= actor['stats']['regen_delay']:
                actor['hp'] = min(actor['max_hp'],actor['hp']+actor['stats']['regen_per_s']*DT)
        if me['hp'] <= 0:
            alive_for = (frame + 1)*DT
            break
    return dict(survived=me['hp']>0, survival_s=round(alive_for,2), hp=max(0.,round(me['hp'],1)),
                damage_in=damage_in, damage_out=damage_out, zone_damage=zone_damage, contacts=contacts,
                covered_s=round(cover_frames*DT,2), jumps_not_simulated=jump_commands,
                maximum_decision_ms=round(decision_ms,3), late_decisions=late_decisions)


def evaluate(versions, first, limit, clock, include_rotation=True):
    layouts = [('open','duel'),('yard','duel'),('alleys','duel'),('open','pursuit'),
               ('yard','pursuit'),('alleys','pursuit'),('open','flank'),('yard','flank'),('alleys','flank')]
    if include_rotation:
        layouts.extend((layout, 'rotation') for layout in ('open','yard','alleys'))
    rows = []
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as temporary:
        maps = {}
        for layout, _ in layouts:
            if layout not in maps:
                temp, world = make_world(geometry(layout))
                path = Path(temporary) / layout
                shutil.copytree(temp.name, path)
                temp.cleanup()
                maps[layout] = (path,world)
        # Fixed planning clock makes the fast comparison reproducible.
        with (patch('time.perf_counter',return_value=0) if clock == 'fixed' else nullcontext()):
            for index in range(limit):
                layout, opponent = layouts[index % len(layouts)]
                path,world = maps[layout]
                hello=copy.deepcopy(FIXTURE['hello'])
                hello['map']['dir']=str(path)
                seed=first+index
                scores={name:play(module, cls, hello, world, seed,layout,opponent) for name,module,cls in versions}
                rows.append(dict(seed=seed,layout=layout,opponent=opponent,**scores))
    def summary(label):
        values=[r[label] for r in rows]
        return dict(survivors=sum(a['survived'] for a in values),
                    mean_survival_s=round(statistics.mean(a['survival_s'] for a in values),3),
                    mean_hp=round(statistics.mean(a['hp'] for a in values),1),
                    mean_damage_in=round(statistics.mean(a['damage_in'] for a in values),1),
                    mean_damage_out=round(statistics.mean(a['damage_out'] for a in values),1),
                    mean_zone_damage=round(statistics.mean(a['zone_damage'] for a in values),1),
                    maximum_decision_ms=max(a['maximum_decision_ms'] for a in values),
                    late_decisions=sum(a['late_decisions'] for a in values))
    return dict(first_seed=first, clock=clock, trials_per_policy=len(rows), elapsed_s=round(time.perf_counter()-start,2),
                source_sha256=hashlib.sha256((ROOT/'bot.py').read_bytes()).hexdigest(),
                metrics={name:summary(name) for name,_,_ in versions}, rows=rows)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=int,default=93500)
    parser.add_argument('--trials',type=int,default=12)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error('--trials must be positive')
    baseline = load(ROOT/'tools'/'baseline','comparison_v8')
    candidate = load(ROOT,'comparison_v10')
    result = evaluate([('V8',baseline,baseline.Bot),('V10',candidate,candidate.Bot)],
                      args.seed,args.trials,'real')
    if args.output:
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({key:value for key,value in result.items() if key!='rows'},indent=2))
