"""Recorded-stream and synthetic-load timings. These are not match scores."""
import argparse
import copy
import gzip
import importlib.util
import json
import math
import resource
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot import Bot


def summary(samples):
    s=sorted(samples)
    return dict(count=len(s),p50_ms=round(statistics.median(s),3),
                p90_ms=round(s[int(.9*(len(s)-1))],3),p99_ms=round(s[int(.99*(len(s)-1))],3),
                max_ms=round(max(s),3),over_50_ms=sum(x>50 for x in s))


def run(kit, repeat):
    with gzip.open(kit/'check/stream.jsonl.gz','rt') as f:
        messages=[json.loads(l) for l in f]
    hello=messages[0];hello['map']['dir']=str((kit/'arena').resolve())
    spec=importlib.util.spec_from_file_location('checker',kit/'check/check.py')
    checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
    schema=checker.Schema(kit/'mechfight.schema.json')
    obs=[m for m in messages if m['type']=='obs']
    t=time.perf_counter();b=Bot(hello);startup=(time.perf_counter()-t)*1000
    times=[];errors=[];actions=[]
    for _ in range(repeat):
        b.goal=None;b.nav.path=[];b.nav.search=None
        for o in obs:
            t=time.perf_counter();a=b.act(o);times.append((time.perf_counter()-t)*1000)
            errors.extend(schema.errors(a,'Action'))
            json.dumps(a,allow_nan=False)
            actions.append(dict(tick=o['tick'],mode=b.mode,action=a))
    # 15 simultaneous enemies and 40 incoming projectiles, cycling zone and recovery.
    stress=[]
    for frame in range(200):
        o=copy.deepcopy(obs[0]);o['t']=frame*.1;o['tick']=frame*2
        x,y,z=o['self']['pos'];o['self']['hp']=600 if frame%40<20 else 1400
        o['self']['weapons'][1]=dict(kind='laser',cooldown=0,charge=(frame%10)*.1,stats=hello['config']['weapons']['laser'])
        for i in range(15):
            angle=i*math.tau/15;d=25+(i%5)*23
            o['mechs'].append(dict(id=(i+4)%16,kind='mech',pos=[x+d*math.cos(angle),y+d*math.sin(angle),z],
                                  vel=[3,-2,0],aim=[angle+math.pi,0],weapons=['gun','laser'],charging=i%3==0,hp=1000,max_hp=1400,cubes=i%5))
        for i in range(40):
            angle=i*math.tau/40
            o['projectiles'].append(dict(id=i,kind='gun',pos=[x+30*math.cos(angle),y+30*math.sin(angle),z+4],
                                        vel=[-150*math.cos(angle),-150*math.sin(angle),0]))
        t=time.perf_counter();a=b.act(o);stress.append((time.perf_counter()-t)*1000)
        errors.extend(schema.errors(a,'Action'));json.dumps(a,allow_nan=False)
    return dict(startup_ms=round(startup,1),replay=summary(times),synthetic_load=summary(stress),
                peak_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),
                schema_errors=errors[:20],astar_expansions=b.nav.expansions),actions


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kit',type=Path,default=ROOT.parent/'mechfight-kit')
    ap.add_argument('--repeat',type=int,default=3)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    result,actions=run(args.kit,args.repeat)
    print(json.dumps(result,indent=2))
    if args.output:
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
        (args.output/'actions.jsonl').write_text(''.join(json.dumps(a)+'\n' for a in actions))
    if result['schema_errors'] or result['replay']['over_50_ms'] or result['synthetic_load']['over_50_ms']:
        sys.exit(1)
