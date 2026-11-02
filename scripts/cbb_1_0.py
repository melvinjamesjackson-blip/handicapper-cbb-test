#!/usr/bin/env python3
"""College Basketball 1.0 PROTOTYPE, test-only.
Fetch ESPN final D-I men's basketball games, construct opponent-adjusted SCORE ratings,
project matchup full game. 1H estimates intentionally omitted until calibrated.
This is not possession efficiency or betting-value modeling.
"""
import argparse,csv,datetime,json,math,time,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
URL='https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard'
HEADERS=['date','game_id','away','away_name','home','home_name','away_score','home_score','neutral']

def fetch_day(day):
 q=urllib.parse.urlencode({'dates':day.strftime('%Y%m%d'),'groups':'50','limit':500})
 req=urllib.request.Request(URL+'?'+q,headers={'User-Agent':'SharpHandicapper-Research/1.0'})
 for attempt in range(3):
  try:
   with urllib.request.urlopen(req,timeout=30) as f:return json.load(f)
  except Exception:
   if attempt==2:raise
   time.sleep(2**attempt)

def parse_event(event):
 if not event.get('status',{}).get('type',{}).get('completed'):return None
 c=event.get('competitions',[{}])[0]; sides=c.get('competitors',[])
 if len(sides)!=2:return None
 by={r.get('homeAway'):r for r in sides}
 if set(by)!={'home','away'}:return None
 h,a=by['home'],by['away']
 if not (h.get('score') and a.get('score')):return None
 ts=event.get('date','')
 date=datetime.datetime.fromisoformat(ts.replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
 return dict(date=date,game_id=str(event['id']),away=str(a['team']['id']),away_name=a['team']['displayName'],home=str(h['team']['id']),home_name=h['team']['displayName'],away_score=int(a['score']),home_score=int(h['score']),neutral=int(bool(c.get('neutralSite',False))))

def get_games(start,end):
 byid={};day=start
 while day<=end:
  data=fetch_day(day)
  for e in data.get('events',[]):
   g=parse_event(e)
   if g:byid[g['game_id']]=g
  day+=datetime.timedelta(days=1)
  if day<=end:time.sleep(1.1)
 rows=sorted(byid.values(),key=lambda x:(x['date'],x['game_id']))
 for r in rows:
  if r['away']==r['home']:raise ValueError('Same team on both sides')
 seen=set()
 for r in rows:
  for t in (r['away'],r['home']):
   k=(r['date'],t)
   if k in seen:raise ValueError(f'Duplicate team/date {k} - investigate source before modeling')
   seen.add(k)
 return rows

def ratings(games):
 # Lightweight opponent-adjusted score-rating system, least-squares ridge iteration.
 # Score prediction = league mean + team O - opponent D + home advantage.
 # Not adjusted per possession: this is a transparent preliminary prototype.
 teams={};sums=defaultdict(lambda:[0.,0.,0])
 for g in games:
  teams[g['home']]=g['home_name'];teams[g['away']]=g['away_name']
  for team,p,allowed in ((g['home'],g['home_score'],g['away_score']),(g['away'],g['away_score'],g['home_score'])):
   sums[team][0]+=p;sums[team][1]+=allowed;sums[team][2]+=1
 if not games:return [],{}
 league=sum(g['home_score']+g['away_score'] for g in games)/(2*len(games))
 off={t:0. for t in teams};deff={t:0. for t in teams}
 played=defaultdict(list)
 for g in games:
  played[g['home']].append((g['home_score'],g['away'],1 if not g['neutral'] else 0))
  played[g['away']].append((g['away_score'],g['home'],-1 if not g['neutral'] else 0))
 # Shrink ratings toward 0 with 10 effective games, 12 iteration dampening
 for _ in range(12):
  newoff={};newdef={}
  for t in teams:
   n=len(played[t]);weight=n/(n+10)
   att=sum(p-league+deff[o]-1.5*loc for p,o,loc in played[t])/n
   # Defensive score impact = opponent points above baseline
   defending=[]
   for g in games:
    if g['home']==t:defending.append((g['away_score'],g['away'],1 if not g['neutral'] else 0))
    if g['away']==t:defending.append((g['home_score'],g['home'],-1 if not g['neutral'] else 0))
   d=sum(p-league-off[o]-1.5*loc for p,o,loc in defending)/n
   newoff[t]=weight*att;newdef[t]=weight*d
  off={t:0.5*off[t]+0.5*newoff[t] for t in teams}
  deff={t:0.5*deff[t]+0.5*newdef[t] for t in teams}
 out=[]
 for t in sorted(teams):
  out.append({'team_id':t,'team':teams[t],'games':int(sums[t][2]),'offense_points_adjustment':round(off[t],3),'defense_points_allowed_adjustment':round(deff[t],3),'league_points_per_team':round(league,3)})
 return out,{t:(teams[t],off[t],deff[t],sums[t][2]) for t in teams}

def main():
 p=argparse.ArgumentParser();p.add_argument('--start',default='2025-11-03');p.add_argument('--end',default='2026-04-06');p.add_argument('--out',default='generated/cbb_1_0');p.add_argument('--away-id');p.add_argument('--home-id');p.add_argument('--neutral',action='store_true');args=p.parse_args()
 start,end=map(datetime.date.fromisoformat,(args.start,args.end))
 if (end-start).days>230 or end<start:raise SystemExit('Choose a valid range of <=231 days')
 out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
 games=get_games(start,end)
 if not games:raise SystemExit('No final games found; do not emit ungrounded ratings')
 rs,by=ratings(games)
 with (out/'cbb_1_0_games.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=HEADERS);w.writeheader();w.writerows(games)
 with (out/'cbb_1_0_ratings.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
 result={'source':'ESPN unofficial scoreboard JSON; all D-I group=50; final games only','games':len(games),'teams':len(rs),'last_date':max(g['date'] for g in games),'status':'PRELIMINARY_NOT_BETTING_CALIBRATED','limitations':['Ratings are SCORE-based, not possession-adjusted efficiency.','No injuries, rosters, market odds, 1H model or calibrated probabilities.','ESPN API unofficial; coverage requires cross-check before deployment.']}
 if args.home_id or args.away_id:
  if not args.home_id or not args.away_id:raise SystemExit('Supply BOTH --home-id and --away-id')
  h=by[args.home_id];a=by[args.away_id]
  if h[3]<3 or a[3]<3:raise SystemExit('Both teams require >=3 games for preliminary projection')
  adv=0 if args.neutral else 1.5
  avg=sum(g['home_score']+g['away_score'] for g in games)/(2*len(games))
  hs=avg+h[1]+a[2]+adv;ass=avg+a[1]+h[2]-adv
  result['projection']={'home':h[0],'away':a[0],'home_score':round(hs,1),'away_score':round(ass,1),'home_margin':round(hs-ass,1),'total':round(hs+ass,1),'note':'Experimental scores with unvalidated fixed 1.5pt home scoring effect; not a betting recommendation'}
 (out/'cbb_1_0_report.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
