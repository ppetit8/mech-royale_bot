"""Regression tests for the tactical cover route selector."""
import copy
import math
import unittest
from unittest.mock import patch

from test_bot import Bot, FIXTURE, enemy, make_world, observation, wall


class CoverRouteTests(unittest.TestCase):
    def setUp(self):
        temp, self.world = make_world([wall(-33,-28,3.5,30)])
        self.addCleanup(temp.cleanup)
        hello = copy.deepcopy(FIXTURE['hello'])
        hello['map']['dir'] = temp.name
        self.bot = Bot(hello)
        self.obs = observation()
        self.foes = [enemy((-70,30,0))]
        self.obs['mechs'] = self.foes

    def route(self, radius=100):
        with patch('time.perf_counter', return_value=0):
            return self.bot.cover_route(self.obs, self.foes, [0,0], radius)

    def test_route_reaches_cover_around_edge_of_building(self):
        start = self.obs['self']['pos']
        route = self.route()
        self.assertIsNotNone(route)
        self.assertTrue(self.world.shot_clear([-70,30,7],[*start[:2],5]))
        self.assertFalse(self.world.shot_clear([-70,30,7],[*route,5]))
        self.assertTrue(self.world.walk_clear(start,[*route,0],2.5,9))

    def test_refuge_must_be_inside_future_margin(self):
        route = self.route(radius=10)
        if route is not None:
            self.assertLessEqual(math.hypot(*route),10)

    def test_exhausted_budget_yields_baseline_fallback(self):
        with patch('time.perf_counter', side_effect=[0,1]):
            self.assertIsNone(self.bot.cover_route(self.obs,self.foes,[0,0],100))

    def test_opposite_side_threat_keeps_baseline_escape_policy(self):
        self.foes.append(dict(enemy((25,0,0)), id=6))
        self.bot.cover_mode = 'aligned'
        self.assertIsNone(self.route())

    def test_urgent_zone_takes_precedence(self):
        self.bot.recovering = True
        self.obs['self']['in_zone'] = False
        with patch.object(self.bot, 'cover_route', side_effect=AssertionError('zone should override cover')):
            goal = self.bot.strategic_goal(self.obs,self.foes,urgent=True)
        self.assertEqual(self.bot.goal_kind,'zone')
        self.assertEqual(len(goal),2)

    def test_healthy_duel_does_not_use_retreat_planner(self):
        self.bot.last_mech_hit = (self.obs['t'],self.foes[0]['id'])
        with patch.object(self.bot, 'cover_route', side_effect=AssertionError('single foe')):
            self.bot.strategic_goal(self.obs,self.foes,urgent=False)


if __name__ == '__main__':
    unittest.main()
