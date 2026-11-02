#!/usr/bin/env python3
"""CBB game-day test model. Prior season score ratings, NOT possession-adjusted or betting-calibrated."""
import argparse, csv, datetime as dt, json, math, time, urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
API='https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard'
ET=ZoneInfo('America/New_York')

def get_day(date):
    qs=urllib.parse.urlencode({'dates':date.strftime('%Y%m%d'),'groups':'50','limit':'500'})
    request=urllib.request.Request(API+'?'+qs,headers={'User-Agent':'Mozilla/5.0 (compatible; SharpHandicapperResearch/1.0)','Accept':'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request,timeout=35) as response: return json.load(response)
        except Exception:
            if attempt==2: raise
            time.sleep(2**attempt)

def event_row(e):
    c=(e.get('competitions') or [{}])[0]; comps=c.get('competitors') or []
    d={x.get('homeAway'):x for x in comps}
    if 'home' not in d or 'away' not in d: return None
    h,a=d['home'],d['away']
    try: kick=dt.datetime.fromisoformat(e['date'].replace('Z','+00:00')).astimezone(ET)
    except (KeyError, ValueError): return None
    row=dict(id=str(e.get('id','')),date=kick.date().isoformat(),tipoff_et=kick.strftime('%I:%M %p ET'),home_id=str(h['team']['id']),away_id=str(a['team']['id']),home=h['team']['displayName'],away=a['team']['displayName'],neutral=bool(c.get('neutralSite',False)),completed=bool(e.get('status',{}).get('type',{}).get('completed',False)))
    if row['completed']:
        try: row.update(home_score=int(h['score']),away_score=int(a['score']))
        except (KeyError, ValueError, TypeError): row['completed']=False
    return row

def fetch_range(start,end):
    seen={};date=start
    while date<=end:
        for e in get_day(date).get('events',[]):
            r=event_row(e)
            if r and r['id']: seen[r['id']]=r
        date+=dt.timedelta(days=1)
        if date<=end:time.sleep(.15)
    return sorted(seen.values(),key=lambda x:(x['date'],x['id']))

def ratings(games):
    finals=[g for g in games if g['completed'] and 'home_score' in g]
    if not finals:return {},0
    mean=sum(g['home_score']+g['away_score'] for g in finals)/(2*len(finals))
    played=defaultdict(list); names={}
    for g in finals:
        h,a=g['home_id'],g['away_id'];names[h]=g['home'];names[a]=g['away']
        played[h].append((g['home_score'],g['away_score'],a,0 if g['neutral'] else 1))
        played[a].append((g['away_score'],g['home_score'],h,0 if g['neutral'] else -1))
    off={k:0. for k in played};deff={k:0. for k in played}
    # Opponent-aware score adjustments, shrink 8 equivalent games; early-season games aren't used to fit these.
    for _ in range(14):
        newoff={};newdef={}
        for t, rec in played.items():
            n=len(rec); w=n/(n+8)
            newoff[t]=w*sum(sc-mean+deff[opp]-1.2*loc for sc,allowed,opp,loc in rec)/n
            newdef[t]=w*sum(allowed-mean-off[opp]+1.2*loc for sc,allowed,opp,loc in rec)/n
        off={t:.5*off[t]+.5*newoff[t] for t in played}
        deff={t:.5*deff[t]+.5*newdef[t] for t in played}
    return {t:dict(name=names[t],games=len(played[t]),off=round(off[t],4),defense_allowed=round(deff[t],4),mean=round(mean,4)) for t in played},len(finals)

def main():
    p=argparse.ArgumentParser();p.add_argument('--prior-start',default='2025-11-03');p.add_argument('--prior-end',default='2026-04-06');p.add_argument('--day',default=dt.datetime.now(ET).date().isoformat());p.add_argument('--out',default='generated/cbb_gameday');p.add_argument('--cache',default='data/cbb_2025_26_prior_games.json');p.add_argument('--refresh-prior',action='store_true');a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    date=dt.date.fromisoformat(a.day);cache=Path(a.cache)
    if cache.exists() and not a.refresh_prior: old=json.loads(cache.read_text()); source='cached_prior_season'
    else:
        old=fetch_range(dt.date.fromisoformat(a.prior_start),dt.date.fromisoformat(a.prior_end));source='fresh_prior_season'
        cache.parent.mkdir(parents=True,exist_ok=True);cache.write_text(json.dumps(old,separators=(',',':'))+'\n')
    prior, prior_games=ratings(old)
    todays=[r for r in fetch_range(date,date) if r['date']==a.day]
    results=[]; blocked=0
    for g in todays:
        h=prior.get(g['home_id']);aw=prior.get(g['away_id'])
        x={k:v for k,v in g.items() if k not in ('home_score','away_score')}
        x['projection_available']=bool(h and aw and h['games']>=5 and aw['games']>=5 and prior_games>=600)
        if x['projection_available']:
            advantage=0 if g['neutral'] else 1.5
            hs=h['mean']+h['off']+aw['defense_allowed']+advantage
            ass=aw['mean']+aw['off']+h['defense_allowed']-advantage
            x.update(pred_home=round(hs,1),pred_away=round(ass,1),home_margin=round(hs-ass,1),total=round(hs+ass,1),home_prior_games=h['games'],away_prior_games=aw['games'])
        else:
            blocked+=1
            x['reason']='Insufficient prior-season coverage (>=600 total finals and >=5 games per side required)'
        results.append(x)
    payload={'phase':'CBB Game-Day 1.0 test','day':a.day,'prior_source':source,'prior_final_games':prior_games,'prior_teams':len(prior),'matchups':len(todays),'projections_available':len(todays)-blocked,'projections_blocked':blocked,'rating_method':'prior-season opponent-aware points-per-game residuals; NOT possession-based or betting-calibrated','limitations':['Roster continuity unknown; early-season team strength may differ materially','Unofficial ESPN data and D-I membership not independently verified','No calibrated first-half model, injury or odds integration','Model output is experimental, not evidence of betting value'],'games':results}
    (out/'cbb_gameday.json').write_text(json.dumps(payload,indent=2)+'\n')
    (out/'cbb_gameday_report.json').write_text(json.dumps({k:v for k,v in payload.items() if k!='games'},indent=2)+'\n')
    print(json.dumps({k:v for k,v in payload.items() if k!='games'},indent=2))
if __name__=='__main__':main()
