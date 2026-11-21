"""Closed-loop ground-route probe, NOT an authoritative game simulator.

Uses the bot's collision geometry, acceleration and a flat foot support model.
Useful for detecting stuck routes; cannot establish placement or combat strength.
"""
import argparse
import copy
import json
import math
import random
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot import Bot
from combat import unit
from world import Navigator


def rollout(bot, start, goal, planned, critical=False):
    w=bot.world; o=copy.deepcopy(json.loads((ROOT/'tests/fixtures.json').read_text())['obs'])
    me=o['self']; me['pos']=[*start,w.ground(*start)];me['vel']=[0,0,0]
    o['zone'].update(center=[0,0],radius=2000,next_center=[0,0],next_radius=2000)
    bot.nav=Navigator(w);bot.last_move=[0,0]
    distance=0.;blocked=0;timings=[];stationary=0
    for step in range(1800):
        o['t']=step*.1;o['tick']=step*2
        t=time.perf_counter()
        desired=bot.nav.direction(me,goal,t+.006,now=step*.1,critical=critical) if planned else [goal[i]-me['pos'][i] for i in range(2)]
        move=bot.movement(o,desired,[],False,t+.016) if planned else unit(desired)
        timings.append((time.perf_counter()-t)*1000)
        old=me['pos'][:];velocity=me['vel'][:]
        for i in range(2):
            velocity[i]+=max(-me['stats']['ground_accel']*.1,min(me['stats']['ground_accel']*.1,move[i]*me['stats']['walk_speed']-velocity[i]))
        q=[old[i]+velocity[i]*.1 for i in range(2)];q.append(w.ground(*q))
        if w.walk_clear(old,q,me['stats']['radius'],me['stats']['height']):
            me['pos']=q;me['vel']=velocity;distance+=math.dist(old[:2],q[:2])
        else:
            blocked+=1;me['vel']=[0,0,0]
            if planned and blocked%10==0:
                bot.nav.path=[];bot.nav.search=None
        bot.last_move=move
        stationary = stationary + 1 if math.dist(old[:2],me['pos'][:2]) < .05 else 0
        if planned and not critical and bot.nav.failed_goal is not None and stationary > 20:
            return dict(reached=False,remaining_m=round(math.dist(me['pos'][:2],goal),1),
                        path_m=round(distance,1),blocked_steps=blocked,max_ms=round(max(timings),2),
                        reason='No route found in bounded ground grid; stopped this objective.')
        if math.dist(me['pos'][:2],goal)<5:
            return dict(reached=True,seconds=round((step+1)*.1,1),path_m=round(distance,1),blocked_steps=blocked,max_ms=round(max(timings),2))
    return dict(reached=False,remaining_m=round(math.dist(me['pos'][:2],goal),1),path_m=round(distance,1),blocked_steps=blocked,max_ms=round(max(timings),2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kit',type=Path,default=ROOT.parent/'mechfight-kit')
    ap.add_argument('--routes',type=int,default=12)
    ap.add_argument('--output',type=Path)
    ap.add_argument('--critical',action='store_true',help='Exercise mandatory zone/recovery route fallback.')
    args=ap.parse_args()
    hello=json.loads((ROOT/'tests/fixtures.json').read_text())['hello']
    hello['map']['dir']=str((args.kit/'arena').resolve());b=Bot(hello);w=b.world;rng=random.Random(713)
    free=[n for n in range(len(w.clearance)) if w.clearance[n]>6]
    routes=[]
    while len(routes)<args.routes:
        a,c=rng.sample(free,2);start,goal=w.xy(a),w.xy(c)
        if not 100<math.dist(start,goal)<350:
            continue
        baseline=rollout(b,start,goal,False);planned=rollout(b,start,goal,True,args.critical)
        row=dict(start=list(start),goal=list(goal),straight_line=baseline,aegis=planned)
        routes.append(row)
        print(json.dumps(row),flush=True)
    result=dict(model='Ground navigation probe using our collision model; no authoritative server physics.',seed=713,
                routes=len(routes),critical=args.critical,straight_line_completed=sum(r['straight_line']['reached'] for r in routes),
                aegis_completed=sum(r['aegis']['reached'] for r in routes),results=routes)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))
