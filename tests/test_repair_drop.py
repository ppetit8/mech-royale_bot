"""Recovery-drop exception and preserved V5 movement/route behaviors."""
import copy
import math
import unittest
from unittest.mock import patch

from test_bot import Bot, FIXTURE, enemy, make_world, observation, wall


def drop(pos=(-25,0,0), **changes):
    value=dict(id=20000,pos=list(pos),radius=8,lands_in=0,capture_s=4,progress=0,holder=None)
    value.update(changes)
    return value


class RepairDropTests(unittest.TestCase):
    def setUp(self):
        self.temp,self.world=make_world();self.addCleanup(self.temp.cleanup)
        self.hello=copy.deepcopy(FIXTURE['hello']);self.hello['map']['dir']=self.temp.name
        self.bot=Bot(self.hello);self.obs=observation()
        for key in ('mechs','projectiles','drops','crates','cubes','pickups','events','sounds'):
            self.obs[key]=[]
        self.obs['self']['hp']=500;self.bot.recovering=True;self.bot.last_damage=self.obs['t']

    def repair(self):
        with patch('time.perf_counter',return_value=0):
            return self.bot.repair_drop_goal(self.obs,self.obs['mechs'])

    def goal(self,urgent=False):
        with patch('time.perf_counter',return_value=0):
            self.bot.goal=self.bot.strategic_goal(self.obs,self.obs['mechs'],urgent)
        return self.bot.goal

    def geometry(self,prisms):
        temp,w=make_world(prisms);self.addCleanup(temp.cleanup)
        self.hello['map']['dir']=temp.name;self.bot=Bot(self.hello)
        self.bot.recovering=True;self.bot.last_damage=self.obs['t']
        return w

    def test_safe_landed_drop_beats_passive_recovery(self):
        self.obs['drops']=[drop()]
        self.assertEqual(self.goal(),[-25,0]);self.assertEqual(self.bot.goal_kind,'drop')

    def test_drop_goal_drives_actual_controller(self):
        self.obs['drops']=[drop()]
        with patch('time.perf_counter',return_value=0):action=self.bot.act(self.obs)
        self.assertEqual(self.bot.goal_kind,'drop')
        self.assertGreater(action['move'][0],.8)
        self.assertFalse(any(action['fire']))

    def test_capture_at_center_holds_position_without_firing(self):
        self.obs['drops']=[drop(pos=(-40,0,0),holder=3,progress=2)]
        with patch('time.perf_counter',return_value=0):action=self.bot.act(self.obs)
        self.assertEqual(self.bot.goal_kind,'drop');self.assertEqual(action['move'],[0,0])
        self.assertFalse(any(action['fire']))

    def test_safe_nearly_complete_capture_keeps_own_progress(self):
        self.obs['drops']=[drop(pos=(-40,0,0),holder=3,progress=3.8)]
        self.assertEqual(self.repair(),[-40,0])

    def test_enemy_in_ring_blocks_nearly_complete_capture(self):
        self.obs['drops']=[drop(pos=(-40,0,0),holder=3,progress=3.8)]
        self.obs['mechs']=[enemy((-34,0,0))]
        self.assertIsNone(self.repair())

    def test_other_mechs_capture_clock_is_not_ours(self):
        self.obs['drops']=[drop(holder=5,progress=3.9)]
        self.assertIsNone(self.repair())

    def test_progress_outside_ring_is_not_banked(self):
        self.obs['drops']=[drop(holder=3,progress=3.9)]
        self.obs['self']['hp']=1120
        # Full heal can complete in 6.22 s if regen is already active; a new
        # capture takes >5.6 s plus the 1 s required advantage, so it loses.
        self.bot.last_damage=-100
        self.assertIsNone(self.repair())

    def test_unlanded_drop_does_not_interrupt_recovery(self):
        self.obs['drops']=[drop(lands_in=.1)]
        self.assertIsNone(self.repair());self.goal();self.assertEqual(self.bot.goal_kind,'recover')

    def test_far_drop_does_not_trigger_new_exception(self):
        self.obs['drops']=[drop(pos=(30,0,0))]
        self.assertIsNone(self.repair())

    def test_passive_regen_can_beat_capture(self):
        self.obs['self']['hp']=1250;self.bot.last_damage=-100
        self.obs['drops']=[drop()]
        self.assertIsNone(self.repair())

    def test_upgraded_regen_changes_time_comparison(self):
        self.obs['self']['stats'].update(regen_delay=0,regen_per_s=300)
        self.obs['drops']=[drop()]
        self.assertIsNone(self.repair())

    def test_enemy_that_can_arrive_in_time_rejects_capture(self):
        self.obs['drops']=[drop()];self.obs['mechs']=[enemy((50,0,0))]
        self.assertIsNone(self.repair())

    def test_possible_enemy_speed_upgrades_count(self):
        self.obs['drops']=[drop()];self.obs['mechs']=[enemy((155,0,0))]
        self.assertIsNone(self.repair())

    def test_exposed_drop_rejected_even_without_capture_race(self):
        self.obs['drops']=[drop()];self.obs['mechs']=[enemy((190,0,0))]
        self.assertIsNone(self.repair())

    def test_covered_distant_enemy_does_not_always_block_repair(self):
        self.geometry([wall(0,4,-79,79)])
        self.obs['self']['pos']=[-70,0,0]
        self.obs['drops']=[drop(pos=(-65,0,0),holder=3,progress=1.5)];self.obs['mechs']=[enemy((78,0,0))]
        self.assertEqual(self.repair(),[-65,0])

    def test_endpoint_cover_cannot_hide_exposed_approach(self):
        self.geometry([wall(-20,-10,5,25)])
        self.obs['drops']=[drop(pos=(-24.5,9.5,0))]
        self.obs['mechs']=[enemy((190,-10,0))]
        self.assertIsNone(self.repair())

    def test_roof_drop_rejected(self):
        self.obs['drops']=[drop(pos=(-25,0,15))]
        self.assertIsNone(self.repair())

    def test_airborne_mech_retains_baseline_recovery(self):
        self.obs['self'].update(grounded=False,pos=[-40,0,5]);self.obs['drops']=[drop()]
        self.assertIsNone(self.repair())

    def test_direct_route_to_repair_must_be_clear(self):
        self.geometry([wall()]);self.obs['self']['pos']=[-20,0,0]
        self.obs['drops']=[drop(pos=(20,0,0))]
        self.assertIsNone(self.repair())

    def test_enclosed_repair_drop_rejected(self):
        self.geometry([wall(-20,20,-20,20,holes=[[-12,-12,12,-12,12,12,-12,12]])])
        self.obs['drops']=[drop(pos=(0,0,0))]
        self.assertIsNone(self.repair())

    def test_failed_repair_route_is_not_reselected(self):
        self.obs['drops']=[drop()];self.bot.avoid_goals=[[-25,0]]
        self.assertIsNone(self.repair())

    def test_drop_outside_forecast_zone_rejected(self):
        self.obs['drops']=[drop(pos=(10,0,0))]
        self.obs['zone'].update(next_center=[-40,0],next_radius=20,shrink_start=0,shrink_end=20)
        self.assertIsNone(self.repair())

    def test_capture_must_leave_time_for_next_rotation(self):
        self.obs['drops']=[drop(pos=(15,0,0))]
        self.obs['zone'].update(next_center=[-60,0],next_radius=30,shrink_start=0,shrink_end=26)
        self.assertIsNone(self.repair())

    def test_zone_emergency_keeps_v5_priority(self):
        self.obs['drops']=[drop()];self.obs['self']['in_zone']=False
        self.obs['zone'].update(center=[30,0],radius=30,next_center=[30,0],next_radius=20)
        self.goal(urgent=True);self.assertEqual(self.bot.goal_kind,'zone')

    def test_repair_disappears_then_baseline_recovery_resumes(self):
        self.obs['drops']=[drop()];self.goal();self.assertEqual(self.bot.goal_kind,'drop')
        self.obs['drops']=[];self.obs['t']+=.5
        self.goal();self.assertEqual(self.bot.goal_kind,'recover')

    def test_expired_optional_budget_returns_to_v5(self):
        self.obs['drops']=[drop()]
        with patch('time.perf_counter',side_effect=[0,1]):
            self.assertIsNone(self.bot.repair_drop_goal(self.obs,[]))

    def test_healthy_bot_does_not_enter_repair_exception(self):
        self.bot.recovering=False;self.obs['self']['hp']=1400;self.obs['drops']=[drop()]
        with patch.object(self.bot,'repair_drop_goal',side_effect=AssertionError('unexpected repair override')):
            self.goal()

    def test_energy_recovery_does_not_lock_exploration(self):
        self.bot.recovering=False;self.obs['self']['hp']=1400
        self.bot.goal=self.obs['self']['pos'][:2];self.bot.goal_kind='hold';self.bot.goal_until=4
        self.obs['self']['energy']=0;self.goal()
        self.obs['self']['energy']=100;self.obs['t']=5
        goal=self.goal()
        self.assertEqual(self.bot.goal_kind,'explore')
        self.assertGreater(math.dist(goal,self.obs['self']['pos'][:2]),20)
        with patch('time.perf_counter',return_value=0):
            action=self.bot.act(self.obs)
        self.assertGreater(math.hypot(*action['move']),.5)

    def test_baseline_loot_detour_around_wall_is_preserved(self):
        self.geometry([wall()]);self.bot.recovering=False;self.obs['self']['hp']=1400
        self.bot.loot[5000]=(dict(id=5000,pos=[30,0,0]),0,'cube')
        self.assertEqual(self.goal(),[30,0]);self.assertEqual(self.bot.goal_kind,'cube')


if __name__=='__main__':
    unittest.main()
