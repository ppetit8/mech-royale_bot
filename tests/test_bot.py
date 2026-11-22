import copy
import json
import math
import struct
import sys
import tempfile
import time
import unittest
import select
import shutil
import subprocess
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot import Bot, future_zone
from combat import Combat, intercept, mortar_solution
from world import Navigator, World

FIXTURE = json.loads((ROOT / 'tests/fixtures.json').read_text())


def make_world(prisms=()):
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name) / 'v2'; root.mkdir()
    world = dict(bounds=dict(minX=-80, maxX=80, minY=-80, maxY=80),
                 terrain=dict(minX=-80, minY=-80, step=1, nx=161, ny=161, scale=.01), prisms=list(prisms))
    (root / 'world.json').write_text(json.dumps(world))
    (root / 'terrain.i16').write_bytes(struct.pack('<h', 0) * 161 * 161)
    return temp, World(temp.name, FIXTURE['hello']['config'])


def wall(x0=-2, x1=2, y0=-35, y1=35, base=0, top=25, holes=None):
    return dict(kind='building', base=base, top=top,
                ring=[x0,y0,x1,y0,x1,y1,x0,y1], holes=holes or [])


def observation():
    o = copy.deepcopy(FIXTURE['obs'])
    o['self']['pos'] = [-40, 0, 0]
    o['self']['aim'] = [0, 0]
    o['zone'].update(center=[0, 0], radius=200, next_center=[0, 0], next_radius=150)
    return o


def enemy(pos=(40,0,0), vel=(0,0,0)):
    return dict(id=5, kind='mech', pos=list(pos), vel=list(vel), aim=[math.pi,0],
                hp=1400,max_hp=1400,cubes=0,weapons=['gun'],charging=False)


class BallisticsTests(unittest.TestCase):
    def test_intercept_hits_lateral_target(self):
        target = dict(pos=[140,20,5], vel=[-5,16,0])
        point,t = intercept([0,0,7], target, 252,3)
        self.assertAlmostEqual(math.dist([0,0,7],point),252*t+3,places=7)
        self.assertAlmostEqual(point[1],20+16*t)

    def test_impossible_intercept_rejected(self):
        self.assertIsNone(intercept([0,0,0],dict(pos=[10,0,0],vel=[300,0,0]),252))

    def test_ballistic_endpoint_meets_moving_target(self):
        target=dict(pos=[130,20,4.5],vel=[1,7,0])
        s=FIXTURE['hello']['config']['weapons']['mortar']
        yaw,pitch,t,_=mortar_solution([0,0,9.5],target,s)
        direction=[math.cos(pitch)*math.cos(yaw),math.cos(pitch)*math.sin(yaw),math.sin(pitch)]
        at=[direction[i]*(3+s['speed']*t) + (9.5 if i==2 else 0) for i in range(3)]
        at[2]-=.5*s['gravity']*t*t
        expected=[target['pos'][i]+target['vel'][i]*t for i in range(3)]
        self.assertLess(math.dist(at,expected),.05)

    def test_mortar_out_of_range(self):
        self.assertIsNone(mortar_solution([0,0,9.5],dict(pos=[400,0,0],vel=[0,0,0]),FIXTURE['hello']['config']['weapons']['mortar']))


class GeometryTests(unittest.TestCase):
    def test_wall_blocks_shots_and_motion(self):
        temp,w=make_world([wall()])
        with temp:
            self.assertFalse(w.shot_clear([-30,0,7],[30,0,7]))
            self.assertTrue(w.shot_clear([-30,0,30],[30,0,30]))
            self.assertFalse(w.walk_clear([-6,0,0],[6,0,0],2.5,9))
            self.assertTrue(w.walk_clear([-30,50,0],[30,50,0],2.5,9))

    def test_bridge_underpass_and_tall_cube_mech(self):
        temp,w=make_world([wall(base=12,top=15)])
        with temp:
            self.assertTrue(w.walk_clear([-6,0,0],[6,0,0],2.5,9))
            self.assertFalse(w.walk_clear([-6,0,0],[6,0,0],4,14))
            self.assertTrue(w.shot_clear([-30,0,7],[30,0,7]))
            self.assertFalse(w.shot_clear([-30,0,13],[30,0,13]))

    def test_hole_is_clear_but_outer_wall_is_not(self):
        temp,w=make_world([wall(-20,20,-20,20,holes=[[-10,-10,10,-10,10,10,-10,10]])])
        with temp:
            self.assertTrue(w.shot_clear([-5,0,7],[5,0,7]))
            self.assertFalse(w.shot_clear([-30,0,7],[0,0,7]))
            self.assertGreater(w.clear_at(0,0,0,9),5)

    def test_thin_wall_not_skipped(self):
        temp,w=make_world([wall(.01,.03,-1,1)])
        with temp:
            self.assertFalse(w.shot_clear([-70,0,7],[70,0,7]))

    def test_swept_body_does_not_clip_corner(self):
        temp,w=make_world([wall()])
        with temp:
            self.assertFalse(w.walk_clear([-3.34,-37.36,0],[8,-40,0],2.5,9))

    def test_roof_height_overlap(self):
        temp,w=make_world([wall(top=20)])
        with temp:
            self.assertGreater(w.clear_at(0,0,20,9),2.5)
            self.assertEqual(w.clear_at(0,0,10,9),0)

    def test_navigation_routes_around_wall(self):
        temp,w=make_world([wall()])
        with temp:
            me=observation()['self']; me['pos']=[-40,0,0]
            nav=Navigator(w); goal=[40,0]
            for _ in range(300):
                d=nav.direction(me,goal,time.perf_counter()+.01)
                norm=math.hypot(*d)
                if norm:
                    step=min(1.17,norm)
                    q=[me['pos'][i]+d[i]/norm*step for i in range(2)]+[0]
                    if w.walk_clear(me['pos'],q,2.5,9):
                        me['pos']=q
                if math.dist(me['pos'][:2],goal)<3:
                    break
            self.assertLess(math.dist(me['pos'][:2],goal),3)

    def test_enclosed_goal_is_identified(self):
        temp,w=make_world([wall(-20,20,-20,20,holes=[[-12,-12,12,-12,12,12,-12,12]])])
        with temp:
            me=observation()['self'];nav=Navigator(w)
            nav.direction(me,[0,0],time.perf_counter()+.1)
            self.assertIsNotNone(nav.failed_goal)

    def test_mandatory_route_survives_exhausted_search_budget(self):
        temp,w=make_world([wall()])
        with temp:
            me=observation()['self'];nav=Navigator(w,max_nodes=1);goal=[40,0]
            nav.direction(me,goal,time.perf_counter()+.1,now=0,critical=True)
            direction=nav.direction(me,goal,time.perf_counter()+.1,now=.1,critical=True)
            self.assertGreater(math.hypot(*direction),1)
            q=[me['pos'][i]+direction[i] for i in range(2)]+[0]
            self.assertTrue(w.walk_clear(me['pos'],q,2.5,9))

    def test_failed_goal_retries_from_new_approach(self):
        temp,w=make_world([wall()])
        with temp:
            me=observation()['self'];nav=Navigator(w,max_nodes=1);goal=[40,0]
            nav.direction(me,goal,time.perf_counter()+.1,now=0)
            self.assertIsNotNone(nav.failed_goal)
            me['pos']=[20,-60,0];nav.max_nodes=8000
            direction=nav.direction(me,goal,time.perf_counter()+.1,now=.1)
            self.assertGreater(math.hypot(*direction),1)
            self.assertIsNone(nav.failed_goal)

    def test_failed_goal_retries_after_timeout(self):
        temp,w=make_world([wall()])
        with temp:
            me=observation()['self'];nav=Navigator(w,max_nodes=1);goal=[40,0]
            nav.direction(me,goal,time.perf_counter()+.1,now=0)
            nav.max_nodes=8000
            direction=nav.direction(me,goal,time.perf_counter()+.1,now=13)
            self.assertGreater(math.hypot(*direction),1)
            self.assertIsNone(nav.failed_goal)

    def test_fallback_routes_around_wall_with_tiny_search_budget(self):
        temp,w=make_world([wall()])
        with temp:
            me=observation()['self'];nav=Navigator(w,max_nodes=1);goal=[40,0]
            for tick in range(600):
                direction=nav.direction(me,goal,time.perf_counter()+.01,now=tick*.1,critical=True)
                norm=math.hypot(*direction)
                if norm:
                    q=[me['pos'][i]+direction[i]/norm*min(1.17,norm) for i in range(2)]+[0]
                    self.assertTrue(w.walk_clear(me['pos'],q,2.5,9))
                    me['pos']=q
                if math.dist(me['pos'][:2],goal)<3:
                    break
            self.assertLess(math.dist(me['pos'][:2],goal),3)

    def test_navigation_allows_descent_without_allowing_impossible_climb(self):
        temp,w=make_world()
        with temp:
            # A 10 m terrain ledge spans the entire map. There is a safe
            # horizontal direction to drop off, but no ground route back up.
            t=w.terrain
            for j in range(t['ny']):
                for i in range(t['nx']):
                    w.samples[j*t['nx']+i]=1000 if t['minX']+i<0 else 0
            for n in range(len(w.heights)):
                w.heights[n]=w.ground(*w.xy(n))
            self.assertFalse(w.walk_clear([10,0,0],[-10,0,10],2.5,9))
            me=observation()['self'];me['pos']=[-40,0,10]
            nav=Navigator(w);goal=[40,0]
            for tick in range(150):
                direction=nav.direction(me,goal,time.perf_counter()+.01,now=tick*.1)
                norm=math.hypot(*direction)
                if norm:
                    q=[me['pos'][i]+direction[i]/norm*min(1.17,norm) for i in range(2)]
                    q.append(w.ground(*q));me['pos']=q
                if math.dist(me['pos'][:2],goal)<3:
                    break
            self.assertLess(math.dist(me['pos'][:2],goal),3)


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp,cls.world=make_world()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def bot(self):
        h=copy.deepcopy(FIXTURE['hello']);h['map']['dir']=self.temp.name
        return Bot(h)

    def test_zone_prediction_uses_remaining_shrink(self):
        z=dict(center=[20,0],radius=80,next_center=[40,0],next_radius=40,shrink_start=10,shrink_end=30)
        c,r=future_zone(z,20,25)
        self.assertEqual(c,[30,0]);self.assertEqual(r,60)

    def test_no_fire_through_tracked_cover(self):
        temp,w=make_world([wall()])
        with temp:
            o=observation();o['mechs']=[enemy()]
            self.assertEqual(Combat(FIXTURE['hello']['config'],w).decide(o,False,False)[1],[False,False])

    def test_actual_aim_prevents_wasted_gun_fire(self):
        o=observation();o['mechs']=[enemy()];o['self']['aim']=[math.pi,0]
        aim,fire,_,_=Combat(FIXTURE['hello']['config'],self.world).decide(o,False,False)
        self.assertAlmostEqual(aim[0],0);self.assertFalse(any(fire))

    def test_aligned_gun_fires_with_lead(self):
        o=observation();o['mechs']=[enemy()]
        c=Combat(FIXTURE['hello']['config'],self.world)
        aim,_,_,_=c.decide(o,False,False);o['self']['aim']=aim
        self.assertTrue(c.decide(o,False,False)[1][0])

    def test_laser_charges_then_releases(self):
        o=observation();o['mechs']=[enemy()]
        o['self']['weapons']=[None,dict(kind='laser',cooldown=0,charge=0,stats=FIXTURE['hello']['config']['weapons']['laser'])]
        c=Combat(FIXTURE['hello']['config'],self.world)
        aim,fire,_,_=c.decide(o,False,False);self.assertTrue(fire[1])
        o['self']['aim']=aim;o['self']['weapons'][1]['charge']=.75
        self.assertFalse(c.decide(o,False,False)[1][1])

    def test_laser_can_charge_while_gun_leads(self):
        o=observation();o['mechs']=[enemy(vel=(0,15,0))]
        o['self']['weapons'][1]=dict(kind='laser',cooldown=0,charge=0,stats=FIXTURE['hello']['config']['weapons']['laser'])
        self.assertTrue(Combat(FIXTURE['hello']['config'],self.world).decide(o,False,False)[1][1])

    def test_recovery_does_not_reset_regen_by_firing(self):
        o=observation();o['mechs']=[enemy()];o['self']['hp']=500
        b=self.bot();a=b.act(o)
        self.assertTrue(b.recovering);self.assertFalse(any(a['fire']))

    def test_empty_gun_reloads_during_engagement(self):
        o=observation();o['mechs']=[enemy()];o['self']['weapons'][0]['ammo']=0
        a=self.bot().act(o)
        self.assertTrue(a['reload']);self.assertFalse(a['fire'][0])

    def test_empty_gun_reloads_while_recovering(self):
        o=observation();o['mechs']=[enemy()];o['self']['hp']=500
        o['self']['weapons'][0]['ammo']=0
        self.assertTrue(self.bot().act(o)['reload'])

    def test_recovery_returns_fire_under_active_attack(self):
        o=observation();o['mechs']=[enemy()];o['self']['hp']=500
        o['events']=[dict(type='damaged',weapon='gun',amount=45,bearing=0,by=5)]
        c=Combat(FIXTURE['hello']['config'],self.world)
        aim,_,_,_=c.decide(o,True,False);o['self']['aim']=aim
        self.assertTrue(c.decide(o,True,False)[1][0])
        # Keep counterfire stable between consecutive enemy bullets.
        o['t']+=.3;o['events']=[]
        self.assertTrue(c.decide(o,True,False)[1][0])
        o['t']+=2
        self.assertFalse(any(c.decide(o,True,False)[1]))

    def test_recovery_returns_fire_against_close_pursuer(self):
        o=observation();o['mechs']=[enemy((-10,0,0))];o['self']['hp']=500
        c=Combat(FIXTURE['hello']['config'],self.world)
        aim,_,_,_=c.decide(o,True,False);o['self']['aim']=aim
        self.assertTrue(c.decide(o,True,False)[1][0])

    def test_ready_laser_aim_beats_cooling_gun_aim(self):
        o=observation();o['mechs']=[enemy(vel=(0,15,0))]
        o['self']['weapons'][0]['cooldown']=.2
        o['self']['weapons'][1]=dict(kind='laser',cooldown=0,charge=0,stats=FIXTURE['hello']['config']['weapons']['laser'])
        aim,_,_,_=Combat(FIXTURE['hello']['config'],self.world).decide(o,False,False)
        self.assertAlmostEqual(aim[0],0)

    def test_escape_does_not_start_slow_laser_charge(self):
        o=observation();o['mechs']=[enemy((-10,0,0))];o['self']['hp']=500
        o['self']['weapons'][1]=dict(kind='laser',cooldown=0,charge=0,stats=FIXTURE['hello']['config']['weapons']['laser'])
        self.assertFalse(Combat(FIXTURE['hello']['config'],self.world).decide(o,True,False)[1][1])

    def test_pickup_rejects_roof_item(self):
        o=observation();o['pickups']=[dict(id=8000,kind='laser',pos=[-40,0,10])]
        self.assertNotIn('take',self.bot().act(o))

    def test_pickup_takes_eligible_item(self):
        o=observation();o['pickups']=[dict(id=8000,kind='laser',pos=[-40,0,0])]
        self.assertEqual(self.bot().act(o)['take'],8000)

    def test_outside_zone_moves_inward(self):
        o=observation();o['self']['in_zone']=False
        o['zone'].update(radius=20,next_radius=10)
        a=self.bot().act(o)
        self.assertGreater(a['move'][0],.5);self.assertTrue(a['boost'])

    def test_zero_radius_zone_produces_finite_action(self):
        o=observation();o['t']=420;o['self']['in_zone']=False
        o['zone'].update(radius=0,next_radius=0,shrink_start=390,shrink_end=415)
        a=self.bot().act(o)
        json.dumps(a,allow_nan=False)
        self.assertGreater(a['move'][0],.5)

    def test_zone_rotation_goal_avoids_building_interior(self):
        temp,w=make_world([wall(-20,-5,-10,10)])
        with temp:
            h=copy.deepcopy(FIXTURE['hello']);h['map']['dir']=temp.name
            b=Bot(h);o=observation();o['self']['pos']=[-60,0,0]
            o['zone'].update(radius=30,next_radius=20)
            goal=b.strategic_goal(o,[],True)
            self.assertGreater(w.clear_at(*goal,w.ground(*goal),9),2.5)
            self.assertLess(math.dist(goal,[0,0]),20)

    def test_mandatory_stall_recovers_when_controller_stops(self):
        o=observation();o['self']['in_zone']=False
        o['zone'].update(radius=20,next_radius=10)
        b=self.bot();jumps=[]
        with patch.object(b.nav,'direction',return_value=[0,0]), patch.object(b,'movement',return_value=[0,0]):
            for tick in range(20):
                o['tick']=tick*2;o['t']=tick*.1
                jumps.append(b.act(o)['jump'])
        self.assertTrue(any(jumps))

    def test_moving_in_loop_triggers_bounded_escape(self):
        o=observation();o['self']['in_zone']=False
        o['zone'].update(radius=20,next_radius=10)
        b=self.bot();b.goal_kind='zone';jumps=[]
        with patch.object(b,'strategic_goal',return_value=[40,0]), patch.object(b.nav,'direction',return_value=[1,0]), patch.object(b,'movement',return_value=[1,0]):
            for tick in range(100):
                a=tick*.15;o['tick']=tick*2;o['t']=tick*.1
                o['self']['pos']=[-40+5*math.cos(a),5*math.sin(a),0]
                jumps.append(b.act(o)['jump'])
        self.assertTrue(any(jumps))

    def test_low_energy_lightning_does_not_waste_reserve(self):
        o=observation();o['mechs']=[enemy((-10,0,0))];o['self']['energy']=5
        o['self']['weapons']=[None,dict(kind='lightning',cooldown=0,stats=FIXTURE['hello']['config']['weapons']['lightning'])]
        self.assertFalse(any(Combat(FIXTURE['hello']['config'],self.world).decide(o,False,False)[1]))

    def test_bullet_dodge_improves_closest_approach(self):
        o=observation();o['projectiles']=[dict(id=1,kind='gun',pos=[-10,0,4],vel=[-90,0,0])]
        b=self.bot();move=b.movement(o,[1,0],[],False,time.perf_counter()+1)
        self.assertGreater(abs(move[1]),.5)

    def test_hold_stops_instead_of_following_inertia(self):
        o=observation();b=self.bot();b.last_move=[1,0]
        self.assertEqual(b.movement(o,[0,0],[],False,time.perf_counter()+1),[0,0])

    def test_standalone_runtime_ignores_obsolete_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder)/'bot.py';shutil.copyfile(ROOT/'bot.py',runtime)
            for name in ('world.py','combat.py','mechfight.py','strategy.py'):
                (Path(folder)/name).write_text("raise RuntimeError('obsolete module imported')\n")
            h=copy.deepcopy(FIXTURE['hello']);h['map']['dir']=self.temp.name
            proc=subprocess.Popen([sys.executable,'-u',str(runtime)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                def exchange(message):
                    proc.stdin.write(json.dumps(message)+'\n');proc.stdin.flush()
                    self.assertTrue(select.select([proc.stdout],[],[],5)[0])
                    return json.loads(proc.stdout.readline())
                self.assertEqual(exchange(h)['name'],'Aegis-v14')
                action=exchange(observation())
                self.assertTrue({'move','aim','fire'}.issubset(action))
                proc.stdin.write(json.dumps(dict(type='end',place=1,kills=0))+'\n');proc.stdin.flush()
                _,stderr=proc.communicate(timeout=5)
                self.assertEqual(proc.returncode,0);self.assertNotIn('Traceback',stderr)
            finally:
                if proc.poll() is None:
                    proc.kill();proc.communicate()


if __name__=='__main__':
    unittest.main()
