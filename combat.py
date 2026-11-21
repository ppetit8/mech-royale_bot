"""Weapon solutions, slew-aware trigger control, and conservative engagement policy."""
import math


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def unit(v):
    d = math.hypot(*v)
    return [v[0] / d, v[1] / d] if d > 1e-8 else [0., 0.]


def intercept(origin, target, speed, launch_offset=0):
    """Constant target velocity, stationary world-space projectile speed.

    The protocol does not specify inherited shooter velocity; do not subtract it.
    Account for the barrel's 3 m forward origin in the time equation.
    """
    r = [target['pos'][i] - origin[i] for i in range(3)]
    v = target.get('vel', [0, 0, 0])
    a = sum(x * x for x in v) - speed * speed
    b = 2 * (sum(r[i] * v[i] for i in range(3)) - speed * launch_offset)
    c = sum(x * x for x in r) - launch_offset * launch_offset
    if abs(a) < 1e-8:
        roots = [-c / b] if abs(b) > 1e-8 else []
    else:
        disc = b * b - 4 * a * c
        roots = [(-b + sign * math.sqrt(disc)) / (2 * a) for sign in (-1, 1)] if disc >= 0 else []
    times = [t for t in roots if t >= 0]
    if not times:
        return None
    t = min(times)
    return [target['pos'][i] + v[i] * t for i in range(3)], t


def target_shape(target, cfg):
    if target.get('kind') == 'npc':
        return cfg['npc']['radius'], cfg['npc']['height']
    if target.get('kind') == 'crate':
        return cfg['crates']['radius'], cfg['crates']['height']
    scale = 1 + cfg['cubes']['size_per_cube'] * target.get('cubes', 0)
    return cfg['mech']['radius'] * scale, cfg['mech']['height'] * scale


def mortar_solution(origin, target, stats, offset=3):
    """Solve the low ballistic arc with moving-target fixed-point iterations."""
    speed, g = stats['speed'], stats['gravity']
    t = math.dist(origin[:2], target['pos'][:2]) / speed
    pitch = 0.
    vel = target.get('vel', [0, 0, 0])
    for _ in range(12):
        point = [target['pos'][i] + vel[i] * t for i in range(3)]
        dx, dy, dz = (point[i] - origin[i] for i in range(3))
        horizontal = math.hypot(dx, dy)
        # Offset follows aim, so iterate both horizontal and vertical corrections.
        d = max(.1, horizontal - offset * math.cos(pitch))
        h = dz - offset * math.sin(pitch)
        disc = speed ** 4 - g * (g * d * d + 2 * h * speed * speed)
        if disc < 0:
            return None
        pitch = math.atan2(speed * speed - math.sqrt(disc), g * d)
        nt = d / (speed * math.cos(pitch))
        if abs(nt - t) < .0001:
            t = nt
            break
        t = nt
    return math.atan2(dy, dx), pitch, t, point


class Combat:
    def __init__(self, cfg, world):
        self.cfg, self.world = cfg, world
        self.target_id = None
        self.last_attacked = -math.inf
        self.attackers = {}

    def decide(self, obs, recovering, urgent):
        me = obs['self']; p = me['pos']; stats = me['stats']; cfg = self.cfg
        origin = [p[0], p[1], p[2] + stats['muzzle_height']]
        for event in obs['events']:
            if event['type'] == 'damaged' and event.get('weapon') != 'zone':
                self.last_attacked = obs['t']
                if event.get('by') is not None:
                    self.attackers[event['by']] = obs['t']
        self.attackers = {actor: t for actor, t in self.attackers.items() if obs['t'] - t < 3}
        empty_gun = any(w and w['kind'] == 'gun' and w.get('ammo', 0) <= 0
                        and w.get('reload', 0) <= 0 for w in me['weapons'])
        threats = [e for e in obs['mechs'] if e['kind'] == 'mech']
        enemies = threats[:]
        if not recovering and not urgent:
            enemies += [dict(c, kind='crate', vel=[0, 0, 0]) for c in obs['crates']
                        if math.dist(c['pos'][:2], p[:2]) < 70]
            enemies += [e for e in obs['mechs'] if e['kind'] == 'npc'
                        and math.dist(e['pos'][:2], p[:2]) < 85 and me['hp'] > .8 * me['max_hp']]
        candidates = []; pressure = False
        burst = max((w['stats'].get('damage', 0) * (3 if w['kind'] == 'gun' else 1)
                     for w in me['weapons'] if w), default=0)
        burst *= 1 + cfg['cubes']['damage_per_cube'] * min(me['cubes'], cfg['cubes']['stat_cap'])
        for enemy in enemies:
            radius, height = target_shape(enemy, cfg)
            center = enemy['pos'][:]; center[2] += height * .5
            d = math.dist(origin, center)
            if d > max((w['stats'].get('range', w['stats'].get('speed', 0) ** 2 / max(1, w['stats'].get('gravity', 1)))
                        for w in me['weapons'] if w), default=0):
                continue
            if not self.world.shot_clear(origin, center):
                continue  # Observations also contain actors tracked through cover.
            if enemy['kind'] == 'mech':
                attacker = enemy['id'] in self.attackers
                pressure = pressure or d < 100 or attacker or enemy.get('charging', False)
                # Avoid initiating a distant duel while loot is available.
                # Attackers, exposed low-HP finishes and the endgame remain valid.
                if d > 140 and not attacker and not enemy.get('charging') and enemy.get('hp', math.inf) > burst and obs['alive'] > 3:
                    continue
            elif pressure:
                continue
            score = 100 / (d + 30) + (.35 if enemy['id'] == self.target_id else 0)
            if enemy['kind'] == 'mech':
                score += 4 + 3 * (1 - enemy.get('hp', cfg['mech']['hp']) / enemy.get('max_hp', cfg['mech']['hp']))
                if enemy.get('charging'):
                    score += 1
                if enemy['id'] in self.attackers:
                    score += 1.5
            elif enemy['kind'] == 'crate':
                score += 5
            candidates.append((score, enemy, center, radius))
        if not candidates:
            self.target_id = None
            return None, [False, False], empty_gun, None
        _, target, center, radius = max(candidates, key=lambda c: c[0])
        self.target_id = target['id']
        d = math.dist(origin, center)
        # Recovery only helps if damage can actually stop. Return fire against
        # an immediate pursuer or a recent attacker while continuing to escape.
        recent_attack = obs['t'] - self.last_attacked < 1.2
        pursuer = target['kind'] == 'mech' and d < 60
        last_stand = obs['alive'] <= 3 or obs['zone']['radius'] < 45
        counterfire = target['kind'] == 'mech' and (recent_attack or pursuer or last_stand)
        if (recovering or urgent) and not counterfire:
            yaw = math.atan2(center[1] - p[1], center[0] - p[0])
            return [yaw, 0.], [False, False], empty_gun, target
        weapons = me['weapons']; chosen = None
        # Prefer a charged hitscan release; otherwise gun, then arc, then mortar.
        def priority(item):
            _, w = item
            if not w:
                return -100
            base = {'laser': 5 if w.get('charge', 0) else 3, 'gun': 4,
                    'lightning': 6 if d < w['stats'].get('range', 0) - 2 else 0,
                    'mortar': 2}[w['kind']]
            if w.get('reload', 0) > 0 or w['cooldown'] > .1 or (w['kind'] == 'gun' and w.get('ammo', 0) <= 0):
                base -= 20
            return base
        ranked = sorted(enumerate(weapons), key=priority, reverse=True)
        solutions = {}
        for slot, weapon in ranked:
            if not weapon or weapon.get('reload', 0) > 0:
                continue
            s = weapon['stats']; kind = weapon['kind']; t = 0; point = center[:]
            if kind == 'gun':
                result = intercept(origin, dict(target, pos=center), s['speed'], stats['radius'] + .5)
                if not result or weapon.get('ammo', 0) <= 0:
                    continue
                point, t = result
            elif kind == 'mortar':
                mortar_origin = [p[0], p[1], p[2] + stats['height'] + .5]
                result = mortar_solution(mortar_origin, dict(target, pos=center), s, stats['radius'] + .5)
                if not result or d < s['splash_radius'] + stats['radius'] + 12:
                    continue
                yaw, pitch, t, point = result
                if t > s.get('ttl', 7):
                    continue
                direction = [math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)]
                start = [mortar_origin[i] + direction[i] * (stats['radius'] + .5) for i in range(3)]
                last = start; clear = True
                for j in range(1, 21):
                    dt = t * j / 20
                    at = [start[i] + direction[i] * s['speed'] * dt for i in range(3)]
                    at[2] -= .5 * s['gravity'] * dt * dt
                    if not self.world.shot_clear(last, at):
                        clear = False; break
                    last = at
                if not clear:
                    continue
            elif kind == 'lightning':
                if d > s['range'] - 1 or me['energy'] < s['energy'] + 25:
                    continue
            elif kind == 'laser':
                # A new charge halves movement speed: avoid starting one while
                # escaping. A charge already in progress still needs a safe release.
                if d > s['range'] or ((recovering or urgent) and not weapon.get('charge')):
                    continue
            if kind != 'mortar':
                yaw = math.atan2(point[1] - p[1], point[0] - p[0])
                pitch = math.atan2(point[2] - origin[2], math.dist(point[:2], p[:2]))
                if d > s.get('range', math.inf) or not self.world.shot_clear(origin, point):
                    continue
            if not stats['min_pitch'] <= pitch <= stats['max_pitch']:
                continue
            solutions[slot] = (yaw, pitch, t, point)
            if chosen is None:
                chosen = slot
        if chosen is None:
            return [math.atan2(center[1] - p[1], center[0] - p[0]), 0.], [False, False], empty_gun, target
        yaw, pitch, _, _ = solutions[chosen]
        fire = [False, False]
        for slot, solution in solutions.items():
            w = weapons[slot]; s = w['stats']; sy, sp, _, point = solution
            # Gate on observed actual aim, with only the slew available before cooldown ends.
            wait = max(0, w['cooldown'])
            yaw_error = max(0, abs(wrap(sy - me['aim'][0])) - stats['turn_rate'] * wait)
            pitch_error = max(0, abs(sp - me['aim'][1]) - stats['pitch_rate'] * wait)
            tolerance = math.atan2(radius * .75, max(3, math.dist(origin, point)))
            aligned = yaw_error < tolerance and pitch_error < max(tolerance, .012)
            compatible = abs(wrap(sy - yaw)) < tolerance and abs(sp - pitch) < max(tolerance, .012)
            if w['kind'] == 'lightning':
                aligned = abs(wrap(sy - me['aim'][0])) < math.radians(s['cone_deg']) * .45
                compatible = abs(wrap(sy - yaw)) < math.radians(s['cone_deg']) * .45
            if wait > .1:
                continue
            if w['kind'] == 'laser':
                charge = w.get('charge', 0)
                damage = s['damage'] * (1 + cfg['cubes']['damage_per_cube'] * min(me['cubes'], cfg['cubes']['stat_cap']))
                lethal = target.get('hp', math.inf) <= damage * max(s['min_frac'], charge / s['charge'])
                # False releases the beam. Keep charging until aligned/full or a lethal partial.
                fire[slot] = not (compatible and aligned and (charge >= s['charge'] or (charge >= s['min_charge'] and lethal)))
            else:
                fire[slot] = aligned and compatible
        # Opportunistic reload only away from an immediate engagement.
        reload = empty_gun or (any(w and w['kind'] == 'gun' and w.get('ammo', 0) < w['stats']['mag'] * .4
                     and not w.get('reload', 0) for w in weapons) and d > 120)
        return [yaw, pitch], fire, reload, target
