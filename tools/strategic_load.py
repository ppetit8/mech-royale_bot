"""Force strategic evaluation on every frame, with landed drops and heavy loot.

This measures decision cost and action validity, not combat or match outcomes.
"""
import argparse
import copy
import gzip
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot import Bot
from benchmark import summary


def run(kit, frames=300):
    with gzip.open(kit/'check/stream.jsonl.gz', 'rt') as stream:
        messages = [json.loads(line) for line in stream]
    hello = messages[0]; hello['map']['dir'] = str((kit/'arena').resolve())
    sample = next(m for m in messages if m['type'] == 'obs')
    bot = Bot(hello); p = sample['self']['pos']; x,y,z = p
    spec = importlib.util.spec_from_file_location('checker',kit/'check/check.py')
    checker = importlib.util.module_from_spec(spec); spec.loader.exec_module(checker)
    schema = checker.Schema(kit/'mechfight.schema.json')
    times=[]; errors=[]; repair_checks=[]; repair_ms=[]; modes={}
    retreat_checks=[]; retreat_ms=[]
    original=bot.repair_drop_goal
    def measured_repair(*args):
        begin=time.perf_counter();result=original(*args)
        repair_ms.append((time.perf_counter()-begin)*1000);repair_checks.append(result is not None)
        return result
    bot.repair_drop_goal=measured_repair
    retreat=bot.disengage_boost
    def measured_retreat(*args):
        begin=time.perf_counter()
        result=retreat(*args)
        retreat_ms.append((time.perf_counter()-begin)*1000)
        retreat_checks.append(result)
        return result
    bot.disengage_boost=measured_retreat
    for frame in range(frames):
        obs=copy.deepcopy(sample); obs['tick']=frame*10; obs['t']=frame*.1
        obs['self']['hp']=500 if frame%60<30 else 1400
        obs['self']['energy']=20 if frame%50<10 else 100
        for key, count, start_id in (('cubes',192,5000),('pickups',40,8000),('crates',36,1000)):
            obs[key]=[]
            for i in range(count):
                a=i*2.399963229728653; d=6+(i%27)*4
                q=[x+d*math.cos(a),y+d*math.sin(a)]; q.append(bot.world.ground(*q))
                obj=dict(id=start_id+i,pos=q)
                if key=='pickups': obj['kind']=('laser','mortar','lightning')[i%3]
                if key=='crates': obj['hp']=300
                obs[key].append(obj)
        obs['drops']=[]
        for i in range(3):
            q=[x+20+i*25,y+10];q.append(bot.world.ground(*q))
            obs['drops'].append(dict(id=20000+i,pos=q,radius=8,lands_in=i*5,capture_s=4,progress=0,holder=None))
        obs['mechs']=[]; obs['projectiles']=[]; obs['events']=[]
        if frame%60<40:
            for i in range(15):
                a=i*math.tau/15;d=35+i*5
                q=[x+d*math.cos(a),y+d*math.sin(a)];q.append(bot.world.ground(*q))
                obs['mechs'].append(dict(id=(i+4)%16,kind='mech',pos=q,vel=[3,-2,0],aim=[a+math.pi,0],weapons=['gun','laser'],charging=i%3==0,hp=1000,max_hp=1400,cubes=i%5))
            for i in range(40):
                a=i*math.tau/40
                obs['projectiles'].append(dict(id=i,kind='gun',pos=[x+30*math.cos(a),y+30*math.sin(a),z+4],vel=[-150*math.cos(a),-150*math.sin(a),0]))
            if frame%60>=30:
                obs['events']=[dict(type='damaged',weapon='gun',amount=45,by=4,bearing=0)]
        if frame%50>=40:
            obs['self']['in_zone']=False
            obs['zone'].update(center=[x+50,y],radius=30,next_center=[x+50,y],next_radius=25,shrink_start=0,shrink_end=100)
        start=time.perf_counter();action=bot.act(obs);times.append((time.perf_counter()-start)*1000)
        errors.extend(schema.errors(action,'Action'));json.dumps(action,allow_nan=False)
        
        modes[bot.goal_kind]=modes.get(bot.goal_kind,0)+1
    return dict(timing=summary(times),schema_errors=errors[:20],repair_override_calls=len(repair_checks),repair_override_selected=sum(repair_checks),
                repair_override_timing=summary(repair_ms),goal_kinds=modes,
                retreat_checks=len(retreat_checks),retreat_boosts=sum(retreat_checks),
                retreat_check_timing=summary(retreat_ms) if retreat_ms else None,
                workload=dict(cubes=192,pickups=40,crates=36,drops=3,max_enemies=15,max_projectiles=40,
                              strategy_runs_every_frame=True))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kit',type=Path,default=ROOT.parent/'mechfight-kit')
    ap.add_argument('--output',type=Path)
    args=ap.parse_args();result=run(args.kit)
    print(json.dumps(result,indent=2))
    if args.output: args.output.write_text(json.dumps(result,indent=2)+'\n')
    raise SystemExit(bool(result['schema_errors'] or result['timing']['over_50_ms'] or not result['retreat_checks']))
