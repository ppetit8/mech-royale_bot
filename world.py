"""Static collision/shot geometry and a bounded, resumable ground navigator.

No scenery collisions: only terrain and solid prisms are authoritative.
"""
import array
import heapq
import json
import math
import sys
import time
from collections import deque
from pathlib import Path


def inside(x, y, ring):
    hit = False
    ax, ay = ring[-2:]
    for i in range(0, len(ring), 2):
        bx, by = ring[i:i + 2]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            hit = not hit
        ax, ay = bx, by
    return hit


def edge_distance(x, y, ring):
    best = math.inf
    ax, ay = ring[-2:]
    for i in range(0, len(ring), 2):
        bx, by = ring[i:i + 2]
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
        best = min(best, (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2)
        ax, ay = bx, by
    return math.sqrt(best)


def segment_edge_distance(a, b, ring):
    """Minimum horizontal distance from a movement segment to polygon edges."""
    best = min(edge_distance(*a[:2], ring), edge_distance(*b[:2], ring))
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    ax, ay = ring[-2:]
    for i in range(0, len(ring), 2):
        bx, by = ring[i:i + 2]
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) > 1e-10:
            u, v = ax - a[0], ay - a[1]
            t, s = (u * ey - v * ex) / den, (u * dy - v * dx) / den
            if 0 <= t <= 1 and 0 <= s <= 1:
                return 0.
        t = max(0, min(1, ((ax - a[0]) * dx + (ay - a[1]) * dy) / (length2 or 1)))
        best = min(best, math.hypot(ax - a[0] - t * dx, ay - a[1] - t * dy))
        ax, ay = bx, by
    return best


class World:
    CELL = 4.0
    BUCKET = 32.0

    def __init__(self, directory, config):
        self.cfg = config
        root = Path(directory) / 'v2'
        self.data = json.loads((root / 'world.json').read_text())
        self.bounds = self.data['bounds']
        self.terrain = self.data['terrain']
        self.samples = array.array('h')
        self.samples.frombytes((root / 'terrain.i16').read_bytes())
        if sys.byteorder != 'little':
            self.samples.byteswap()
        self.prisms = self.data['prisms']
        self.buckets = {}
        for i, p in enumerate(self.prisms):
            r = p['ring']
            p['_bbox'] = (min(r[::2]), min(r[1::2]), max(r[::2]), max(r[1::2]))
            lo_x, lo_y, hi_x, hi_y = p['_bbox']
            for by in range(math.floor(lo_y / self.BUCKET), math.floor(hi_y / self.BUCKET) + 1):
                for bx in range(math.floor(lo_x / self.BUCKET), math.floor(hi_x / self.BUCKET) + 1):
                    self.buckets.setdefault((bx, by), []).append(i)
        self.x0, self.y0 = self.bounds['minX'], self.bounds['minY']
        self.nx = math.floor((self.bounds['maxX'] - self.x0) / self.CELL) + 1
        self.ny = math.floor((self.bounds['maxY'] - self.y0) / self.CELL) + 1
        self.heights = array.array('f')
        self.clearance = array.array('f')
        height = config['mech']['height']
        for iy in range(self.ny):
            for ix in range(self.nx):
                x, y = self.xy(iy * self.nx + ix)
                z = self.ground(x, y)
                self.heights.append(z)
                self.clearance.append(self.clear_at(x, y, z, height, 18))
        # Ground-only connectivity identifies enclosed courtyards before a bot
        # wastes thousands of expansions trying to walk through their walls.
        self.components = array.array('i', [-1]) * len(self.clearance)
        self.component_nodes = []
        for start in range(len(self.clearance)):
            if self.clearance[start] < config['mech']['radius'] + .4 or self.components[start] >= 0:
                continue
            label = len(self.component_nodes); nodes = []; todo = deque([start])
            self.components[start] = label
            while todo:
                n = todo.popleft(); nodes.append(n)
                ix, iy = n % self.nx, n // self.nx
                for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if 0 <= ix + ox < self.nx and 0 <= iy + oy < self.ny:
                        m = n + oy * self.nx + ox
                        if self.components[m] < 0 and self.clearance[m] >= config['mech']['radius'] + .4:
                            self.components[m] = label; todo.append(m)
            self.component_nodes.append(nodes)

    def nearby(self, x, y, radius=0):
        ids = set()
        for by in range(math.floor((y - radius) / self.BUCKET), math.floor((y + radius) / self.BUCKET) + 1):
            for bx in range(math.floor((x - radius) / self.BUCKET), math.floor((x + radius) / self.BUCKET) + 1):
                ids.update(self.buckets.get((bx, by), ()))
        return ids

    def ground(self, x, y):
        t = self.terrain
        u = max(0, min(t['nx'] - 1.00001, (x - t['minX']) / t['step']))
        v = max(0, min(t['ny'] - 1.00001, (y - t['minY']) / t['step']))
        i, j = int(u), int(v)
        a, b = u - i, v - j
        n = t['nx']; k = j * n + i; h = self.samples
        return ((h[k] * (1 - a) + h[k + 1] * a) * (1 - b)
                + (h[k + n] * (1 - a) + h[k + n + 1] * a) * b) * t.get('scale', .01)

    def clear_at(self, x, y, z, height, cap=18):
        b = self.bounds
        best = min(cap, x - b['minX'], b['maxX'] - x, y - b['minY'], b['maxY'] - y)
        for i in self.nearby(x, y, max(0, best)):
            p = self.prisms[i]
            if p['top'] <= z + self.cfg['mech']['step_up'] or p['base'] >= z + height:
                continue
            lo_x, lo_y, hi_x, hi_y = p['_bbox']
            if x < lo_x - best or x > hi_x + best or y < lo_y - best or y > hi_y + best:
                continue
            holes = p.get('holes', [])
            in_hole = any(inside(x, y, h) for h in holes)
            if inside(x, y, p['ring']) and not in_hole:
                return 0.0
            d = min([edge_distance(x, y, p['ring'])] + [edge_distance(x, y, h) for h in holes])
            best = min(best, d)
        return max(0, best)

    def xy(self, node):
        return self.x0 + node % self.nx * self.CELL, self.y0 + node // self.nx * self.CELL

    def node(self, pos):
        ix = max(0, min(self.nx - 1, round((pos[0] - self.x0) / self.CELL)))
        iy = max(0, min(self.ny - 1, round((pos[1] - self.y0) / self.CELL)))
        return iy * self.nx + ix

    def nearest(self, pos, radius):
        start = self.node(pos)
        ix, iy = start % self.nx, start // self.nx
        candidates = []
        for dy in range(-6, 7):
            for dx in range(-6, 7):
                if 0 <= ix + dx < self.nx and 0 <= iy + dy < self.ny:
                    n = (iy + dy) * self.nx + ix + dx
                    if self.clearance[n] >= radius + .4:
                        x, y = self.xy(n)
                        candidates.append(((x - pos[0]) ** 2 + (y - pos[1]) ** 2, n))
        return min(candidates)[1] if candidates else None

    def walk_clear(self, a, b, radius, height, ground=True):
        distance = math.dist(a[:2], b[:2])
        steps = max(1, math.ceil(distance / 1.5))
        # Sampling alone can miss the closest point while rounding a corner.
        # Check the entire swept cylinder against footprint edges as well.
        ids = self.nearby((a[0] + b[0]) * .5, (a[1] + b[1]) * .5, distance * .5 + radius)
        for i in ids:
            p = self.prisms[i]
            if p['top'] <= min(a[2], b[2]) + self.cfg['mech']['step_up'] or p['base'] >= max(a[2], b[2]) + height:
                continue
            for ring in [p['ring']] + p.get('holes', []):
                if segment_edge_distance(a, b, ring) < radius + .15:
                    return False
        last_z = a[2]
        slope = math.tan(math.radians(self.cfg['mech']['max_slope_deg']))
        for j in range(1, steps + 1):
            f = j / steps
            x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
            z = self.ground(x, y) if ground else a[2] + (b[2] - a[2]) * f
            if ground and z - last_z > max(self.cfg['mech']['step_up'], slope * distance / steps):
                return False
            if self.clear_at(x, y, z, height, radius + .2) < radius + .15:
                return False
            last_z = z
        return True

    def shot_clear(self, a, b):
        """Exact polygon/height intervals; terrain sampled at <= 1 m. Trees pass shots."""
        dx, dy, dz = (b[i] - a[i] for i in range(3))
        distance = math.hypot(dx, dy)
        ids = set()
        # Supercover via the segment bounding box: corner-crossed buckets must
        # not disappear between discrete samples of the line.
        for iy in range(math.floor(min(a[1], b[1]) / self.BUCKET), math.floor(max(a[1], b[1]) / self.BUCKET) + 1):
            for ix in range(math.floor(min(a[0], b[0]) / self.BUCKET), math.floor(max(a[0], b[0]) / self.BUCKET) + 1):
                ids.update(self.buckets.get((ix, iy), ()))
        for idx in ids:
            p = self.prisms[idx]
            if max(a[2], b[2]) < p['base'] or min(a[2], b[2]) > p['top']:
                continue
            cuts = [0., 1.]
            if abs(dz) > 1e-9:
                cuts.extend(t for t in ((p['base'] - a[2]) / dz, (p['top'] - a[2]) / dz) if 0 < t < 1)
            for ring in [p['ring']] + p.get('holes', []):
                ax, ay = ring[-2:]
                for i in range(0, len(ring), 2):
                    bx, by = ring[i:i + 2]; ex, ey = bx - ax, by - ay
                    den = dx * ey - dy * ex
                    if abs(den) > 1e-10:
                        u, v = ax - a[0], ay - a[1]
                        t = (u * ey - v * ex) / den
                        s = (u * dy - v * dx) / den
                        if 0 <= t <= 1 and 0 <= s <= 1:
                            cuts.append(t)
                    ax, ay = bx, by
            cuts.sort()
            for low, high in zip(cuts, cuts[1:]):
                t = (low + high) * .5
                z = a[2] + dz * t
                if p['base'] <= z <= p['top']:
                    x, y = a[0] + dx * t, a[1] + dy * t
                    if inside(x, y, p['ring']) and not any(inside(x, y, h) for h in p.get('holes', [])):
                        return False
        count = max(1, math.ceil(math.dist(a, b)))
        for j in range(count + 1):
            t = j / count
            if a[2] + dz * t < self.ground(a[0] + dx * t, a[1] + dy * t) - .03:
                return False
        return True


class Navigator:
    def __init__(self, world, max_nodes=8000):
        self.w = world
        self.path = []
        self.search = None
        self.goal_node = None
        self.radius = 0
        self.expansions = 0
        self.edges = {}
        self.failed_goal = None
        self.projections = {}
        self.failures = {}
        self.max_nodes = max_nodes
        self.calls = 0
        self.follow = None

    def boundary_direction(self, me, goal, now):
        """Bounded wall following for mandatory objectives when A* is unavailable.

        This returns a continuously checked horizontal segment, not a claim
        that a full route exists. The next observation still controls movement.
        """
        w = self.w; p = me['pos']; s = me['stats']
        distance = math.dist(p[:2], goal[:2])
        if distance < 1:
            return [0, 0]
        direct = math.atan2(goal[1] - p[1], goal[0] - p[0])
        ground = abs(p[2] - w.ground(*p[:2])) < 2
        def clear(angle, length=6):
            q = [p[0] + length * math.cos(angle), p[1] + length * math.sin(angle)]
            q.append(w.ground(*q) if ground else p[2])
            return w.walk_clear(p, q, s['radius'], s['height'], ground)
        state = self.follow
        if state is None or math.dist(state['goal'], goal[:2]) > 15:
            if clear(direct, min(10, distance)):
                self.follow = None
                return [math.cos(direct) * 10, math.sin(direct) * 10]
            state = self.follow = dict(goal=list(goal[:2]), yaw=direct, hand=1,
                                       hit=distance, best=distance, changed=now, active=False)
        if distance < state['best'] - 2:
            state['best'] = distance; state['changed'] = now
        # Rejoin the destination bearing only after making genuine progress.
        if clear(direct, min(10, distance)) and distance < state['hit'] - 3:
            self.follow = None
            return [math.cos(direct) * 10, math.sin(direct) * 10]
        if now - state['changed'] > 5:
            state['hand'] *= -1; state['changed'] = now
        # Keep a chosen wall on one side: turn toward it, then sweep away
        # until a complete 6 m cylinder sweep fits. At most 16 probes.
        for i in range(16):
            angle = state['yaw'] + state['hand'] * ((-math.pi / 2 if state['active'] else 0) + i * math.pi / 8)
            if clear(angle):
                state['yaw'] = angle; state['active'] = True
                return [math.cos(angle) * 6, math.sin(angle) * 6]
        return [0, 0]

    def direction(self, me, goal, deadline, now=None, critical=False):
        self.calls += 1
        if now is None:
            now = self.calls * .1
        w = self.w; p = me['pos']; radius = me['stats']['radius']; height = me['stats']['height']
        # Roof/air travel uses continuous geometry, never the ground grid.
        on_ground_map = abs(p[2] - w.ground(*p[:2])) < 2
        dest = [goal[0], goal[1], w.ground(*goal[:2])]
        if math.dist(p[:2], goal[:2]) < 35 and w.walk_clear(p, dest, radius, height, on_ground_map):
            self.path = []; self.search = None
            self.failed_goal = None; self.follow = None
            return [goal[0] - p[0], goal[1] - p[1]]
        target = w.nearest(goal, radius)
        if target is None:
            self.failed_goal = w.node(goal)
            return self.boundary_direction(me, goal, now) if critical else [goal[0] - p[0], goal[1] - p[1]]
        requested = target
        start_node = w.nearest(p, radius)
        component = w.components[start_node] if start_node is not None else -1
        failure_key = (target, round(radius, 2), round(height, 2), component)
        if failure_key in self.failures:
            failure = self.failures[failure_key]
            if now - failure['at'] < (2 if critical else 12) and math.dist(p[:2], failure['from']) < 20:
                self.failed_goal = requested
                self.path = []; self.search = None
                return self.boundary_direction(me, goal, now) if critical else [0, 0]
            del self.failures[failure_key]
        if start_node is not None and w.components[start_node] != w.components[target]:
            self.failed_goal = target
            key = (target, w.components[start_node], round(radius, 2))
            if key not in self.projections:
                allowed = w.component_nodes[w.components[start_node]]
                valid = (n for n in allowed if w.clearance[n] >= radius + .4)
                self.projections[key] = min(valid, key=lambda n: math.dist(w.xy(n), goal[:2]), default=start_node)
            target = self.projections[key]
        elif failure_key not in self.failures:
            self.failed_goal = None
        if target != self.goal_node or abs(radius - self.radius) > .01:
            self.path = []; self.search = None; self.goal_node = target; self.radius = radius
        if not self.path and self.search is None:
            start = w.nearest(p, radius)
            if start is not None:
                self.search = ([(0., start)], {start: 0.}, {}, start, set())
        if self.search:
            heap, costs, parent, start, closed = self.search
            tx, ty = w.xy(target)
            for iteration in range(600):
                if not heap or time.perf_counter() >= deadline or len(closed) >= self.max_nodes:
                    break
                _, n = heapq.heappop(heap)
                if n in closed:
                    continue
                closed.add(n)
                if n == target:
                    path = [n]
                    while path[-1] != start:
                        path.append(parent[path[-1]])
                    self.path = list(reversed(path)); self.search = None
                    break
                self.expansions += 1
                ix, iy = n % w.nx, n // w.nx
                for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    if not (0 <= ix + ox < w.nx and 0 <= iy + oy < w.ny):
                        continue
                    m = n + oy * w.nx + ox
                    if m in closed:
                        continue
                    if w.clearance[m] < radius + .4:
                        continue
                    if ox and oy and (w.clearance[n + ox] < radius + .4 or w.clearance[n + oy * w.nx] < radius + .4):
                        continue
                    distance = w.CELL * (math.sqrt(2) if ox and oy else 1)
                    # The walking limit restricts ascent. Descents may fall
                    # under gravity; treating every drop as an uphill wall can
                    # incorrectly disconnect entire low-ground regions.
                    if w.heights[m] - w.heights[n] > distance * math.tan(math.radians(w.cfg['mech']['max_slope_deg'])):
                        continue
                    if min(w.clearance[n], w.clearance[m]) < radius + distance * .5 + .2:
                        # Stepping down and stepping up are different queries.
                        key = (n, m, round(radius, 2), round(height, 2))
                        if key not in self.edges:
                            ax, ay = w.xy(n); bx, by = w.xy(m)
                            self.edges[key] = w.walk_clear([ax, ay, w.heights[n]], [bx, by, w.heights[m]], radius, height)
                        if not self.edges[key]:
                            continue
                    cost = costs[n] + distance * (1 + .8 / max(1, w.clearance[m] - radius))
                    if cost < costs.get(m, math.inf):
                        costs[m] = cost; parent[m] = n
                        x, y = w.xy(m)
                        heapq.heappush(heap, (cost + math.hypot(x - tx, y - ty), m))
            if self.search and (not heap or len(closed) >= self.max_nodes):
                self.search = None
                self.failed_goal = requested
                closest = min(closed, key=lambda n: math.dist(w.xy(n), goal[:2]), default=start)
                self.failures[failure_key] = {'at': now, 'from': list(p[:2]), 'node': closest}
                if len(self.failures) > 128:
                    del self.failures[next(iter(self.failures))]
                partial = [closest]
                while partial[-1] != start:
                    partial.append(parent[partial[-1]])
                self.path = list(reversed(partial))
            elif self.search and heap:
                # Follow the best frontier route while the bounded search continues.
                # Direct steering during a long search can trap us at the first wall.
                tip = heap[0][1]
                preview = [tip]
                while preview[-1] != start and preview[-1] in parent:
                    preview.append(parent[preview[-1]])
                self.path = list(reversed(preview))
        if self.path:
            # Discard passed waypoints, then use only geometry-validated shortcuts.
            nearest = min(range(len(self.path)), key=lambda i: math.dist(w.xy(self.path[i]), p[:2]))
            self.path = self.path[nearest:]
            for index in range(min(7, len(self.path) - 1), -1, -1):
                x, y = w.xy(self.path[index]); z = w.heights[self.path[index]]
                if w.walk_clear(p, [x, y, z], radius, height, on_ground_map):
                    if index == len(self.path) - 1 and math.dist(p[:2], (x, y)) < 2:
                        self.path = []
                    return [x - p[0], y - p[1]]
            self.path = []
        if self.failed_goal == requested:
            return self.boundary_direction(me, goal, now) if critical else [0, 0]
        return [goal[0] - p[0], goal[1] - p[1]]
