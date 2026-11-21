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
    name = 'Aegis-v12'
    cover_mode = 'cover'
    rear_guard_seconds = 0.
    retreat_charge_seconds = 0.
    recovery_enter_hp = .65
    shelter_hold_seconds = 2.8
    pursuit_recovery_hp = .78
    migration_buffer_s = 12.

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
        self.last_mech_hit = (-math.inf, None)
        self.last_hit_bearing = None
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
        self.refuge_until = -1
        self.hide = None

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

    def repair_drop_goal(self, obs, threats):
        """A narrow recovery exception; otherwise leave the V5 policy in charge.

        Only landed, nearby, directly walkable drops can replace passive healing.
        Compare completion with the fastest plausible passive full-heal time.
        Unknown opponents are not assumed absent; known opponents receive a
        conservative arrival test and line-of-sight checks along the approach.
        """
        if not obs.get('drops'):
            return None
        deadline = time.perf_counter() + .0015
        me = obs['self']; p = me['pos']; now = obs['t']; stats = me['stats']
        w = self.world; body = stats['radius']; height = stats['height']
        if not me['grounded'] or abs(p[2] - w.ground(*p[:2])) > 2:
            return None
        walk = max(1, stats['walk_speed'])
        if any(weapon and weapon.get('charge', 0) > 0 for weapon in me['weapons']):
            walk *= stats['charge_move_mult']
        passive_time = (max(0, stats['regen_delay'] - (now - self.last_damage)) +
                        max(0, me['max_hp'] - me['hp']) / max(1, stats['regen_per_s']))
        enemy_speed = self.cfg['mech']['boost_speed']
        for upgrade in self.cfg.get('upgrades', []):
            for effect in upgrade['effects']:
                if effect['path'] == 'mech.boost_speed':
                    enemy_speed *= max(1, effect.get('mul', 1)) ** upgrade['max']
                    enemy_speed += max(0, effect.get('add', 0)) * upgrade['max']
        enemy_speed = max([1, enemy_speed] + [math.hypot(*e['vel'][:2]) for e in threats])
        max_range = max(weapon.get('range', 0) for weapon in self.cfg['weapons'].values())
        best = None
        drops = sorted(obs['drops'][:3], key=lambda drop: math.dist(p[:2], drop['pos'][:2]))
        for drop in drops:
            if time.perf_counter() >= deadline:
                break
            q = drop['pos']; distance = math.dist(p[:2], q[:2]); ground = w.ground(*q[:2])
            if drop['lands_in'] > 0 or distance > 60 or abs(q[2] - ground) > 4:
                continue
            if drop['holder'] not in (None, me['id']):
                continue
            if any(math.dist(q[:2], blocked) < 12 for blocked in self.avoid_goals):
                continue
            in_ring = distance < drop['radius'] and abs(p[2] - q[2]) <= 4
            progress = drop['progress'] if in_ring and drop['holder'] == me['id'] else 0
            arrival = 0 if in_ring else distance / walk + .35
            completion = arrival + max(0, drop['capture_s'] - progress)
            if completion + 1 >= passive_time:
                continue
            zone = obs['zone']
            center, radius = future_zone(zone, now, now + max(20, completion + 8))
            if math.dist(q[:2], center) > max(0, radius - min(25, radius * .2)):
                continue
            exit_distance = max(0, math.dist(q[:2], zone['next_center']) - max(0, zone['next_radius'] - 12))
            if exit_distance > 0 and completion + exit_distance / walk * 1.7 + 8 > zone['shrink_end'] - now:
                continue
            if any(max(0, math.dist(q[:2], e['pos'][:2]) - drop['radius']) / enemy_speed <= completion + 2
                   for e in threats):
                continue
            if w.clear_at(*q[:2], ground, height, body + .5) < body + .4:
                continue
            if not w.walk_clear(p, [q[0], q[1], ground], body, height):
                continue
            # Refuse an exposed repair approach, even if the enemy cannot enter
            # the capture ring in time. Inspect current, midpoint and endpoint.
            points = [p[:2], [(p[i] + q[i]) * .5 for i in range(2)], q[:2]]
            safe = True
            for e in threats:
                for point in points:
                    if time.perf_counter() >= deadline:
                        safe = False; break
                    if math.dist(e['pos'][:2], point) > max_range:
                        continue
                    source = e['pos'][:]; source[2] += self.cfg['mech']['muzzle_height']
                    target = [*point, w.ground(*point) + height * .55]
                    if w.shot_clear(source, target):
                        safe = False; break
                if not safe:
                    break
            if not safe or time.perf_counter() >= deadline:
                continue
            rank = (completion, distance, drop['id'])
            if best is None or rank < best[0]:
                best = rank, q[:2]
        return best[1] if best is not None else None

    def cover_route(self, obs, threats, center, safe_radius):
        """Choose a short escape route by exposure on the route and at its end."""
        me = obs['self']
        p = me['pos']
        stats = me['stats']
        world = self.world
        if not me['grounded'] or abs(p[2] - world.ground(*p[:2])) > 2:
            return None
        nearby = [enemy for enemy in threats[:4] if math.dist(p[:2], enemy['pos'][:2]) < 130]
        sources = [[*e['pos'][:2], e['pos'][2] + self.cfg['mech']['muzzle_height']] for e in nearby]
        if not sources:
            return None
        if self.cover_mode == 'aligned':
            axis = unit([sources[0][0] - p[0], sources[0][1] - p[1]])
            if any(sum(axis[i] * (source[i] - p[i]) for i in range(2)) < 0
                   for source in sources[1:]):
                return None
        deadline = time.perf_counter() + .003
        projected = []
        base = self.cfg['mech']
        for enemy in nearby:
            origin = enemy['pos']
            x, y = (origin[i] + .85 * enemy['vel'][i] for i in range(2))
            z = world.ground(x, y)
            if (math.dist(origin[:2], (x, y)) >= 2
                    and abs(origin[2] - world.ground(*origin[:2])) < 2
                    and world.walk_clear(origin, [x, y, z], base['radius'], base['height'])):
                projected.append([x, y, z + base['muzzle_height']])

        def risk(point):
            target = [point[0], point[1], point[2] + .55 * stats['height']]
            danger = 0.
            for source in sources:
                distance = math.dist(point[:2], source[:2])
                danger += max(0., 30 - distance) / 18
                if world.shot_clear(source, target):
                    danger += 75 / (25 + distance)
            return danger

        def future_risk(point):
            target = [point[0], point[1], point[2] + .55 * stats['height']]
            return sum(55 / (25 + math.dist(point[:2], source[:2]))
                       for source in projected if world.shot_clear(source, target))

        current_risk = risk(p)
        if current_risk < .08:
            return None
        # The first heading points away from the nearest tracked threat.
        heading = math.atan2(p[1] - sources[0][1], p[0] - sources[0][0])
        old_goal = self.goal if self.goal_kind in ('recover', 'disengage') else None
        options = []
        if old_goal is not None and obs['t'] < self.refuge_until:
            options.append(old_goal)
        for distance in (16., 32., 48.):
            for delta in (0, .785, -.785, 1.57, -1.57, 2.35, -2.35, math.pi):
                yaw = heading + delta
                options.append([p[0] + distance * math.cos(yaw), p[1] + distance * math.sin(yaw)])

        best = None
        for q in options:
            if time.perf_counter() >= deadline:
                break
            distance = math.dist(p[:2], q[:2])
            if distance < 4 or math.dist(q[:2], center) > safe_radius:
                continue
            destination = [*q[:2], world.ground(*q[:2])]
            if not world.walk_clear(p, destination, stats['radius'], stats['height']):
                continue
            end_risk = risk(destination)
            if end_risk >= current_risk * .82:
                continue
            midpoint = [(p[i] + destination[i]) / 2 for i in range(2)]
            mid_risk = risk([*midpoint, world.ground(*midpoint)])
            if mid_risk > current_risk * 1.18 + .1:
                continue
            travel_seconds = distance / max(1., stats['walk_speed'])
            transit = (.25 * current_risk + .5 * mid_risk + .25 * end_risk) * travel_seconds
            score = transit + 4 * end_risk + .18 * travel_seconds
            if projected:
                score += 3 * future_risk(destination)
            # Hold a route through small changes in enemy position. Geometry,
            # zone and exposure still have to pass again at each evaluation.
            if q is old_goal and obs['t'] < self.refuge_until:
                score *= .82
            if best is None or score < best[0]:
                best = (score, q)
        if best is None:
            return None
        if best[1] is not old_goal:
            self.refuge_until = obs['t'] + 1.5
        return best[1]

    def hide_spot(self, obs, threats, center, safe_r):
        """Pick an enclosed, low-exposure, quiet spot inside the safe zone and hold it."""
        me = obs['self']; p = me['pos']; now = obs['t']; w = self.world
        body = me['stats']['radius']; height = me['stats']['height']
        deadline = time.perf_counter() + .004
        rays = [(math.cos(i * math.pi / 6), math.sin(i * math.pi / 6)) for i in range(12)]

        def score(q):
            z = w.ground(*q) + height * .55
            blocked = sum(1 for dx, dy in rays if not w.shot_clear([q[0], q[1], z], [q[0] + 40 * dx, q[1] + 40 * dy, z]))
            s = 6 * blocked / 12 - 4 * self.exposure(q, threats, height)
            for bearing, weight, heard_at in self.heard[-6:]:
                dx, dy = q[0] - p[0], q[1] - p[1]; n = math.hypot(dx, dy) or 1
                s -= 6 * weight * max(0, (dx * math.cos(bearing) + dy * math.sin(bearing)) / n)
            if safe_r > 150:
                s -= 2 * max(0, 1 - math.dist(q, center) / (.45 * safe_r))
            return s - .02 * math.dist(q, p[:2])

        def valid(q):
            n = w.nearest(q, body)
            if n is None or math.dist(q, center) > safe_r:
                return None
            xy = list(w.xy(n))
            if math.dist(xy, center) > safe_r or any(math.dist(xy, bad) < 12 for bad in self.avoid_goals):
                return None
            return xy if w.clear_at(*xy, w.ground(*xy), height) > body + .4 else None

        cur = self.hide
        if cur is not None and now < cur['until'] and math.dist(cur['q'], center) <= safe_r and not threats \
                and not self.heard:
            return cur['q']
        options = []
        if cur is not None and math.dist(cur['q'], center) <= safe_r:
            options.append(cur['q'])
        for dist in (20, 45, 75):
            for i in range(8):
                a = i * math.pi / 4 + dist * .1
                options.append([p[0] + dist * math.cos(a), p[1] + dist * math.sin(a)])
        best = None
        for q in options:
            if time.perf_counter() > deadline:
                break
            xy = valid(q)
            if xy is None:
                continue
            sc = score(xy) + (1.5 if cur is not None and q is cur['q'] else 0)
            if best is None or sc > best[0]:
                best = (sc, xy)
        if best is None:
            return center[:]
        self.hide = {'q': best[1], 'until': now + 6}
        return best[1]

    def strategic_goal(self, obs, threats, urgent):
        me = obs['self']; p = me['pos']; now = obs['t']; zone = obs['zone']
        walk = me['stats']['walk_speed']
        center, radius = future_zone(zone, now, now + 20)
        next_c = zone['next_center']; next_r = zone['next_radius']
        dist_next = max(0, math.dist(p[:2], next_c) - next_r + 20)
        migrate = urgent or dist_next / walk * 1.7 + self.migration_buffer_s > zone['shrink_end'] - now
        if migrate:
            center, radius = next_c, next_r
        margin = min(25, radius * .2)
        safe_r = max(0, radius - margin)
        if migrate or math.dist(p[:2], center) > safe_r:
            toward = unit([p[0] - center[0], p[1] - center[1]])
            goal = [center[0] + toward[0] * safe_r * .8, center[1] + toward[1] * safe_r * .8]
            self.goal_kind = 'zone'
            return self.zone_goal(me, center, max(0, radius - me['stats']['radius']), goal)
        if self.recovering:
            repair = self.repair_drop_goal(obs, threats)
            if repair is not None:
                self.goal_kind = 'drop'
                return repair
            if (self.shelter_hold_seconds and now - self.last_mech_hit[0] < self.shelter_hold_seconds
                    and threats and min(math.dist(p[:2], enemy['pos'][:2]) for enemy in threats) > 35
                    and self.exposure(p, threats, me['stats']['height']) == 0):
                self.goal_kind = 'recover'
                return p[:2]
        recent_hit = now - self.last_mech_hit[0] < 1.5
        if self.recovering or (recent_hit and len(threats) >= 2):
            route = self.cover_route(obs, threats, center, safe_r)
            if route is not None:
                self.goal_kind = 'recover' if self.recovering else 'disengage'
                return route
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
            if now - seen > 18 or d > (50 if kind == 'cube' else 80) or abs(q[2] - self.world.ground(*q[:2])) > 4:
                continue
            if math.dist(q[:2], center) > safe_r:
                continue
            danger = sum(max(0, 80 - math.dist(q[:2], e['pos'][:2])) / 12 for e in threats)
            value = 85 if kind == 'cube' else (125 if kind == 'weapon' and empty and obj['kind'] not in held else 0)
            if kind == 'cube' and (threats or self.heard):
                value = 0
            score = value / (d + 18) - danger
            if score > 0 and (best is None or score > best[0]):
                if kind == 'crate':
                    away = unit([p[0] - q[0], p[1] - q[1]])
                    q = [q[0] + away[0] * 18, q[1] + away[1] * 18]
                best = (score, q[:2], kind)
        if best:
            self.goal_kind = best[2]
            return best[1]
        spot = self.hide_spot(obs, threats, center, safe_r)
        self.goal_kind = 'hide'
        return spot

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

    def ground_boost_clear(self, me, move):
        """Check the short ground segment before spending energy on a retreat."""
        if not me['grounded']:
            return False
        p = me['pos']
        stats = me['stats']
        world = self.world
        if abs(p[2] - world.ground(*p[:2])) >= 2:
            return False

        # Look slightly less far ahead than local steering so the guard does
        # not brake too early for a turn the navigator already plans to take.
        horizon = .35
        accel = stats['ground_accel']
        radius = stats['radius']
        height = stats['height']
        speed_scale = (stats['charge_move_mult']
                       if any(weapon and weapon.get('charge', 0) > 0 for weapon in me['weapons'])
                       else 1)

        speed = stats['boost_speed'] * speed_scale
        vx, vy = me['vel'][:2]
        dx, dy = move[0] * speed - vx, move[1] * speed - vy
        change = math.hypot(dx, dy)
        ramp = min(horizon, change / accel) if accel > 0 else 0.
        ax = dx * accel / change if ramp else 0.
        ay = dy * accel / change if ramp else 0.
        previous = p
        for t in (horizon / 2, horizon):
            applied = min(t, ramp)
            integral = applied * (t - applied / 2)
            x = p[0] + vx * t + ax * integral
            y = p[1] + vy * t + ay * integral
            point = [x, y, world.ground(x, y)]
            if not world.walk_clear(previous, point, radius, height):
                return False
            previous = point
        return True

    def disengage_boost(self, me, move, threats, now, reserve):
        """Use a brief burst only along an already chosen retreat."""
        hit_at, attacker_id = self.last_mech_hit
        if now - hit_at > .65 or me['energy'] <= reserve + 15:
            return False
        attacker = next((enemy for enemy in threats if enemy['id'] == attacker_id), None)
        if attacker is None:
            return False
        p = me['pos']
        offset = [attacker['pos'][i] - p[i] for i in range(2)]
        distance = math.hypot(*offset)
        if distance > 120 or sum(move[i] * offset[i] for i in range(2)) >= -.25 * distance:
            return False
        for enemy in threats:
            offset = [enemy['pos'][i] - p[i] for i in range(2)]
            distance = math.hypot(*offset)
            if distance < 45 and sum(move[i] * offset[i] for i in range(2)) > .2 * distance:
                return False
        return self.ground_boost_clear(me, move)

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
                if e.get('weapon') in ('gun', 'laser', 'lightning', 'mortar') and e.get('by') is not None:
                    self.last_mech_hit = (now, e['by'])
                    self.last_hit_bearing = e.get('bearing')
        for key, kind in (('cubes', 'cube'), ('pickups', 'weapon'), ('crates', 'crate')):
            for obj in obs[key]:
                self.loot[obj['id']] = (obj, now, kind)
        self.loot = {i: item for i, item in self.loot.items() if now - item[1] < 18
                     and not (math.dist(item[0]['pos'][:2], p[:2]) < 4 and item[1] < now - .5)}
        if me['hp'] < me['max_hp'] * self.recovery_enter_hp:
            self.recovering = True
        if me['hp'] >= me['max_hp'] * .93:
            self.recovering = False
        threats = sorted((e for e in obs['mechs'] if e['kind'] == 'mech'), key=lambda e: math.dist(p[:2], e['pos'][:2]))
        center, r = future_zone(obs['zone'], now, now + 12)
        urgent = not me['in_zone'] or math.dist(p[:2], center) > max(0, r - min(12, r * .15))
        if (self.pursuit_recovery_hp and not self.recovering and not urgent
                and now - self.last_mech_hit[0] < 1.1 and len(threats) >= 2
                and me['hp'] < self.pursuit_recovery_hp * me['max_hp']):
            closing = 0
            for enemy in threats[:4]:
                offset = [p[i] - enemy['pos'][i] for i in range(2)]
                distance = math.hypot(*offset)
                if distance:
                    speed_toward_us = sum(enemy['vel'][i] * (offset[i] / distance) for i in range(2))
                    if distance <= 100 and speed_toward_us >= 3.5:
                        closing += 1
            self.recovering = closing >= 2
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
        if self.goal_kind == 'drop' and math.dist(p[:2], self.goal) < 3:
            desired = [0, 0]
        if self.goal_kind in ('recover', 'hold', 'hide') and math.dist(p[:2], self.goal) < 2:
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
        boost = moving and me['energy'] > reserve and (urgent or (self.recovering and bool(threats)))
        if not boost and moving and self.goal_kind == 'disengage' and not self.recovering:
            boost = self.disengage_boost(me, move, threats, now, reserve)
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
        if len(held) < 2:
            near = [o for o in obs['pickups'] if o['kind'] not in held
                    and math.dist(p[:2], o['pos'][:2]) < self.cfg['loot']['pickup_radius']
                    and abs(p[2] - o['pos'][2]) <= 4]
            if near:
                action['take'] = max(near, key=lambda o: {'laser': 3, 'lightning': 2, 'mortar': 1, 'gun': 0}[o['kind']])['id']
        return action


if __name__ == '__main__':
    mf.run(Bot)
