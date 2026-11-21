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
    name = 'Aegis-v6'

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
        self.goal_key = None
        self.goal_decision = {}

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
        """Bounded utility selection, with a conservative opponent-response test.

        Utilities are policy points, not probabilities of winning. Optional goals
        need a verified direct ground route; mandatory rotations retain the
        existing navigator's ability to take detours. No combat controls change.
        """
        deadline = time.perf_counter() + .004
        me = obs['self']; p = me['pos']; now = obs['t']; zone = obs['zone']
        w = self.world; stats = me['stats']; body = stats['radius']; height = stats['height']
        walk = max(1, stats['walk_speed'])
        missing = max(0, 1 - me['hp'] / me['max_hp'])
        center, radius = future_zone(zone, now, now + 20)
        next_c = zone['next_center']; next_r = zone['next_radius']
        dist_next = max(0, math.dist(p[:2], next_c) - next_r + 20)
        migrate = urgent or dist_next / walk * 1.7 + 12 > zone['shrink_end'] - now
        if migrate:
            center, radius = next_c, next_r
        safe_r = max(0, radius - min(25, radius * .2))
        rotating = migrate or math.dist(p[:2], center) > safe_r
        candidates = []
        rejected = {}; checked = 0; exhausted = False

        def add(q, kind, reward, key=None, dwell=0, target=None):
            candidates.append(dict(q=list(q[:2]), kind=kind, reward=reward,
                                   key=key or (kind, round(q[0]), round(q[1])),
                                   dwell=dwell, target=target))

        def reject(reason):
            rejected[reason] = rejected.get(reason, 0) + 1

        # Limit expensive raycasts to the four nearest actors at EACH point.
        # All tracked actors still contribute a cheap proximity penalty, even
        # behind cover. A track is not proof that the intervening route is safe.
        risk_cache = {}
        def risk(q):
            key = (round(q[0], 1), round(q[1], 1))
            if key in risk_cache:
                return risk_cache[key]
            ordered = sorted(((math.dist(q, e['pos'][:2]), e) for e in threats),
                             key=lambda item: item[0])
            value = sum(max(0, 80 - d) * .28 for d, _ in ordered)
            top = [*q, w.ground(*q) + height * .55]
            for d, e in ordered[:4]:
                if d > 230:
                    continue
                source = e['pos'][:]
                source[2] += self.cfg['mech']['muzzle_height']
                value += (12 if w.shot_clear(source, top) else 2) * min(1.5, 140 / (d + 30))
            risk_cache[key] = value
            return value

        # Nearby destinations and obstacle corners offer cover without requiring
        # a separate global search. Testing their outgoing steps penalizes traps.
        points = [p[:2]]
        for distance in (22, 42):
            for i in range(6):
                a = i * math.tau / 6
                points.append([p[0] + distance * math.cos(a), p[1] + distance * math.sin(a)])
        corners = []
        for idx in w.nearby(*p[:2], 50):
            prism = w.prisms[idx]
            if prism['kind'] == 'tree' or prism['top'] < p[2] + height * .55:
                continue
            x0, y0, x1, y1 = prism['_bbox']; pad = body + 2
            for x in (x0 - pad, x1 + pad):
                for y in (y0 - pad, y1 + pad):
                    if math.dist(p[:2], [x, y]) < 65:
                        corners.append([x, y])
        points.extend(sorted(corners, key=lambda q: math.dist(p[:2], q))[:8])

        if rotating:
            toward = unit([p[0] - center[0], p[1] - center[1]])
            preferred = [center[i] + toward[i] * safe_r * .8 for i in range(2)]
            fallback = self.zone_goal(me, center, max(0, radius - body), preferred)
            add(fallback, 'zone', 0)
            for q in points[1:]:
                if math.dist(q, center) <= safe_r:
                    add(q, 'zone', 0)
        else:
            # Evaluate the safe baseline and repair drops before other detours.
            local_danger = any(math.dist(p[:2], e['pos'][:2]) < 120 for e in threats)
            cover_kind = 'recover' if self.recovering else ('disengage' if local_danger else 'hold')
            cover_reward = 12 + missing * 18 if self.recovering else (5 if local_danger else 0)
            fallback = p[:2]
            add(p, cover_kind, cover_reward)

            def cube_value(count):
                cap = self.cfg['cubes']['stat_cap']
                stats_gain = max(0, min(count, cap - me['cubes']))
                offers = sum(me['cubes'] < n <= me['cubes'] + count
                             for n in self.cfg['cubes']['upgrade_thresholds'])
                return stats_gain * 15 + offers * 8 + (count - stats_gain) * 2

            # Opponents' upgrade selections are hidden. Use the fastest speed
            # supported by the public catalog, or a faster observed velocity.
            enemy_speed = self.cfg['mech']['boost_speed']
            for upgrade in self.cfg.get('upgrades', []):
                for effect in upgrade['effects']:
                    if effect['path'] == 'mech.boost_speed':
                        enemy_speed *= max(1, effect.get('mul', 1)) ** upgrade['max']
                        enemy_speed += max(0, effect.get('add', 0)) * upgrade['max']
            enemy_speed = max([1, enemy_speed] + [math.hypot(*e['vel'][:2]) for e in threats])
            for drop in sorted(obs.get('drops', []), key=lambda d: math.dist(p[:2], d['pos'][:2])):
                q = drop['pos']; d = math.dist(p[:2], q[:2])
                if d > 115 or abs(q[2] - w.ground(*q[:2])) > 4:
                    reject('drop_range_or_height'); continue
                # No credit for someone else's capture clock. Travel all the way
                # to the center is conservative relative to entering the ring.
                ours = drop['holder'] == me['id'] and d < drop['radius'] and abs(p[2] - q[2]) <= 4
                dwell = max(0, drop['lands_in'] - d / walk) + max(0, drop['capture_s'] - (drop['progress'] if ours else 0))
                completion = d / walk + dwell
                contested = any(max(0, math.dist(q[:2], e['pos'][:2]) - drop['radius']) / enemy_speed <= completion + 2
                                for e in threats)
                if contested or drop['holder'] not in (None, me['id']) or completion > 18:
                    reject('drop_contest_or_wait'); continue
                delay = max(0, stats['regen_delay'] - (now - self.last_damage))
                passive_heal = stats['regen_per_s'] * max(0, completion - delay)
                repair = max(0, me['max_hp'] - me['hp'] - passive_heal) / me['max_hp'] * 85
                value = cube_value(self.cfg['drops']['cubes']) + repair + (me['max_energy'] - me['energy']) * .1
                add(q, 'drop', value, ('drop', drop['id']), dwell, drop)

            # Only positional goals are retained speculatively. Object goals must
            # be re-created from still-valid memory/current drop observations.
            if (self.goal is not None and now < self.goal_until and
                    self.goal_kind in (cover_kind, 'explore') and
                    (self.goal_kind != 'explore' or (not self.recovering and not local_danger))):
                add(self.goal, self.goal_kind, 11 if self.goal_kind == 'explore' else cover_reward, self.goal_key)
            cover_points = []
            if self.recovering or local_danger:
                # Keep some cover evaluations ahead of loot when the time
                # budget is tight. Corners and radial samples both get a turn.
                for group in (points[13:], points[1:13]):
                    valid = [q for q in group if w.clear_at(*q, w.ground(*q), height, body + .5) >= body + .4]
                    cover_points.extend(sorted(valid, key=lambda q: sum(max(0, 80 - math.dist(q, e['pos'][:2])) for e in threats) + math.dist(p[:2], q) * .3)[:4])
                for q in cover_points[:4]:
                    add(q, cover_kind, cover_reward)
            held = [weapon['kind'] for weapon in me['weapons'] if weapon]
            loot_candidates = []
            for obj, seen, kind in self.loot.values():
                q = obj['pos']; d = math.dist(q[:2], p[:2])
                if now - seen > 18 or d > 115 or abs(q[2] - w.ground(*q[:2])) > 4:
                    continue
                if kind in ('cube', 'weapon') and any(
                        max(0, math.dist(q[:2], e['pos'][:2]) - 4) / enemy_speed <= d / walk + 1
                        for e in threats):
                    reject('loot_contest'); continue
                value = cube_value(1) if kind == 'cube' else (28 if kind == 'weapon' and len(held) < 2 and obj['kind'] not in held else 0)
                dwell = 0
                if kind == 'crate' and not threats and not self.recovering and me['cubes'] < 10:
                    value = 12
                    gun = next((weapon for weapon in me['weapons'] if weapon and weapon['kind'] == 'gun'), None)
                    if not gun:
                        continue
                    dwell = self.cfg['crates']['hp'] / max(1, gun['stats']['damage']) * gun['stats']['cooldown'] + gun['stats']['reload']
                    away = unit([p[0] - q[0], p[1] - q[1]])
                    q = [q[0] + away[0] * 18, q[1] + away[1] * 18]
                if value:
                    loot_candidates.append((value / (1 + d / walk / 10), obj['id'], q, kind, value, dwell, obj))
            for _, ident, q, kind, value, dwell, obj in sorted(loot_candidates, reverse=True)[:6]:
                add(q, kind, value, (kind, ident), dwell, obj)
            if self.recovering or local_danger:
                for q in cover_points[4:]:
                    add(q, cover_kind, cover_reward)
            else:
                # Seeded exploration gets a commitment window, avoiding a fresh
                # random heading every strategic update.
                for _ in range(6):
                    a = self.rng.uniform(-math.pi, math.pi)
                    add([p[0] + 65 * math.cos(a), p[1] + 65 * math.sin(a)], 'explore', 11)

        scored = []
        start_node = w.nearest(p, body)
        for candidate in candidates[:32]:
            if checked and time.perf_counter() >= deadline:
                exhausted = True; break
            checked += 1
            q = candidate['q']; kind = candidate['kind']; distance = math.dist(p[:2], q)
            ground = w.ground(*q)
            if w.clear_at(*q, ground, height, body + .5) < body + .4:
                reject('blocked'); continue
            node = w.node(q)
            if start_node is not None and w.components[node] != w.components[start_node]:
                reject('disconnected'); continue
            if kind != 'zone' and any(math.dist(q, blocked) < 12 for blocked in self.avoid_goals):
                reject('failed_route'); continue
            completion = distance / walk + candidate['dwell']
            c, r = future_zone(zone, now, now + max(20, completion + 6))
            if kind != 'zone':
                if math.dist(q, c) > max(0, r - min(12, r * .12)):
                    reject('zone_at_completion'); continue
                exit_distance = max(0, math.dist(q, next_c) - max(0, next_r - 12))
                if exit_distance > 0 and completion + exit_distance / walk * 1.7 + 6 > zone['shrink_end'] - now:
                    reject('rotation_slack'); continue
                if distance > 1 and not w.walk_clear(p, [*q, ground], body, height, abs(p[2] - w.ground(*p[:2])) < 2):
                    reject('unverified_route'); continue
            elif math.dist(q, center) > max(0, radius - body):
                reject('zone_destination'); continue
            endpoint_risk = risk(q)
            midpoint_risk = risk([(q[i] + p[i]) * .5 for i in range(2)]) if distance > 12 else endpoint_risk
            # Transit exposure cannot be hidden by a well-sheltered endpoint.
            risk_cost = (endpoint_risk * .75 + midpoint_risk * .25) * (1 + missing)
            exits = sum(w.walk_clear([*q, ground], [q[0] + dx * 8, q[1] + dy * 8, w.ground(q[0] + dx * 8, q[1] + dy * 8)], body, height)
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            trap_cost = max(0, 2 - exits) * 4
            sound_cost = 0
            heading = unit([q[0] - p[0], q[1] - p[1]])
            for bearing, weight, heard_at in self.heard[-6:]:
                sound_cost += max(0, heading[0] * math.cos(bearing) + heading[1] * math.sin(bearing)) * weight * max(0, 1 - (now - heard_at) / 3) * 8
            reserve = max(25, me['max_energy'] * .3)
            escape_cost = max(0, reserve - me['energy']) / max(1, reserve) * min(8, distance / 8)
            score = candidate['reward'] / (1 + completion / 10) - distance * (.1 if kind == 'explore' else .14)
            score -= risk_cost + trap_cost + sound_cost + escape_cost
            if kind == 'drop':
                score -= 3 + candidate['dwell'] * .3  # globally advertised, stationary capture
            if kind == 'zone':
                # Rotation travel matters most while taking zone damage.
                score -= distance * (.1 if not me['in_zone'] else 0)
            candidate['score'] = score
            scored.append(candidate)

        if scored:
            best = max(scored, key=lambda item: item['score'])
            old = next((item for item in scored if item['key'] == self.goal_key), None)
            if not rotating and old is not None and best['score'] < old['score'] + max(3, abs(old['score']) * .15):
                best = old
            if best['key'] != self.goal_key:
                self.goal_until = now + (8 if best['kind'] == 'explore' else 4)
            self.goal_key = best['key']; self.goal_kind = best['kind']
            result = best['q']
        else:
            self.goal_kind = 'zone' if rotating else ('recover' if self.recovering else 'hold')
            self.goal_key = (self.goal_kind, 'fallback'); best = None
            result = fallback
        self.goal_decision = dict(kind=self.goal_kind, key=self.goal_key,
                                  utility=round(best['score'], 3) if best else None,
                                  checked=checked, rejected=rejected, budget_exhausted=exhausted)
        return result

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
        if self.goal_kind == 'drop' and math.dist(p[:2], self.goal) < 3:
            desired = [0, 0]
        if self.goal_kind in ('recover', 'hold') and math.dist(p[:2], self.goal) < 2:
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
