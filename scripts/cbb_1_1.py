#!/usr/bin/env python3
"""Sharp Handicapper CBB 1.1: TEST-ONLY validated boxscore metrics and rolling opponent adjustment.
ESPN's unofficial API is not guaranteed. Missing boxscores are NEVER silently imputed.
Outputs diagnostics, ratings and raw box-score coverage; no betting edge or calibrated first halves.
"""
import argparse,csv,datetime as dt,json,math,re,time,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
SCOREBOARD='https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard'
SUMMARY='https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary'
HEAD=['date','game_id','away','away_name','home','home_name','away_score','home_score','neutral']
STATS=('fgm','fga','tpm','tpa','ftm','fta','orb','drb','tov')

def request_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'SharpHandicapper-CBB-Research/1.1','Accept':'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=25) as resp:return json.load(resp)
        except Exception:
            if attempt==2:raise
            time.sleep(2**attempt)

def game_from_event(e):
    if not e.get('status',{}).get('type',{}).get('completed'):return None
    c=(e.get('competitions') or [{}])[0]
    sides={x.get('homeAway'):x for x in c.get('competitors',[])}
    if 'home' not in sides or 'away' not in sides:return None
    h,a=sides['home'],sides['away']
    try:
        date=dt.datetime.fromisoformat(e['date'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
        return dict(date=date,game_id=str(e['id']),away=str(a['team']['id']),away_name=a['team']['displayName'],home=str(h['team']['id']),home_name=h['team']['displayName'],away_score=int(a['score']),home_score=int(h['score']),neutral=int(bool(c.get('neutralSite'))))
    except (ValueError,TypeError,KeyError):return None

def load_games_csv(path):
    with open(path,newline='',encoding='utf8-sig') as f:
        rows=list(csv.DictReader(f))
    out=[]
    for row in rows:
        r={k:row[k] for k in HEAD}
        for key in ('away_score','home_score','neutral'):r[key]=int(r[key])
        out.append(r)
    return out

def fetch_games(start,end):
    games={};day=start
    while day<=end:
        q=urllib.parse.urlencode({'dates':day.strftime('%Y%m%d'),'groups':50,'limit':500})
        for e in request_json(SCOREBOARD+'?'+q).get('events',[]):
            r=game_from_event(e)
            if r:games[r['game_id']]=r
        day+=dt.timedelta(days=1)
        if day<=end:time.sleep(.4)
    return list(games.values())

def integrity(games):
    errors=[];seen_games=set();played={}
    for g in games:
        i=g['game_id']
        if i in seen_games:errors.append({'game_id':i,'issue':'duplicate game ID'})
        seen_games.add(i)
        if g['home']==g['away']:errors.append({'game_id':i,'issue':'same opponent ID'})
        for k in ('home_score','away_score'):
            if not (0<=g[k]<=250):errors.append({'game_id':i,'issue':f'invalid {k}'})
        for t in (g['home'],g['away']):
            key=(g['date'],t)
            if key in played:errors.append({'game_id':i,'issue':f'team {t} plays twice {g["date"]}: {played[key]} and {i}'})
            played[key]=i
    return errors

def normkey(s):return re.sub(r'[^a-z0-9]','',str(s).lower())
def number(s):
    try:return float(str(s).replace(',','').strip())
    except (ValueError,TypeError):return None

def pair(v):
    if not isinstance(v,str):return None
    m=re.fullmatch(r'\s*(\d+)\s*[-/]\s*(\d+)\s*',v)
    return tuple(map(int,m.groups())) if m else None

def team_stats(data):
    """Map summary.boxscore.teams team id -> canonical totals; different ESPN keys handled."""
    rows={}
    for t in data.get('boxscore',{}).get('teams',[]):
        ident=str(t.get('team',{}).get('id',''))
        raw={normkey(x.get('name',x.get('label',''))): x.get('displayValue',x.get('value')) for x in t.get('statistics',[]) if isinstance(x,dict)}
        values={}
        for key, aliases in {
            'fg':('fieldgoals','fieldgoalsmadeattempted','fg'),
            'tp':('threepointfieldgoals','threepointfieldgoalsmadeattempted','threepointers','3ptfieldgoals'),
            'ft':('freethrows','freethrowsmadeattempted','ft')}.items():
            for alias in aliases:
                val=pair(raw.get(alias))
                if val is not None:values[key+'m'],values[key+'a']=val;break
        singles={'orb':('offensiverebounds','offreb','oreb'),'drb':('defensiverebounds','defreb','dreb'),'tov':('turnovers','totalturnovers')}
        for field,aliases in singles.items():
            for alias in aliases:
                if alias in raw:
                    values[field]=number(raw[alias]);break
        # Some sources provide team stats in different key combinations. Preserve missingness.
        rows[ident]={x:values.get(x) for x in STATS}
    return rows

def metrics(box,points):
    if any(box.get(k) is None for k in STATS):return None
    fgm,fga,tpm,tpa,ftm,fta,orb,drb,tov=(box[k] for k in STATS)
    if fga<=0 or min(fgm,fga,tpm,tpa,ftm,fta,orb,drb,tov)<0 or fgm>fga or tpm>tpa or ftm>fta or tpa>fga:return None
    poss=fga-orb+tov+0.475*fta
    if poss<=0:return None
    return {'poss':poss,'off_rating':100*points/poss,'efg':(fgm+.5*tpm)/fga,'tov_pct':tov/poss,'orb':orb,'drb':drb,'ftr':fta/fga,'three_pct':tpm/tpa if tpa else None,'three_rate':tpa/fga,'ft_pct':ftm/fta if fta else None}

def run(args):
    today=dt.datetime.now(ZoneInfo('America/New_York')).date()
    start=dt.date.fromisoformat(args.start) if args.start else dt.date(today.year if today.month>=7 else today.year-1,11,1)
    end=dt.date.fromisoformat(args.end) if args.end else today
    if end<start or (end-start).days>230:raise SystemExit('Date range must be 0–230 days, chronological')
    games=load_games_csv(args.games_csv) if args.games_csv else fetch_games(start,end)
    games=sorted(games,key=lambda g:(g['date'],g['game_id']))
    if args.max_games:games=games[:args.max_games]
    if not games:raise SystemExit('No completed games found; no ratings generated')
    errors=integrity(games)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    (out/'cbb_1_1_integrity.json').write_text(json.dumps({'issues':errors,'source_games':len(games)},indent=2)+'\n')
    if errors:raise SystemExit(f'Data-integrity failure: {len(errors)} issues; inspect artifact')
    with (out/'cbb_1_1_games.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=HEAD);w.writeheader();w.writerows(games)
    teamnames={}
    for g in games:
        teamnames[g['home']]=g['home_name'];teamnames[g['away']]=g['away_name']
    records=[];bad=[]
    for idx,g in enumerate(games):
        try:
            data=request_json(SUMMARY+'?'+urllib.parse.urlencode({'event':g['game_id']}))
            sides=team_stats(data)
            hm=metrics(sides.get(g['home'],{}),g['home_score'])
            am=metrics(sides.get(g['away'],{}),g['away_score'])
            if hm is None or am is None:raise ValueError('missing/incomplete boxscore team statistics')
            # one common pace estimate for each game, so both teams use identical possession count
            pace=(hm['poss']+am['poss'])/2
            for role,t,other,score,opp_score,m,otherm in (
                ('home',g['home'],g['away'],g['home_score'],g['away_score'],hm,am),
                ('away',g['away'],g['home'],g['away_score'],g['home_score'],am,hm)):
                records.append(dict(date=g['date'],game_id=g['game_id'],team_id=t,team=teamnames[t],opp_id=other,role=role,neutral=g['neutral'],points=score,points_allowed=opp_score,estimated_possessions=round(pace,3),off_rating=round(100*score/pace,3),def_rating=round(100*opp_score/pace,3),efg=round(m['efg'],5),tov_pct=round(m['tov_pct'],5),orb_pct=round(m['orb']/(m['orb']+otherm['drb']),5) if (m['orb']+otherm['drb']) else '',ftr=round(m['ftr'],5),three_rate=round(m['three_rate'],5)))
        except Exception as exc:
            bad.append({'game_id':g['game_id'],'date':g['date'],'reason':str(exc)[:180]})
        if not args.games_csv and (idx+1)%50==0:print(f'Processed {idx+1}/{len(games)} boxscores',flush=True)
        if args.fetch_delay:time.sleep(args.fetch_delay)
    fields=['date','game_id','team_id','team','opp_id','role','neutral','points','points_allowed','estimated_possessions','off_rating','def_rating','efg','tov_pct','orb_pct','ftr','three_rate']
    with (out/'cbb_1_1_team_games.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(records)
    with (out/'cbb_1_1_missing_boxscores.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['game_id','date','reason']);w.writeheader();w.writerows(bad)
    # opponent-adjusted points/100 via shrinkage and iterative correction; only complete boxes
    teams=defaultdict(list)
    for r in records:teams[r['team_id']].append(r)
    league=sum(r['off_rating'] for r in records)/len(records) if records else None
    offense={t:0. for t in teams};defense={t:0. for t in teams}
    if records:
        for _ in range(18):
            nexto={};nextd={}
            for t,rs in teams.items():
                n=len(rs);factor=n/(n+args.shrink)
                nexto[t]=factor*sum(r['off_rating']-league+defense.get(r['opp_id'],0) for r in rs)/n
                nextd[t]=factor*sum(r['def_rating']-league+offense.get(r['opp_id'],0) for r in rs)/n
            offense={t:.5*offense[t]+.5*nexto[t] for t in teams}
            defense={t:.5*defense[t]+.5*nextd[t] for t in teams}
    ratings=[]
    for t,rs in teams.items():
        def mean(k):return round(sum(float(r[k]) for r in rs if r[k]!='')/sum(r[k]!='' for r in rs),4) if any(r[k]!='' for r in rs) else ''
        ratings.append({'team_id':t,'team':teamnames[t],'complete_boxscore_games':len(rs),'adj_off_points_per_100':round(league+offense[t],3),'adj_def_points_allowed_per_100':round(league+defense[t],3),'estimated_pace':mean('estimated_possessions'),'efg':mean('efg'),'tov_pct':mean('tov_pct'),'orb_pct':mean('orb_pct'),'ftr':mean('ftr'),'three_rate':mean('three_rate')})
    ratings.sort(key=lambda r:r['team'])
    with (out/'cbb_1_1_ratings.csv').open('w',newline='') as f:
        names=list(ratings[0]) if ratings else ['team_id','team','complete_boxscore_games','adj_off_points_per_100','adj_def_points_allowed_per_100','estimated_pace','efg','tov_pct','orb_pct','ftr','three_rate']
        w=csv.DictWriter(f,fieldnames=names);w.writeheader();w.writerows(ratings)
    report={'phase':'CBB 1.1 test-only','data_source':'ESPN unofficial scoreboards and boxscore summaries','collection_range':[start.isoformat(),end.isoformat()],'source_games':len(games),'complete_boxscore_games':len(records)//2,'missing_or_incomplete_boxscore_games':len(bad),'team_count_unfiltered':len(teamnames),'teams_with_full_boxscore_metrics':len(ratings),'current_season_required':True,'model_status':'PRELIMINARY_NOT_BETTING_VALIDATED','checks':{'duplicate_team_dates':0,'game_id_duplicates':0,'complete_boxscores':len(records)//2},'limitations':['D-I filtering not yet verified: group=50 may include non-D-I opponents; team_count_unfiltered is not the D-I count.','Possessions use FGA-ORB+TO+0.475 FTA estimate, not exact play-by-play possessions.','Opponent adjustment is a ridge-shrunken iterative approximation; not calibrated or validated out of sample.','No injuries, official odds, lineup projections, or first-half score model. Missing boxscores are excluded, never imputed.','Unofficial ESPN feeds are subject to coverage and schema changes.']}
    (out/'cbb_1_1_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not records:raise SystemExit('No complete boxscores; inspect missing_boxscores.csv and source compatibility')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--start',help='YYYY-MM-DD, defaults to November 1 of current season')
    p.add_argument('--end',help='YYYY-MM-DD, defaults to current eastern date')
    p.add_argument('--out',default='generated/cbb_1_1')
    p.add_argument('--games-csv',help='Optional existing CBB 1.0 CSV for offline testing')
    p.add_argument('--max-games',type=int,default=0)
    p.add_argument('--fetch-delay',type=float,default=.2)
    p.add_argument('--shrink',type=float,default=12.0)
    run(p.parse_args())
