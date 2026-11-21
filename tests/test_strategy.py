"""Goal-selection regressions on controlled maps, not simulated match scores."""
import copy
import math
import unittest
from unittest.mock import patch

from test_bot import Bot, FIXTURE, enemy, make_world, observation, wall


def drop(pos=(-25, 0, 0), **changes):
    value = dict(id=20000, pos=list(pos), radius=8, lands_in=0,
                 capture_s=4, progress=0, holder=None)
    value.update(changes)
    return value


class StrategicTests(unittest.TestCase):
    def setUp(self):
        self.temp, self.world = make_world()
        self.addCleanup(self.temp.cleanup)
        self.hello = copy.deepcopy(FIXTURE['hello'])
        self.hello['map']['dir'] = self.temp.name
        self.bot = Bot(self.hello)
        self.obs = observation()
        self.obs['cubes'] = []; self.obs['pickups'] = []; self.obs['crates'] = []
        self.obs['mechs'] = []; self.obs['drops'] = []

    def select(self, bot=None, urgent=False):
        bot = bot or self.bot
        # Policy assertions shouldn't depend on a loaded host's wall clock.
        # Separate real-clock benchmarks exercise the actual budget.
        with patch('time.perf_counter', return_value=0):
            goal = bot.strategic_goal(self.obs, self.obs['mechs'], urgent)
        bot.goal = goal
        return goal

    def hurt(self):
        self.obs['self']['hp'] = 500
        self.bot.recovering = True
        self.bot.last_damage = self.obs['t']

    def cube(self, ident=5000, pos=(-25, 0, 0)):
        item = dict(id=ident, pos=list(pos))
        self.bot.loot[ident] = (item, self.obs['t'], 'cube')

    def test_repair_drop_beats_passive_recovery(self):
        self.hurt(); self.obs['drops'] = [drop()]
        self.assertEqual(self.select(), [-25, 0])
        self.assertEqual(self.bot.goal_kind, 'drop')

    def test_repair_drop_goal_reaches_movement_controller(self):
        self.hurt(); self.obs['drops'] = [drop()]
        with patch('time.perf_counter', return_value=0):
            action = self.bot.act(self.obs)
        self.assertEqual(self.bot.goal_kind, 'drop')
        self.assertGreater(action['move'][0], .8)
        self.assertFalse(any(action['fire']))

    def test_capture_at_center_holds_position(self):
        self.hurt(); self.obs['drops'] = [drop(pos=(-40,0,0),holder=3,progress=2)]
        with patch('time.perf_counter', return_value=0):
            action = self.bot.act(self.obs)
        self.assertEqual(self.bot.goal_kind, 'drop')
        self.assertEqual(action['move'], [0,0])
        self.assertFalse(any(action['fire']))

    def test_possible_enemy_contest_rejects_repair_drop(self):
        self.hurt(); self.obs['drops'] = [drop()]
        self.obs['mechs'] = [enemy((50, 0, 0))]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')
        self.assertIn('drop_contest_or_wait', self.bot.goal_decision['rejected'])

    def test_foreign_holder_is_not_our_capture_progress(self):
        self.hurt(); self.obs['drops'] = [drop(progress=3.9, holder=5)]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')

    def test_possible_upgraded_enemy_speed_counts_for_contest(self):
        self.hurt(); self.obs['drops'] = [drop()]
        self.obs['mechs'] = [enemy((155, 0, 0))]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')
        self.assertIn('drop_contest_or_wait', self.bot.goal_decision['rejected'])

    def test_own_capture_progress_keeps_nearly_complete_drop(self):
        self.hurt(); self.obs['drops'] = [drop(pos=(-40, 0, 0), progress=3.8, holder=3)]
        self.obs['mechs'] = [enemy((30, 0, 0))]
        self.assertEqual(self.select(), [-40, 0])
        self.assertEqual(self.bot.goal_kind, 'drop')

    def test_capture_progress_does_not_override_enemy_in_ring(self):
        self.hurt(); self.obs['drops'] = [drop(pos=(-40, 0, 0), progress=3.9, holder=3)]
        self.obs['mechs'] = [enemy((-34, 0, 0))]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')

    def test_old_capture_progress_ignored_outside_ring(self):
        self.hurt(); self.obs['drops'] = [drop(progress=3.9, holder=3)]
        self.obs['mechs'] = [enemy((80, 0, 0))]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')

    def test_distant_future_drop_does_not_reserve_bot(self):
        self.hurt(); self.obs['drops'] = [drop(lands_in=24)]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')

    def test_drop_that_zone_will_swallow_is_rejected(self):
        self.hurt(); self.obs['drops'] = [drop(pos=(60, 0, 0))]
        self.obs['zone'].update(next_center=[-40, 0], next_radius=30,
                                shrink_start=0, shrink_end=30)
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')
        self.assertTrue({'rotation_slack', 'zone_at_completion'} & self.bot.goal_decision['rejected'].keys())

    def test_optional_enclosed_courtyard_is_rejected(self):
        temp, world = make_world([wall(-20,20,-20,20,holes=[[-12,-12,12,-12,12,12,-12,12]])])
        self.addCleanup(temp.cleanup)
        self.hello['map']['dir'] = temp.name
        self.bot = Bot(self.hello); self.hurt()
        self.obs['drops'] = [drop(pos=(0, 0, 0))]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')
        self.assertIn('disconnected', self.bot.goal_decision['rejected'])

    def test_drop_behind_wall_needs_verified_route(self):
        temp, _ = make_world([wall()]); self.addCleanup(temp.cleanup)
        self.hello['map']['dir'] = temp.name
        self.bot = Bot(self.hello); self.hurt()
        self.obs['drops'] = [drop(pos=(30, 0, 0))]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')
        self.assertIn('unverified_route', self.bot.goal_decision['rejected'])

    def test_roof_drop_is_not_treated_as_ground_drop(self):
        self.hurt(); self.obs['drops'] = [drop(pos=(-25, 0, 15))]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'drop')

    def test_small_loot_score_change_does_not_flip_goal(self):
        self.cube(5000, (-20, 1, 0)); self.cube(5001, (-20, -1, 0))
        self.select(); selected = self.bot.goal_key
        other = 5000 if selected == ('cube', 5001) else 5001
        self.bot.loot[other][0]['pos'][0] -= .5
        self.obs['t'] += .5
        self.select()
        self.assertEqual(self.bot.goal_key, selected)

    def test_large_improvement_overrides_commitment(self):
        self.cube(5000, (-10, 0, 0)); self.select()
        self.assertEqual(self.bot.goal_kind, 'cube')
        self.hurt(); self.obs['drops'] = [drop()]
        self.select()
        self.assertEqual(self.bot.goal_kind, 'drop')

    def test_new_threat_can_break_loot_commitment(self):
        self.cube(); self.select(); self.assertEqual(self.bot.goal_kind, 'cube')
        self.obs['mechs'] = [enemy((-25, 0, 0))]
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'cube')

    def test_close_pursuer_prompts_retreat_goal(self):
        self.hurt(); self.obs['mechs'] = [enemy((-25,0,0))]
        goal = self.select()
        self.assertGreater(math.dist(goal, [-25,0]), 30)

    def test_low_energy_reduces_optional_detours(self):
        self.cube(pos=(40, 0, 0)); self.select()
        self.assertEqual(self.bot.goal_kind, 'cube')
        self.bot.goal = None; self.bot.goal_key = None
        self.obs['self']['energy'] = 0
        self.select()
        self.assertEqual(self.bot.goal_kind, 'hold')

    def test_exhausted_budget_keeps_valid_baseline(self):
        self.hurt(); self.obs['drops'] = [drop()]
        with patch('time.perf_counter', side_effect=[0, 1]):
            goal = self.bot.strategic_goal(self.obs, [], False)
        self.assertEqual(goal, self.obs['self']['pos'][:2])
        self.assertTrue(self.bot.goal_decision['budget_exhausted'])
        self.assertEqual(self.bot.goal_decision['checked'], 1)

    def test_zone_emergency_overrides_repair_commitment(self):
        self.hurt(); self.obs['drops'] = [drop()]; self.select()
        self.obs['self']['in_zone'] = False
        self.obs['zone'].update(center=[30,0], radius=30, next_center=[30,0], next_radius=20)
        goal = self.select(urgent=True)
        self.assertEqual(self.bot.goal_kind, 'zone')
        self.assertLess(math.dist(goal, [30, 0]), 20)

    def test_gone_drop_invalidates_commitment(self):
        self.hurt(); self.obs['drops'] = [drop()]; self.select()
        self.obs['drops'] = []; self.obs['t'] += .5
        self.select()
        self.assertEqual(self.bot.goal_kind, 'recover')

    def test_expired_loot_invalidates_commitment(self):
        self.cube(); self.select(); self.assertEqual(self.bot.goal_kind, 'cube')
        self.obs['t'] += 19
        self.select()
        self.assertNotEqual(self.bot.goal_kind, 'cube')

    def test_safe_exploration_has_stable_heading(self):
        first = self.select(); key = self.bot.goal_key
        self.assertEqual(self.bot.goal_kind, 'explore')
        for _ in range(5):
            self.obs['t'] += .5
            self.assertEqual(self.select(), first)
            self.assertEqual(self.bot.goal_key, key)

    def test_known_safe_loot_not_blocked_by_distant_covered_tracks(self):
        temp, _ = make_world([wall(0, 4, -79, 79)]); self.addCleanup(temp.cleanup)
        self.hello['map']['dir'] = temp.name; self.bot = Bot(self.hello)
        self.cube(pos=(-50, 0, 0))
        self.obs['mechs'] = [enemy((70, 0, 0)), enemy((65, 20, 0))]
        self.select()
        self.assertEqual(self.bot.goal_kind, 'cube')

    def test_recovery_can_choose_reachable_cover(self):
        temp, world = make_world([wall(-20,-10,5,25)]); self.addCleanup(temp.cleanup)
        self.hello['map']['dir'] = temp.name; self.bot = Bot(self.hello)
        self.hurt(); self.obs['mechs'] = [enemy((30, -10, 0))]
        goal = self.select()
        self.assertEqual(self.bot.goal_kind, 'recover')
        self.assertGreater(math.dist(goal, self.obs['self']['pos'][:2]), 5)
        self.assertTrue(world.walk_clear(self.obs['self']['pos'], [*goal, 0], 2.5, 9))
        self.assertFalse(world.shot_clear([30,-10,7], [*goal, 4.95]))


if __name__ == '__main__':
    unittest.main()
