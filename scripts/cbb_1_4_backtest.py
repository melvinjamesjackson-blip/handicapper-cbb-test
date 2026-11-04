#!/usr/bin/env python3
"""CBB 1.4 research backtest; stdlib only; no network or publication."""
import argparse, collections, csv, datetime, hashlib, json, math
from pathlib import Path

def read(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def fit(history,shrink,hfa):
    teams=collections.defaultdict(list)
    for r in history:teams[r['team_id']].append(r)
    league=sum(float(r['points']) for r in history)/sum(float(r['estimated_possessions']) for r in history)*100
    obs={}
    for t,rs in teams.items():
        n=len(rs);o=d=pace=0
        for r in rs:
            p=float(r['estimated_possessions']);adv=0 if int(r['neutral']) else (hfa/2 if r['role']=='home' else -hfa/2)
            o+=(float(r['points'])-adv)/p*100;d+=(float(r['points_allowed'])+adv)/p*100;pace+=p
        obs[t]=(n,o/n-league,d/n-league,pace/n)
    off={t:0. for t in teams};deff=off.copy()
    for _ in range(80):
        no={};nd={}
        for t,rs in teams.items():
            n,o,d,p=obs[t];w=n/(n+shrink)
            no[t]=w*(o-sum(deff[r['opp_id']] for r in rs)/n)
            nd[t]=w*(d-sum(off[r['opp_id']] for r in rs)/n)
        delta=max(max(abs(no[t]-off[t]),abs(nd[t]-deff[t])) for t in teams)
        off={t:(off[t]+no[t])/2 for t in teams};deff={t:(deff[t]+nd[t])/2 for t in teams}
        if delta<1e-7:break
    return league,obs,off,deff

def summary(rows):
    if not rows:return {'games':0}
    n=len(rows);mean=lambda k:sum(r[k] for r in rows)/n
    return dict(games=n,score_mae=mean('score_error'),margin_mae=mean('margin_error'),total_mae=mean('total_error'),home_margin_bias_pred_minus_actual=mean('margin_bias'),winner_accuracy=sum(r['correct'] for r in rows)/n,mean_predicted_favorite_margin=mean('fav_pred'),mean_actual_margin_for_predicted_favorite=mean('fav_actual'),favorite_margin_bias_pred_minus_actual=mean('fav_bias'))

def run(games_path,teams_path,out,shrink=12.,hfa=3.,minimum=5):
    games=read(games_path);rows=read(teams_path);bygame=collections.defaultdict(list)
    seen=set()
    for g in games:
        datetime.date.fromisoformat(g['date'])
        if g['game_id'] in seen:raise ValueError('Duplicate game ID')
        seen.add(g['game_id'])
    gm={g['game_id']:g for g in games}
    for r in rows:
        if r['game_id'] not in gm:raise ValueError('Unknown team-game')
        bygame[r['game_id']].append(r)
    dates=collections.defaultdict(list);training=collections.defaultdict(list)
    for g in games:dates[g['date']].append(g)
    for gid,pair in bygame.items():
        if len(pair)!=2:raise ValueError('Incomplete team pair')
        a,b=pair;g=gm[gid]
        if {a['role'],b['role']}!={'home','away'}:raise ValueError('Invalid roles')
        if a['team_id']!=b['opp_id'] or b['team_id']!=a['opp_id'] or a['points']!=b['points_allowed'] or b['points']!=a['points_allowed'] or a['estimated_possessions']!=b['estimated_possessions']:raise ValueError('Invalid pair')
        for r in pair:
            role=r['role'];p=float(r['estimated_possessions'])
            if not math.isfinite(p) or p<=0 or r['date']!=g['date'] or r['team_id']!=g[role] or float(r['points'])!=float(g[role+'_score']) or r['neutral']!=g['neutral']:raise ValueError('Source mismatch')
            training[r['date']].append(r)
    history=[];predictions=[];skipped=[];last_date=''
    for day,daygames in sorted(dates.items()):
        fitdata=fit(history,shrink,hfa) if history else None
        for g in daygames:
            h,a=g['home'],g['away']
            if not fitdata or any(t not in fitdata[1] or fitdata[1][t][0]<minimum for t in (h,a)):
                skipped.append(dict(date=day,game_id=g['game_id'],reason='fewer_than_required_prior_complete_games'));continue
            league,obs,off,deff=fitdata
            assert last_date<day
            # Common forecast pace uses only each team's earlier games.
            pace=(obs[h][3]+obs[a][3])/2;adv=0 if int(g['neutral']) else hfa/2
            for model in ('adjusted','raw_shrunken','league'):
                effects=({t:(off[t],deff[t]) for t in (h,a)} if model=='adjusted' else {t:((obs[t][0]/(obs[t][0]+shrink)*obs[t][1],obs[t][0]/(obs[t][0]+shrink)*obs[t][2]) if model=='raw_shrunken' else (0,0)) for t in (h,a)})
                hp=(league+effects[h][0]+effects[a][1])*pace/100+adv
                ap=(league+effects[a][0]+effects[h][1])*pace/100-adv
                margin=hp-ap;actual=float(g['home_score'])-float(g['away_score']);sign=1 if margin>=0 else -1
                predictions.append(dict(date=day,game_id=g['game_id'],home=g['home_name'],away=g['away_name'],model=model,training_max_date=last_date,home_prior_games=obs[h][0],away_prior_games=obs[a][0],home_pred=hp,away_pred=ap,home_actual=float(g['home_score']),away_actual=float(g['away_score']),pred_margin=margin,actual_margin=actual,score_error=(abs(hp-float(g['home_score']))+abs(ap-float(g['away_score'])))/2,margin_error=abs(margin-actual),total_error=abs(hp+ap-float(g['home_score'])-float(g['away_score'])),margin_bias=margin-actual,correct=float(margin*actual>0),fav_pred=abs(margin),fav_actual=sign*actual,fav_bias=abs(margin)-sign*actual))
        history.extend(training[day])
        if training[day]:last_date=day
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    for filename,rs in [('cbb_1_4_predictions.csv',predictions),('cbb_1_4_skipped.csv',skipped)]:
        with (out/filename).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rs[0]) if rs else ['date','game_id']);w.writeheader();w.writerows(rs)
    report=dict(version='CBB 1.4',source_games=len(games),training_games=len(bygame),eligible_games=len(predictions)//3,skipped_games=len(skipped),settings=dict(shrink=shrink,home_margin_advantage=hfa,min_prior_games=minimum),input_sha256={Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (games_path,teams_path)},models={},favorite_bins={},limitations=['Retrospective chronological research using currently retrieved historical boxscores; original publication timestamps and later corrections unknown.','Division membership unverified. Eligibility uses prior game counts, not a verified D-I filter.','Fixed settings chosen before this run; no parameter search. This is a new research engine, not a replay of the website.','No market spreads: favorite means model favorite. No ATS, EV, ROI, or market-favorite bias measured.','Home advantage and shrinkage uncalibrated; no preseason roster prior, injury inputs, recency, or 1H model.','Final scores include overtime; estimated possession pace is not adjusted for overtime.'])
    for model in ('adjusted','raw_shrunken','league'):
        rs=[r for r in predictions if r['model']==model]
        report['models'][model]={'all':summary(rs),'before_2026_01_01':summary([r for r in rs if r['date']<'2026-01-01']),'from_2026_01_01':summary([r for r in rs if r['date']>='2026-01-01'])}
    for lo,hi in [(0,5),(5,10),(10,15),(15,1000)]:
        report['favorite_bins'][f'{lo}_to_{hi}']=summary([r for r in predictions if r['model']=='adjusted' and lo<=r['fav_pred']<hi])
    (out/'cbb_1_4_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return predictions,report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--games',required=True);p.add_argument('--team-games',required=True);p.add_argument('--out',default='generated/cbb_1_4');a=p.parse_args();run(a.games,a.team_games,a.out)
