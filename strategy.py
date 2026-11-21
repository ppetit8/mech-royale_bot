"""Aegis: survival-first mechfight/1 bot. Standard library only."""
import math
import random
import time

import mechfight as mf
from combat import Combat, unit, wrap
from world import Navigator, World


def future_zone(zone, now, future):
    start, end = zone['shrink_start'], zone['shrink_end']
    if end <= now:
        return zone['next_center'], zone['next_radius']
    fraction = max(0, min(1, (future - max(start, now)) / max(.001, end - max(start, now))))
    return ([zone['center'][i] + (zone['next_center'][i] - zone['center'][i]) * fraction for i in range(2)],
            zone['radius'] + (zone['next_radius'] - zone['radius']) * fraction)


class Bot:
    name = 'Aegis-survivor-v4'

    def __init__(self, hello):
        self.cfg = hello['config']
        self.rng = random.Random(hello['seed'])
        self.world = World(hello['map']['dir'], self.cfg)
        self.nav = Navigator(self.world)
        self.combat = Combat(self.cfg, self.world)
        self.recovering = False
        self.goal = None
        self.goal_until = -1
        self.goal_kind = 'explore'
        self.last_damage = -100
        self.last_pos = None
        self.stuck = 0
        self.jet_until = -1
        self.side = self.rng.choice((-1, 1))
        self.loot = {}
        self.last_move = [0, 0]
        self.mode = 'explore'
        self.heard = []
        self.avoid_goals = []
        self.progress = None
        self.pressure = None

    def assess_pressure(self, obs, threats):
        me = obs['self']; p = me['pos']
        source = [p[0], p[1], p[2] + me['stats']['eye_height']]
        for enemy in threats[:4]:
            d = math.dist(p[:2], enemy['pos'][:2])
            if d > 120:
                continue
            bearing = math.atan2(p[1] - enemy['pos'][1], p[0] - enemy['pos'][0])
            hostile = d < 55 or enemy.get('charging') or abs(wrap(bearing - enemy['aim'][0])) < .6 or obs['t'] - self.last_damage < 1.2
            target = enemy['pos'][:]
            target[2] += self.cfg['mech']['height'] * (1 + self.cfg['cubes']['size_per_cube'] * enemy.get('cubes', 0)) * .5
            if hostile and self.world.shot_clear(source, target):
                return enemy
        return None

    def combat_direction(self, obs, desired):
        """Escape short-range threats while keeping a controlled firing orbit."""
        me = obs['self']; enemy = self.pressure
        away = unit([me['pos'][0] - enemy['pos'][0], me['pos'][1] - enemy['pos'][1]])
        distance = math.dist(me['pos'][:2], enemy['pos'][:2])
        held = [w for w in me['weapons'] if w]
        lightning = next((w for w in held if w['kind'] == 'lightning'), None)
        if lightning and me['energy'] > 35 and 'mortar' not in enemy.get('weapons', []):
            preferred = lightning['stats']['range'] - 9
        elif any(w['kind'] == 'laser' for w in held):
            preferred = 110
        else:
            preferred = 85
        if 'lightning' in enemy.get('weapons', []) and lightning is None:
            preferred = max(preferred, self.cfg['weapons']['lightning']['range'] + 25)
        radial = max(0, min(1.5, (preferred - distance) / 25))
        tangent = [-away[1] * self.side, away[0] * self.side]
        route = unit(desired)
        return unit([route[i] * .3 + away[i] * radial + tangent[i] * .8 for i in range(2)])

    def zone_goal(self, me, center, radius, preferred):
        """Project rotations onto free ground inside the intended safe circle."""
        w = self.world; body = me['stats']['radius']; height = me['stats']['height']
        candidates = [preferred, center]
        for i in range(8):
            a = i * math.pi / 4
            candidates.append([center[0] + radius * .65 * math.cos(a),
                               center[1] + radius * .65 * math.sin(a)])
        valid = []
        for q in candidates:
            n = w.nearest(q, body)
            if n is None:
                continue
            xy = list(w.xy(n))
            if math.dist(xy, center) <= radius and w.clear_at(*xy, w.ground(*xy), height) >= body + .4:
                valid.append(xy)
                # Usually one cheap projection is sufficient.
                if q is preferred:
                    return xy
        if valid:
            return min(valid, key=lambda q: math.dist(me['pos'][:2], q))
        return list(preferred)

    def exposure(self, point, threats, height):
        risk = 0
        top = [point[0], point[1], self.world.ground(*point[:2]) + height * .55]
        for e in threats[:5]:
            d = math.dist(point[:2], e['pos'][:2])
            if d > 230:
                continue
            source = e['pos'][:]; source[2] += self.cfg['mech']['muzzle_height']
            if self.world.shot_clear(source, top):
                risk += 100 / (d + 15)
        return risk

    def strategic_goal(self, obs, threats, urgent):
        me = obs['self']; p = me['pos']; now = obs['t']; zone = obs['zone']
        walk = me['stats']['walk_speed']
        center, radius = future_zone(zone, now, now + 20)
        next_c = zone['next_center']; next_r = zone['next_radius']
        dist_next = max(0, math.dist(p[:2], next_c) - next_r + 20)
        migrate = urgent or dist_next / walk * 1.7 + 12 > zone['shrink_end'] - now
        if migrate:
            center, radius = next_c, next_r
        margin = min(25, radius * .2)
        safe_r = max(0, radius - margin)
        if migrate or math.dist(p[:2], center) > safe_r:
            toward = unit([p[0] - center[0], p[1] - center[1]])
            goal = [center[0] + toward[0] * safe_r * .8, center[1] + toward[1] * safe_r * .8]
            self.goal_kind = 'zone'
            return self.zone_goal(me, center, max(0, radius - me['stats']['radius']), goal)
        if self.recovering or len(threats) >= 2:
            candidates = [p[:2]]
            for distance in (20, 45):
                for i in range(8):
                    a = i * math.pi / 4
                    q = [p[0] + distance * math.cos(a), p[1] + distance * math.sin(a)]
                    if math.dist(q, center) <= safe_r and self.world.clear_at(*q, self.world.ground(*q), me['stats']['height']) > me['stats']['radius'] + 1:
                        candidates.append(q)
            def score(q):
                near = sum(max(0, 75 - math.dist(q, e['pos'][:2])) / 20 for e in threats)
                return self.exposure(q, threats, me['stats']['height']) * 4 + near + math.dist(q, p[:2]) * .012
            goal = min(candidates, key=score)
            self.goal_kind = 'recover' if self.recovering else 'disengage'
            return goal
        best = None
        held = [w['kind'] for w in me['weapons'] if w]
        empty = len(held) < 2
        for obj, seen, kind in self.loot.values():
            q = obj['pos']; d = math.dist(q[:2], p[:2])
            if any(math.dist(q[:2], blocked) < 12 for blocked in self.avoid_goals):
                continue
            if now - seen > 18 or d > 115 or abs(q[2] - self.world.ground(*q[:2])) > 4:
                continue
            if math.dist(q[:2], center) > safe_r:
                continue
            danger = sum(max(0, 80 - math.dist(q[:2], e['pos'][:2])) / 12 for e in threats)
            useful_weapon = kind == 'weapon' and obj['kind'] not in held and (empty or ('mortar' in held and obj['kind'] in ('laser', 'lightning')))
            value = 85 if kind == 'cube' else (125 if useful_weapon else 0)
            if kind == 'crate' and not threats and me['cubes'] < 10:
                value = 35
            score = value / (d + 18) - danger
            if score > 0 and (best is None or score > best[0]):
                if kind == 'crate':
                    away = unit([p[0] - q[0], p[1] - q[1]])
                    q = [q[0] + away[0] * 18, q[1] + away[1] * 18]
                best = (score, q[:2], kind)
        for drop in obs.get('drops', []):
            q = drop['pos']; d = math.dist(q[:2], p[:2])
            if d < 100 and drop['lands_in'] < d / walk + 5 and math.dist(q[:2], center) < safe_r:
                if all(math.dist(e['pos'][:2], q[:2]) > 100 for e in threats):
                    score = (200 if me['hp'] < me['max_hp'] * .8 else 100) / (d + 20)
                    if best is None or score > best[0]:
                        best = (score, q[:2], 'drop')
        if best:
            self.goal_kind = best[2]
            return best[1]
        if self.goal is not None and now < self.goal_until and math.dist(p[:2], self.goal) > 6 and math.dist(self.goal, center) <= safe_r:
            return self.goal
        # With no worthwhile objective, stay quiet and scan. Random patrols
        # create footsteps and unnecessary exposure without guaranteed loot.
        if not threats and now - self.last_damage > 3:
            self.goal_kind = 'hold'; self.goal_until = now + 2
            return p[:2]
        # A short relocation remains available when tracked threats are nearby.
        for _ in range(12):
            angle = self.rng.uniform(-math.pi, math.pi)
            q = [p[0] + 65 * math.cos(angle), p[1] + 65 * math.sin(angle)]
            if math.dist(q, center) <= safe_r and self.world.nearest(q, me['stats']['radius']) is not None and all(math.dist(q, blocked) >= 12 for blocked in self.avoid_goals):
                self.goal_kind = 'explore'; self.goal_until = now + 10
                return q
        self.goal_kind = 'hold'
        return center[:]

    def movement(self, obs, desired, threats, urgent, deadline):
        me = obs['self']; p = me['pos']; s = me['stats']; now = obs['t']; radius = s['radius']; height = s['height']
        desired = unit(desired)
        center, safe_radius = future_zone(obs['zone'], now, now + 2)
        candidates = [[0., 0.], desired]
        base = math.atan2(desired[1], desired[0])
        for i in range(16):
            angle = base + i * math.pi / 8
            candidates.append([math.cos(angle), math.sin(angle)])
        best = (-math.inf, [0, 0])
        ground_map = abs(p[2] - self.world.ground(*p[:2])) < 2
        for move in candidates:
            if time.perf_counter() > deadline:
                break
            # Integrate acceleration for the first 0.4 s instead of assuming instant reversal.
            horizon = .4
            accel = s['ground_accel'] if me['grounded'] else s['air_accel']
            predicted = []
            for i in range(2):
                target_v = move[i] * s['walk_speed']
                dv = max(-accel * horizon, min(accel * horizon, target_v - me['vel'][i]))
                predicted.append(p[i] + (me['vel'][i] + .5 * dv) * horizon)
            q = [*predicted, self.world.ground(*predicted) if ground_map else p[2]]
            if not self.world.walk_clear(p, q, radius, height, ground_map):
                continue
            score = 2 * sum(move[i] * desired[i] for i in range(2))
            if math.hypot(*desired) > .1:
                score += .15 * sum(move[i] * self.last_move[i] for i in range(2))
            else:
                score -= math.hypot(*move) * 2
            outside = max(0, math.dist(predicted, center) - max(0, safe_radius - min(4, safe_radius * .1)))
            score -= outside * (2 + obs['zone']['dps'] / 40)
            velocity = [(q[i] - p[i]) / horizon for i in range(2)] + [me['vel'][2]]
            for projectile in obs['projectiles'][:40]:
                rp = [projectile['pos'][i] - p[i] for i in range(3)]
                rv = [projectile['vel'][i] - velocity[i] for i in range(3)]
                if projectile['kind'] == 'mortar':
                    # Ballistic impact proximity, including the vertical cylinder extent.
                    for t in (.15, .35, .6):
                        z = rp[2] + rv[2] * t - .5 * self.cfg['weapons']['mortar']['gravity'] * t * t
                        dist = math.hypot(rp[0] + rv[0] * t, rp[1] + rv[1] * t)
                        if -3 < z < height + 3:
                            score -= max(0, radius + self.cfg['weapons']['mortar']['splash_radius'] + 2 - dist) * 2
                else:
                    vv = rv[0] ** 2 + rv[1] ** 2
                    t = max(0, min(.65, -(rp[0] * rv[0] + rp[1] * rv[1]) / (vv or 1)))
                    z = rp[2] + rv[2] * t
                    if -.3 < z < height + .3:
                        d = math.hypot(rp[0] + rv[0] * t, rp[1] + rv[1] * t)
                        score -= max(0, radius + 1.2 - d) * 4
            for e in threats[:5]:
                dist = math.dist(predicted, e['pos'][:2])
                away = unit([p[0] - e['pos'][0], p[1] - e['pos'][1]])
                if dist < 120:
                    prefer = 70 if 'lightning' in e.get('weapons', []) else 45
                    score -= max(0, prefer - dist) * (.12 if self.recovering else .04)
                    side = [-away[1] * self.side, away[0] * self.side]
                    score += .65 * sum(move[i] * side[i] for i in range(2))
                    if e.get('charging'):
                        yaw = math.atan2(predicted[1] - e['pos'][1], predicted[0] - e['pos'][0])
                        score -= 5 * max(0, .12 - abs(wrap(yaw - e['aim'][0]))) / .12
            for bearing, weight, heard_at in self.heard[-6:]:
                # Sound gives a noisy sector, never an exact actor or firing solution.
                toward = move[0] * math.cos(bearing) + move[1] * math.sin(bearing)
                score -= max(0, toward) * weight * max(0, 1 - (now - heard_at) / 3)
            if score > best[0]:
                best = score, move
        return best[1]

    def pick_upgrade(self, obs):
        # Known IDs are policy preferences; unknown future IDs are ranked by effects.
        ranks = {'servos': 100, 'nanites': 95, 'plating': 90, 'armor': 88, 'reactor': 80,
                 'gun_mag': 76, 'gun_velocity': 74, 'laser_charge': 73, 'laser_damage': 72,
                 'gun_damage': 70, 'lightning_range': 69, 'capacitor': 68, 'jets': 66,
                 'gun_rate': 65, 'gyros': 64, 'sensors': 58, 'lightning_efficiency': 56,
                 'mortar_reload': 53, 'mortar_velocity': 52, 'mortar_splash': 50,
                 'lightning_chain': 35, 'laser_pierce': 30}
        if obs['self']['hp'] < obs['self']['max_hp'] * .6:
            ranks['plating'] = 110
        choices = obs['offer']['choices']
        return max(range(len(choices)), key=lambda i: ranks.get(choices[i]['id'], 45))

    def act(self, obs):
        begin = time.perf_counter()
        me = obs['self']; p = me['pos']; now = obs['t']; s = me['stats']
        self.heard = [sound for sound in self.heard if now - sound[2] < 3]
        for sound in obs['sounds']:
            if sound['kind'] in ('gun', 'laser', 'laser_charge', 'mortar', 'lightning') and sound['dist'] != 'far':
                self.heard.append((sound['bearing'], .65 if sound['dist'] == 'near' else .2, now - sound['age']))
        for e in obs['events']:
            if e['type'] == 'damaged' and e.get('weapon') != 'zone':
                self.last_damage = now
        for key, kind in (('cubes', 'cube'), ('pickups', 'weapon'), ('crates', 'crate')):
            for obj in obs[key]:
                self.loot[obj['id']] = (obj, now, kind)
        self.loot = {i: item for i, item in self.loot.items() if now - item[1] < 18
                     and not (math.dist(item[0]['pos'][:2], p[:2]) < 4 and item[1] < now - .5)}
        if me['hp'] < me['max_hp'] * .65:
            self.recovering = True
        if me['hp'] >= me['max_hp'] * .93:
            self.recovering = False
        threats = sorted((e for e in obs['mechs'] if e['kind'] == 'mech'), key=lambda e: math.dist(p[:2], e['pos'][:2]))
        self.pressure = self.assess_pressure(obs, threats)
        center, r = future_zone(obs['zone'], now, now + 12)
        urgent = not me['in_zone'] or math.dist(p[:2], center) > max(0, r - min(12, r * .15))
        # Recompute expensive strategic choices at 2 Hz, but react to zone/damage immediately.
        if self.nav.failed_goal is not None and self.goal_kind not in ('zone', 'recover', 'disengage'):
            if self.goal is not None:
                self.avoid_goals.append(self.goal[:])
                self.avoid_goals = self.avoid_goals[-32:]
            self.goal = None
        if self.goal is None or urgent or obs['tick'] % 10 == 0 or self.recovering != (self.mode == 'recover'):
            self.goal = self.strategic_goal(obs, threats, urgent)
        self.mode = 'recover' if self.recovering else self.goal_kind
        critical = urgent or self.goal_kind in ('zone', 'recover', 'disengage')
        desired = self.nav.direction(me, self.goal, begin + .006, now=now, critical=critical)
        if self.pressure is not None and not urgent and not self.recovering and obs['zone']['radius'] > 45:
            desired = self.combat_direction(obs, desired)
        if self.goal_kind == 'drop' and math.dist(p[:2], self.goal) < 3 and self.pressure is None:
            desired = [0, 0]
        if self.goal_kind in ('recover', 'hold') and math.dist(p[:2], self.goal) < 2 and self.pressure is None:
            desired = [0, 0]
        move = self.movement(obs, desired, threats, urgent, begin + .016)
        self.last_move = move
        aim, fire, reload, target = self.combat.decide(obs, self.recovering, urgent)
        if aim is None:
            # Face a recent attacker to avoid rear damage, otherwise scan at a bounded rate.
            damage = next((e for e in reversed(obs['events']) if e['type'] == 'damaged' and e.get('bearing') is not None), None)
            sounds = [e for e in obs['sounds'] if e['dist'] == 'near' and e['kind'] in ('laser_charge', 'gun', 'lightning')]
            yaw = damage['bearing'] if damage else (sounds[0]['bearing'] if sounds else me['aim'][0] + .25)
            aim = [wrap(yaw), 0.]
            reload = any(w and w['kind'] == 'gun' and w.get('ammo', 0) < w['stats']['mag'] * .75
                         and not w.get('reload', 0) for w in me['weapons'])
        reserve = max(25, me['max_energy'] * .3)
        moving = math.hypot(*move) > .5
        close_pressure = self.pressure is not None and math.dist(p[:2], self.pressure['pos'][:2]) < 42
        boost = moving and me['energy'] > reserve and (urgent or (self.recovering and bool(threats)) or close_pressure)
        jump = False
        progress_stalled = False
        if critical and math.dist(p[:2], self.goal) > 10:
            distance = math.dist(p[:2], self.goal)
            if self.progress is None or math.dist(self.progress['goal'], self.goal) > 8:
                self.progress = {'goal': self.goal[:], 'best': distance, 'at': now}
            elif distance < self.progress['best'] - 3:
                self.progress['best'] = distance; self.progress['at'] = now
            elif now - self.progress['at'] > 4:
                # Motion in a loop is not progress. Replan and allow the same
                # bounded jet escape used for a physically stationary mech.
                progress_stalled = True
                self.progress['at'] = now
                if self.nav.follow:
                    self.nav.follow['hand'] *= -1
        else:
            self.progress = None
        # Planner/local-controller stops still count as stalls when the
        # mandatory destination is far away. Intent is independent of output.
        trying_to_move = moving or (critical and math.dist(p[:2], self.goal) > 6)
        if self.last_pos is not None and trying_to_move and me['grounded']:
            self.stuck = self.stuck + .1 if math.dist(p[:2], self.last_pos[:2]) < .15 else max(0, self.stuck - .2)
        if progress_stalled:
            self.stuck = max(self.stuck, 1.)
        self.last_pos = p[:]
        if self.stuck > .9:
            self.nav.path = []; self.nav.search = None
            if me['grounded'] and me['energy'] > reserve + 15:
                jump = True; self.jet_until = now + 1.3; self.stuck = 0
        if not me['grounded'] and now < self.jet_until and me['energy'] > reserve:
            boost = True
        action = dict(tick=obs['tick'], move=move, aim=aim, fire=fire, reload=reload, boost=boost, jump=jump)
        if obs.get('offer'):
            action['pick'] = self.pick_upgrade(obs)
        held = [w['kind'] for w in me['weapons'] if w]
        near = [o for o in obs['pickups'] if o['kind'] not in held
                and math.dist(p[:2], o['pos'][:2]) < self.cfg['loot']['pickup_radius']
                and abs(p[2] - o['pos'][2]) <= 4]
        if near:
            pickup = max(near, key=lambda o: {'laser': 3, 'lightning': 2, 'mortar': 1, 'gun': 0}[o['kind']])
            if len(held) < 2:
                action['take'] = pickup['id']
            elif pickup['kind'] in ('laser', 'lightning'):
                replace = next((i for i, w in enumerate(me['weapons']) if w and w['kind'] == 'mortar'), None)
                if replace is not None:
                    action.update(take=pickup['id'], drop=replace)
        return action


if __name__ == '__main__':
    mf.run(Bot)
