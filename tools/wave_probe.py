"""Paired progression probe with ground movement, gear, and two scripted hunter waves."""
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
from test_bot import FIXTURE, make_world, observation, wall

DT = .1
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


CONFIG = FIXTURE['hello']['config']
WEAPONS = CONFIG['weapons']
CUBES = CONFIG['cubes']
LOOT = CONFIG['loot']
DURATION = 30.
LAYOUTS = ('covered-crate','open-crate','swap','both','no-loot')


def weapon(kind):
    return dict(kind=kind,stats=WEAPONS[kind],cooldown=0.,charge=0.)


def move_hunter(world, actor, player, speed):
    if math.dist(actor['pos'][:2], player['pos'][:2]) < 21:
        return [0.,0.]
    bearing = yaw(actor['pos'],player['pos'])
    for turn in (0., .65, -.65, 1.3, -1.3, 1.8, -1.8):
        direction = (math.cos(bearing+turn), math.sin(bearing+turn))
        destination = [actor['pos'][i]+2.4*direction[i] for i in range(2)] + [0.]
        if world.walk_clear(actor['pos'],destination,actor['stats']['radius'],actor['stats']['height']):
            return [value*speed for value in direction]
    return [0.,0.]


def line_hit(world, start, end, targets):
    hits = [(u, actor) for actor in targets if actor['hp'] > 0
            and (u := projectile_hit(start,end,actor)) is not None]
    if hits:
        u, actor = min(hits,key=lambda hit:hit[0])
        point = [a+u*(b-a) for a,b in zip(start,end)]
        if world.shot_clear(start,point):
            return actor,point
    return None,None


def play(module, cls, hello, world, seed, layout):
    rng = random.Random(seed)
    obs = observation()
    me = obs['self']
    me.update(pos=[-39.,rng.uniform(-3,3),0.], aim=[math.pi,0.], hp=1400, max_hp=1400)
    obs['zone'].update(center=[0,0],next_center=[0,0],radius=102,next_radius=83,
                       shrink_start=40,shrink_end=60,dps=20)
    for key in ('drops','crates','cubes','pickups','sounds','beams','events','mechs','projectiles'):
        obs[key]=[]
    covered = layout in ('covered-crate','both')
    hunter_x = 46. if covered else -8.
    foes = []
    for index,(x,y) in enumerate(((hunter_x,rng.uniform(-5,5)),(25.,rng.choice((-37.,37.))))):
        hunter = copy.deepcopy(me)
        hp = rng.choice((420,520,650)) if index==0 else rng.choice((650,760,850))
        hunter.update(id=index+5,pos=[x,y,0.],hp=hp,max_hp=hp,vel=[0.,0.,0.],
                      aim=[yaw((x,y),me['pos']),0.],cubes=0)
        foes.append(hunter)
    crates = []
    if layout in ('covered-crate','open-crate','both'):
        crate = dict(id=1000,pos=[-56.,rng.uniform(-5,5),0.],hp=CONFIG['crates']['hp'],
                     stats=dict(radius=CONFIG['crates']['radius'],height=CONFIG['crates']['height']))
        crates.append(crate)
    pickups = []
    if layout in ('swap','both'):
        me['weapons'][1]=weapon('mortar')
        pickups.append(dict(id=8000,kind='laser',pos=[-38.,me['pos'][1],0.]))
    cube_items = []
    active_since = {5:5.,6:18.}
    if layout=='open-crate':
        active_since[5]=7.
    guns = {actor['id']:dict(ammo=12,ready=0.,reload=-1.) for actor in [me,*foes]}
    last_combat = {a['id']:-100. for a in [me,*foes]}
    # One hunter was seen just before the initial observation of the cover case.
    seen = {5:0.} if covered else {}
    shot_id = 0
    item_id = 5000
    bullets = []
    secondary_ready = 0.
    laser_hold = 0.
    last_boost = -100.
    longest = 0.
    late = 0
    kills = 0
    first_kill = None
    first_kill_hp = None
    first_contact_cubes = None
    first_contact_weapon = None
    entered_wave_two = False
    farmed = swaps = 0
    damage_in = damage_out = 0.
    time_alive = DURATION
    with patch.object(module,'World',return_value=world):
        bot = cls({**hello,'seed':seed})

    def damage(shooter, target, amount, kind, impact_origin):
        nonlocal kills, first_kill, first_kill_hp, damage_in, damage_out, item_id, farmed
        if target['hp']<=0:
            return
        actor = target['id']<1000
        rear = actor and abs(angle(yaw(target['pos'],impact_origin)-target['aim'][0]))>math.pi/2
        amount *= CONFIG['mech']['rear_mult'] if rear else 1
        if shooter is me:
            amount *= 1+CUBES['damage_per_cube']*min(me['cubes'],CUBES['stat_cap'])
            obs['events'].append(dict(type='hit',target=target['id'],amount=amount,weapon=kind,rear=rear))
            if actor and target is not me:
                damage_out += amount
        if target is me:
            damage_in += amount
            obs['events'].append(dict(type='damaged',amount=amount,weapon=kind,by=shooter['id'],
                                      bearing=yaw(me['pos'],impact_origin),rear=rear))
        target['hp'] -= amount
        last_combat[shooter['id']] = now
        if actor:
            last_combat[target['id']] = now
        if target['hp'] > 0 or shooter is not me or target is me:
            return
        count = 1
        if actor:
            kills += 1
            count = CUBES['death_drop_extra']
            obs['events'].append(dict(type='kill',target=target['id']))
            if target['id']==5 and first_kill is None:
                first_kill,first_kill_hp=round(now,2),round(max(0.,me['hp']),2)
                active_since[6] = min(active_since[6], now+3.)
        else:
            farmed += 1
            if random.Random(seed + 6000).random() < LOOT['crate_weapon_chance']:
                pickups.append(dict(id=8001,kind='laser',pos=target['pos'][:]))
        for _ in range(count):
            cube_items.append(dict(id=item_id,pos=target['pos'][:]))
            item_id += 1

    def fire_arm(shooter, command, reload, jitter):
        nonlocal shot_id
        state = guns[shooter['id']]
        if reload and state['reload']<0 and state['ammo']<GUN['mag']:
            state['reload']=now+GUN['reload']
        if command and state['ammo'] and state['reload']<0 and state['ready']<=now+1e-8:
            shot_id += 1
            bullets.append(gun_ray(shooter,shooter['aim'],shot_id,jitter))
            state['ammo'] -= 1
            state['ready'] = now+GUN['cooldown']

    for frame in range(round(DURATION/DT)):
        now = frame*DT
        active = [a for a in foes if a['hp']>0 and now>=active_since[a['id']]]
        if now >= active_since[5] and first_contact_cubes is None:
            first_contact_cubes = me['cubes']
            first_contact_weapon = me['weapons'][1]['kind'] if me['weapons'][1] else None
        entered_wave_two |= now >= active_since[6]
        eye = [*me['pos'][:2],me['pos'][2]+me['stats']['eye_height']]

        def visible(pos, height):
            distance = math.dist(eye[:2],pos[:2])
            if distance>VISION['range'] or (distance>VISION['near_range'] and
                    abs(angle(yaw(eye,pos)-me['aim'][0]))>math.radians(VISION['fov_deg']/2)):
                return False
            return world.shot_clear(eye,[*pos[:2],pos[2]+height])

        obs['mechs'] = []
        for actor in foes:
            if actor['hp']<=0:
                continue
            if actor in active and visible(actor['pos'],actor['stats']['height']*.55):
                seen[actor['id']] = now
            if now-seen.get(actor['id'],-100.)<=VISION['memory_s']:
                obs['mechs'].append({key:actor[key] for key in ('id','pos','vel','aim','hp','max_hp','cubes')}
                                    | dict(kind='mech',weapons=['gun'],charging=False))
        obs['crates']=[{key:c[key] for key in ('id','pos','hp')} for c in crates
                       if c['hp']>0 and visible(c['pos'],c['stats']['height']*.7)]
        obs['cubes']=[c for c in cube_items if visible(c['pos'],.5)]
        obs['pickups']=[item for item in pickups if visible(item['pos'],.5)]
        obs.update(t=now,tick=2*frame,alive=16-kills,
                   projectiles=[b for b in bullets if b['by']!=me['id'] and math.dist(b['pos'],me['pos'])<95])
        me['in_zone']=math.hypot(*me['pos'][:2])<=obs['zone']['radius']
        for state in guns.values():
            if 0<=state['reload']<=now+1e-8:
                state.update(ammo=GUN['mag'],reload=-1.)
        state=guns[me['id']]
        me['weapons'][0].update(ammo=state['ammo'],cooldown=max(0.,state['ready']-now),reload=max(0.,state['reload']-now))
        secondary=me['weapons'][1]
        if secondary:
            secondary['cooldown']=max(0.,secondary_ready-now)
        start=time.perf_counter()
        action=bot.act(obs)
        elapsed=(time.perf_counter()-start)*1000
        longest=max(longest,elapsed)
        late+=elapsed>50
        obs['events']=[]
        aim = me['aim']
        desired = action['aim']
        limit=me['stats']['turn_rate']*DT
        pitch_limit=me['stats']['pitch_rate']*DT
        me['aim']=[angle(aim[0]+max(-limit,min(limit,angle(desired[0]-aim[0])))),
                   aim[1]+max(-pitch_limit,min(pitch_limit,desired[1]-aim[1]))]
        jitter=random.Random(seed*100000+frame*31+me['id']).gauss(0.,math.radians(.6))
        fire_arm(me,action['fire'][0],action['reload'],jitter)

        def direction(aim):
            return [math.cos(aim[1])*math.cos(aim[0]),math.cos(aim[1])*math.sin(aim[0]),math.sin(aim[1])]

        if secondary and now>=secondary_ready-1e-8:
            kind=secondary['kind']
            stats=secondary['stats']
            axis=direction(me['aim'])
            origin=[*me['pos']]
            origin[2]+=me['stats']['height']+.5 if kind=='mortar' else me['stats']['muzzle_height']
            origin=[a+b*(me['stats']['radius']+.5) for a,b in zip(origin,axis)]
            if kind=='laser':
                if action['fire'][1]:
                    secondary['charge']=min(stats['charge'],secondary['charge']+DT)
                    laser_hold+=DT
                if (not action['fire'][1] and secondary['charge']) or laser_hold>=stats['charge']+stats['hold_s']:
                    strength=max(stats['min_frac'],secondary['charge']/stats['charge'])
                    end=[x+v*stats['range'] for x,v in zip(origin,axis)]
                    target,_=line_hit(world,origin,end,[*active,*crates])
                    if target:
                        damage(me,target,stats['damage']*strength,kind,origin)
                    secondary['charge'],laser_hold=0.,0.
                    secondary_ready=now+stats['cooldown']
            elif kind=='mortar' and action['fire'][1]:
                shot_id+=1
                bullets.append(dict(id=shot_id,kind=kind,by=me['id'],pos=origin,
                                    vel=[v*stats['speed'] for v in axis],remaining=stats['ttl']))
                secondary_ready=now+stats['cooldown']
        item=next((item for item in pickups if item['id']==action.get('take')),None)
        if item and math.dist(item['pos'][:2],me['pos'][:2])<LOOT['pickup_radius']:
            slot=action.get('drop',1)
            replaced=me['weapons'][slot]
            if slot==1 and (not replaced or (action.get('drop')==1 and not replaced.get('charge',0.))):
                me['weapons'][1]=weapon(item['kind'])
                secondary_ready=now+max(LOOT['equip_s'],WEAPONS[item['kind']]['cooldown'])
                laser_hold=0.
                pickups.remove(item)
                swaps+=bool(replaced)
        walk = action['move']
        if me['weapons'][1] and me['weapons'][1].get('charge',0):
            walk=[x*me['stats']['charge_move_mult'] for x in walk]
        step_ground(world,me,walk,action['boost'] and me['energy']>0)
        if action['boost']:
            me['energy']=max(0.,me['energy']-me['stats']['boost_drain']*DT)
            last_boost=now
        elif now-last_boost>=me['stats']['energy_regen_delay']:
            me['energy']=min(me['max_energy'],me['energy']+me['stats']['energy_regen']*DT)
        for actor in active:
            if actor['hp']<=0:
                continue
            distance=math.dist(actor['pos'][:2],me['pos'][:2])
            source=[*actor['pos'][:2], actor['pos'][2]+actor['stats']['muzzle_height']]
            center=[*me['pos'][:2],me['pos'][2]+me['stats']['height']*.55]
            lead=[center[i]+me['vel'][i]*distance/GUN['speed'] for i in range(3)]
            actor['aim']=[yaw(source,lead),math.atan2(lead[2]-source[2],max(1.,distance))]
            can_fire=distance<135 and world.shot_clear(source,center)
            jitter=random.Random(seed*100000+frame*31+actor['id']).gauss(0.,math.radians(1.8 if actor['id']==5 else 1.1))
            fire_arm(actor,can_fire,guns[actor['id']]['ammo']==0,jitter)
            step_ground(world,actor,move_hunter(world,actor,me,.70 if actor['id']==5 else .92),False)
        pending=[]
        for bullet in bullets:
            mortar=bullet['kind']=='mortar'
            p=bullet['pos']
            duration=min(DT,bullet['remaining'] if mortar else bullet['remaining']/GUN['speed'])
            q=[p[i]+bullet['vel'][i]*duration for i in range(3)]
            if mortar:
                q[2]-=.5*WEAPONS['mortar']['gravity']*duration**2
            from_us=bullet['by']==me['id']
            shooter=me if from_us else next(a for a in foes if a['id']==bullet['by'])
            targets=[*active,*crates] if from_us else [me]
            hit,impact=line_hit(world,p,q,targets)
            clear=world.shot_clear(p,q)
            if mortar and (hit is not None or not clear):
                s=WEAPONS['mortar']
                if impact is None:
                    low,high=0.,1.
                    for _ in range(6):
                        fraction=(low+high)/2
                        point=[a+fraction*(b-a) for a,b in zip(p,q)]
                        if world.shot_clear(p,point):
                            low=fraction
                        else:
                            high=fraction
                    impact=[a+low*(b-a) for a,b in zip(p,q)]
                for target in targets:
                    center=[*target['pos'][:2],target['pos'][2]+target['stats']['height']*.5]
                    distance=math.dist(impact,center)
                    if target is hit or (distance < s['splash_radius'] and world.shot_clear(impact,center)):
                        splash=s['splash']*max(s['splash_edge'],1-(1-s['splash_edge'])*distance/s['splash_radius'])
                        damage(shooter,target,splash+(s['damage'] if target is hit else 0),bullet['kind'],impact)
            elif hit is not None:
                damage(shooter,hit,GUN['damage'],'gun',p)
            elif clear and duration>=DT-1e-8:
                bullet['pos']=q
                bullet['remaining']-=DT if mortar else DT*GUN['speed']
                if mortar:
                    bullet['vel'][2]-=WEAPONS['mortar']['gravity']*DT
                if bullet['remaining']>1e-8:
                    pending.append(bullet)
        bullets=pending
        for actor in [me,*active]:
            if not actor['hp']>0:
                continue
            if math.hypot(*actor['pos'][:2])>obs['zone']['radius']:
                actor['hp']-=20*DT
                last_combat[actor['id']]=now
            elif now-last_combat[actor['id']]>=actor['stats']['regen_delay']:
                actor['hp']=min(actor['max_hp'],actor['hp']+actor['stats']['regen_per_s']*DT)
        if me['hp']<=0:
            time_alive=round(now+DT,2)
            break
        for c in cube_items[:]:
            if math.dist(c['pos'][:2],me['pos'][:2])<=CUBES['pickup_radius']:
                cube_items.remove(c)
                me['cubes']+=1
                old_hp=me['max_hp']
                me['max_hp']=CONFIG['mech']['hp']*(1+CUBES['hp_per_cube']*min(me['cubes'],CUBES['stat_cap']))
                me['hp']+=me['max_hp']-old_hp
                scale=1+CUBES['size_per_cube']*me['cubes']
                for field in ('radius','height','muzzle_height','eye_height'):
                    me['stats'][field]=CONFIG['mech'][field]*scale
                obs['events'].append(dict(type='pickup',cubes=me['cubes']))
    return dict(kills=kills,first_kill_s=first_kill,first_kill_hp=first_kill_hp,
                second_wave_reached=entered_wave_two,survived=me['hp']>0,survival_s=time_alive,
                hp=round(max(0.,me['hp']),1),cubes=me['cubes'],crates=farmed,swaps=swaps,
                first_contact_cubes=first_contact_cubes,first_contact_weapon=first_contact_weapon,
                damage_in=round(damage_in,2),damage_out=round(damage_out,2),
                maximum_ms=round(longest,3),late_decisions=late)


def compare(first_seed, trials, variants):
    baseline=load(ROOT/'tools'/'baseline','wave_v8')
    new=load(ROOT,'wave_v14')
    versions={'V8':(baseline,baseline.Bot)}
    config={'farm':dict(farm_under_cover=True,swap_mortar_for_laser=False),
            'swap':dict(farm_under_cover=False,swap_mortar_for_laser=True),
            'both':dict(farm_under_cover=True,swap_mortar_for_laser=True),
            'release':{}}
    for name in variants:
        versions[name]=new,type('WaveCandidate',(new.Bot,),config[name])
    rows=[]
    boot=time.perf_counter()
    for layout in LAYOUTS:
        prisms=[wall(-4,4,-14,14)] if layout in ('covered-crate','both') else []
        temporary,world=make_world(prisms)
        with temporary:
            hello=copy.deepcopy(FIXTURE['hello'])
            hello['map']['dir']=temporary.name
            for index in range(trials):
                seed=first_seed+LAYOUTS.index(layout)*1000+index
                outcomes={name:play(module,cls,hello,world,seed,layout) for name,(module,cls) in versions.items()}
                rows.append(dict(seed=seed,layout=layout,**outcomes))
    def summary(name,group):
        entries=[row[name] for row in group]
        first=[a for a in entries if a['first_kill_s'] is not None]
        return dict(first_kills=len(first), second_wave=sum(a['second_wave_reached'] for a in entries),
                    survivors=sum(a['survived'] for a in entries), kills=sum(a['kills'] for a in entries),
                    mean_first_kill_hp=round(statistics.mean(a['first_kill_hp'] for a in first),1) if first else None,
                    mean_final_hp=round(statistics.mean(a['hp'] for a in entries),1),
                    crates=sum(a['crates'] for a in entries),swaps=sum(a['swaps'] for a in entries),
                    maximum_ms=max(a['maximum_ms'] for a in entries),late_decisions=sum(a['late_decisions'] for a in entries))
    return dict(seed=first_seed,runs_per_policy=len(rows), elapsed_s=round(time.perf_counter()-boot,2),
                bot_sha256=hashlib.sha256((ROOT/'bot.py').read_bytes()).hexdigest(),
                metrics={name:summary(name,rows) for name in versions},
                per_layout={layout:{name:summary(name,[r for r in rows if r['layout']==layout]) for name in versions}
                            for layout in LAYOUTS},rows=rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=int,default=12500)
    parser.add_argument('--trials',type=int,default=6,help='Seeds per layout')
    parser.add_argument('--variant',action='append',choices=('farm','swap','both','release'))
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.trials<1:
        parser.error('--trials must be positive')
    report=compare(args.seed,args.trials,args.variant or ['farm','swap','both'])
    if args.output:
        args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key not in ('rows','per_layout')},indent=2))
