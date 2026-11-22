"""Exercise guarded farming, swaps, and loss of enemy tracking through act()."""
import copy
import math
import unittest
from unittest.mock import patch

from test_bot import Bot, FIXTURE, enemy, make_world, observation, wall


class ProgressionTests(unittest.TestCase):
    def setUp(self):
        temporary, _ = make_world([wall(-4,4,-25,25)])
        self.addCleanup(temporary.cleanup)
        hello = copy.deepcopy(FIXTURE['hello'])
        hello['map']['dir'] = temporary.name
        self.bot = Bot(hello)
        self.bot.farm_under_cover = True
        self.bot.swap_mortar_for_laser = True
        self.obs = observation()
        self.obs.update(crates=[], cubes=[], pickups=[], drops=[], sounds=[], events=[], mechs=[], projectiles=[], tick=0, t=0)
        self.obs['self'].update(pos=[-40,0,0],aim=[math.pi,math.atan2(-6,16)],hp=1400,in_zone=True)

    def act(self):
        with patch('time.perf_counter',return_value=0):
            return self.bot.act(self.obs)

    def crate(self):
        self.obs['crates']=[dict(id=1000,pos=[-56,0,0],hp=300)]

    def mortar_and_laser(self):
        self.obs['self']['weapons'][1]=dict(kind='mortar',cooldown=0,stats=FIXTURE['hello']['config']['weapons']['mortar'])
        self.obs['pickups']=[dict(id=8000,kind='laser',pos=[-39,0,0])]

    def test_blocked_enemy_does_not_veto_covered_crate(self):
        self.crate()
        self.obs['mechs']=[enemy((50,0,0))]
        action=self.act()
        self.assertTrue(action['fire'][0])
        self.assertEqual(self.bot.goal_kind,'crate')

    def test_enemy_with_a_clear_angle_prevents_cover_farming(self):
        self.crate()
        self.obs['mechs']=[enemy((-36,76,0))]
        self.assertFalse(self.act()['fire'][0])
        self.assertEqual(self.bot.covered_crates,())

    def test_safe_swap_preserves_gun(self):
        self.mortar_and_laser()
        action=self.act()
        self.assertEqual((action['take'],action['drop']),(8000,1))

    def test_nearby_enemy_prevents_swap(self):
        self.mortar_and_laser()
        self.obs['mechs']=[enemy((-50,25,0))]
        self.assertNotIn('drop',self.act())

    def test_lost_threat_is_remembered_but_never_fired_at(self):
        self.obs['mechs']=[enemy((-75,0,0))]
        self.act()
        self.mortar_and_laser()
        self.crate()
        self.obs.update(mechs=[],tick=10,t=.5)
        action=self.act()
        self.assertIn(5,self.bot.enemy_tracks)
        self.assertNotIn('take',action)
        self.assertEqual(action['fire'],[False,False])

    def test_stale_or_defeated_enemy_no_longer_blocks_swap(self):
        self.mortar_and_laser()
        self.bot.enemy_tracks={5:((-50.,0.),-11.),6:((-50.,0.),-.1)}
        self.obs['events']=[dict(type='kill',target=6)]
        self.assertEqual(self.act()['take'],8000)
        self.assertEqual(self.bot.enemy_tracks,{})

    def test_refreshes_each_enemy_position_and_expands_uncertainty_after_loss(self):
        self.obs['mechs'] = [enemy((31, 0, 0)), dict(enemy((-100, -18, 0)), id=6)]
        self.act()
        self.obs.update(mechs=[enemy((50, 0, 0))], tick=10, t=.5)
        self.act()
        self.assertEqual(self.bot.enemy_tracks, {5: ((50, 0), .5), 6: ((-100, -18), 0)})
        self.assertFalse(self.bot.lost_enemy_near([-190, 0], self.obs['mechs'], .5))
        self.assertTrue(self.bot.lost_enemy_near([-190, 0], self.obs['mechs'], 4.5))


if __name__=='__main__':
    unittest.main()
