"""Regression checks for the earlier boost during an active disengagement."""
import copy
import unittest
from unittest.mock import patch

from test_bot import Bot, FIXTURE, enemy, make_world, observation, wall


class DisengageBoostTests(unittest.TestCase):
    def setUp(self):
        temp, _ = make_world([wall(-2, 2, -30, 30)])
        self.addCleanup(temp.cleanup)
        hello = copy.deepcopy(FIXTURE['hello'])
        hello['map']['dir'] = temp.name
        self.bot = Bot(hello)
        self.obs = observation()
        self.obs['t'] = 3
        self.obs['self']['pos'] = [-20, 0, 0]
        self.obs['mechs'] = [enemy((-60, 0, 0)), dict(enemy((-65, 8, 0)), id=6)]
        self.obs['events'] = [dict(type='damaged', weapon='gun', by=5, amount=45, bearing=3.14)]
        self.obs['self']['hp'] = 1100

    def action(self, heading=(1, 0)):
        with patch.object(self.bot.nav, 'direction', return_value=heading):
            return self.bot.act(self.obs)

    def test_healthy_mech_boosts_while_disengaging_under_fire(self):
        action = self.action()
        self.assertEqual(self.bot.goal_kind, 'disengage')
        self.assertFalse(self.bot.recovering)
        self.assertTrue(action['boost'])

    def test_no_recent_hit_does_not_spend_energy(self):
        self.obs['events'] = []
        self.assertFalse(self.action()['boost'])

    def test_old_hit_not_used(self):
        self.bot.last_mech_hit = (self.obs['t'] - 1, 5)
        self.obs['events'] = []
        self.assertFalse(self.action()['boost'])

    def test_npc_damage_does_not_trigger_burst(self):
        self.obs['events'][0].update(weapon='npc', by=100)
        self.assertFalse(self.action()['boost'])

    def test_turning_towards_attacker_does_not_trigger_burst(self):
        self.assertFalse(self.action((-1, 0))['boost'])

    def test_nearby_second_enemy_blocks_retreat_boost_towards_it(self):
        self.obs['mechs'][1]['pos'] = [10, 0, 0]
        self.assertFalse(self.action()['boost'])

    def test_burst_stops_above_v7_reserve(self):
        self.obs['self']['energy'] = 45
        self.assertFalse(self.action()['boost'])

    def test_airborne_retreat_does_not_start_unscheduled_jet(self):
        self.obs['self'].update(grounded=False, pos=[-20, 0, 5])
        self.assertFalse(self.action()['boost'])

    def test_obstacle_blocks_new_boost(self):
        me = self.obs['self']
        me.update(pos=[-9.6, 0, 0], vel=[11.7, 0, 0])
        self.assertFalse(self.bot.ground_boost_clear(me, [1, 0]))

    def test_ordinary_zone_boost_remains_available(self):
        self.obs['self']['in_zone'] = False
        self.obs['events'] = []
        self.assertTrue(self.action()['boost'])


if __name__ == '__main__':
    unittest.main()
