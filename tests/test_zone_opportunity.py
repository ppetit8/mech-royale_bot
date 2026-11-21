"""Resource detours must stay local, reachable, and inside the next zone."""
import copy
import math
import unittest
from unittest.mock import patch

from test_bot import Bot, FIXTURE, enemy, make_world, observation, wall


class ZoneOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.obs = observation()
        self.obs.update(t=0., tick=0, events=[], sounds=[], crates=[], cubes=[], pickups=[], drops=[], mechs=[])
        self.obs['zone'].update(center=[0,0], radius=73, next_center=[-25,0], next_radius=40,
                                shrink_start=2, shrink_end=8)
        self.obs['self'].update(hp=1400, pos=[-40,0,0], in_zone=True)
        self.bot = self.make_bot()
        self.cube = {'id':5000,'pos':[-22,0,0]}
        self.obs['cubes'] = [self.cube]

    def make_bot(self, geometry=()):
        temporary, _ = make_world(geometry)
        self.addCleanup(temporary.cleanup)
        hello=copy.deepcopy(FIXTURE['hello'])
        hello['map']['dir']=temporary.name
        return Bot(hello)

    def choose(self):
        with patch('time.perf_counter',return_value=0):
            action=self.bot.act(self.obs)
        return self.bot.goal_kind, action

    def test_cube_inside_next_ring_remains_available(self):
        goal,act=self.choose()
        self.assertEqual(goal,'cube')
        self.assertGreater(act['move'][0],.5)

    def test_next_circle_boundary_bait_is_rejected(self):
        self.cube['pos']=[10,0,0]
        self.assertEqual(self.choose()[0],'zone')

    def test_outside_or_urgent_takes_priority(self):
        self.obs['self']['in_zone']=False
        self.assertEqual(self.choose()[0],'zone')

    def test_nearby_opponent_prevents_detour(self):
        self.obs['mechs']=[enemy((7,-10,0))]
        self.assertEqual(self.choose()[0],'zone')

    def test_wall_cannot_turn_short_detour_into_slow_route(self):
        self.bot=self.make_bot([wall(-33,-29,-15,15)])
        self.assertEqual(self.choose()[0],'zone')

    def test_failed_goal_is_not_retried_as_opportunistic_loot(self):
        self.bot.avoid_goals=[self.cube['pos'][:2]]
        self.assertEqual(self.choose()[0],'zone')

    def test_invalid_height_does_not_override_rotation(self):
        self.cube['pos'][2]=10
        self.assertEqual(self.choose()[0],'zone')

    def test_weapon_pickup_can_beat_safe_zone_move(self):
        self.obs['cubes']=[]
        self.obs['pickups']=[dict(kind='laser',id=8000,pos=[-38,0,0])]
        goal,act=self.choose()
        self.assertEqual(goal,'weapon')
        self.assertEqual(act['take'],8000)

    def test_no_interest_at_cube_cap(self):
        self.obs['self']['cubes']=10
        self.assertEqual(self.choose()[0],'zone')

    def test_landed_drop_can_be_taken_instead_of_repositioning(self):
        self.obs['cubes']=[]
        self.obs['drops']=[dict(id=20000,pos=[-35,0,0],radius=8,lands_in=0,holder=None,progress=0,capture_s=4)]
        self.assertEqual(self.choose()[0],'drop')

    def test_nearby_safe_crate_still_fireable(self):
        self.obs['cubes']=[]
        self.obs['self']['aim']=[0,math.atan2(-6,34)]
        self.obs['crates']=[dict(id=1000,pos=[-6,0,0],hp=300)]
        self.assertTrue(self.choose()[1]['fire'][0])
