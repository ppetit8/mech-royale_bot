"""Before/after goal diagnostics on controlled observations, not match scores."""
import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_bot import FIXTURE, enemy, make_world, observation, wall
from test_strategy import drop


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path/'bot.py')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module.Bot


def run(baseline):
    classes={'V5':load(baseline,'control_runtime'),'V6':load(ROOT,'candidate_runtime')}
    results=[]
    scenarios=(('safe_repair_drop','drop'),('own_capture_progress','drop'),
               ('foreign_capture_clock','avoid_drop'),('enclosed_drop','avoid_drop'),
               ('loot_behind_safe_cover','cube'),('tiny_loot_noise','retain'),
               ('contestable_repair_drop','avoid_drop'),('zone_emergency','zone'))
    for name,expected in scenarios:
        geometry=[]
        if name=='enclosed_drop': geometry=[wall(-20,20,-20,20,holes=[[-12,-12,12,-12,12,12,-12,12]])]
        if name=='loot_behind_safe_cover': geometry=[wall(0,4,-79,79)]
        temp,_=make_world(geometry)
        with temp:
            row=dict(scenario=name,expected=expected,observed={})
            for label,cls in classes.items():
                hello=copy.deepcopy(FIXTURE['hello']);hello['map']['dir']=temp.name
                bot=cls(hello);obs=observation();obs['drops']=[];obs['mechs']=[]
                if name in ('safe_repair_drop','own_capture_progress','contestable_repair_drop','zone_emergency'):
                    obs['self']['hp']=500;bot.recovering=True;bot.last_damage=obs['t']
                if name=='safe_repair_drop': obs['drops']=[drop()]
                if name=='own_capture_progress':
                    obs['drops']=[drop(pos=(-40,0,0),holder=3,progress=3.8)];obs['mechs']=[enemy((30,0,0))]
                if name=='foreign_capture_clock': obs['drops']=[drop(holder=5,progress=3.9)]
                if name=='enclosed_drop': obs['drops']=[drop(pos=(0,0,0))]
                if name=='contestable_repair_drop': obs['drops']=[drop()];obs['mechs']=[enemy((50,0,0))]
                if name=='loot_behind_safe_cover':
                    bot.loot[5000]=(dict(id=5000,pos=[-50,0,0]),0,'cube')
                    obs['mechs']=[enemy((70,0,0)),enemy((65,20,0))]
                if name=='tiny_loot_noise':
                    for ident,y in ((5000,1),(5001,-1)):
                        bot.loot[ident]=(dict(id=ident,pos=[-20,y,0]),0,'cube')
                urgent=name=='zone_emergency'
                if urgent:
                    obs['self']['in_zone']=False
                    obs['zone'].update(center=[30,0],radius=30,next_center=[30,0],next_radius=20)
                with patch('time.perf_counter',return_value=0):
                    goal=bot.strategic_goal(obs,obs['mechs'],urgent);bot.goal=goal
                    if name=='tiny_loot_noise':
                        initial=goal[:]
                        other=5001 if initial[1]>0 else 5000
                        bot.loot[other][0]['pos'][0]-=.5;obs['t']+=.5
                        goal=bot.strategic_goal(obs,obs['mechs'],False)
                        observed='retain' if goal==initial else 'switch'
                    else: observed=bot.goal_kind
                passed=(observed!='drop') if expected=='avoid_drop' else observed==expected
                row['observed'][label]=dict(choice=observed,goal=goal,expected_behavior=passed)
            results.append(row)
    return dict(note='Hand-selected regression diagnostics; not a win rate, placement score, or unbiased strategy evaluation.',scenarios=results)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline',type=Path,default=ROOT.parent/'bot-v5-control')
    ap.add_argument('--output',type=Path)
    args=ap.parse_args();result=run(args.baseline)
    print(json.dumps(result,indent=2))
    if args.output: args.output.write_text(json.dumps(result,indent=2)+'\n')
    raise SystemExit(not all(row['observed']['V6']['expected_behavior'] for row in result['scenarios']))
