#!/usr/bin/env python3
"""CBB 1.3 TEST ONLY: inspect ESPN completed-game box score coverage.
No rating changes, model edits, publication, or website commits.
Uses preexisting scripts/cbb_1_1.py for the current baseline parser.
"""
import argparse,csv,datetime as dt,json,sys,urllib.parse
from collections import Counter
from pathlib import Path

try:
    import cbb_1_1 as old
except ImportError:
    raise SystemExit('Missing scripts/cbb_1_1.py; keep existing CBB 1.1 Python script in scripts/')

STAT_FIELDS=('fgm','fga','tpm','tpa','ftm','fta','orb','drb','tov')

def inspect_event(g, timeout_report):
    row={'date':g['date'],'game_id':g['game_id'],'away':g['away_name'],'home':g['home_name'],
         'status':'unknown','home_missing':'','away_missing':'','observed_stat_keys':'','team_boxscore_ids':'',
         'player_boxscore_teams':0,'error':''}
    try:
        obj=old.request_json(old.SUMMARY+'?'+urllib.parse.urlencode({'event':g['game_id']}))
        box=obj.get('boxscore') or {}
        teams=box.get('teams') or []
        teamids=[str(t.get('team',{}).get('id','')) for t in teams if isinstance(t,dict)]
        all_names=[]
        for t in teams:
            for s in (t.get('statistics') or []):
                if isinstance(s,dict): all_names.append(str(s.get('name',s.get('label','UNKNOWN'))))
        row['team_boxscore_ids']=';'.join(teamids)
        row['observed_stat_keys']=';'.join(sorted(set(all_names)))[:1400]
        row['player_boxscore_teams']=len(box.get('players') or [])
        stats=old.team_stats(obj)
        for side in ('home','away'):
            ident=g[side]
            vals=stats.get(ident,{})
            missing=[k for k in STAT_FIELDS if vals.get(k) is None]
            row[f'{side}_missing']=';'.join(missing)
        if not teams:
            row['status']='no_team_boxscore'
        elif g['home'] not in teamids or g['away'] not in teamids:
            row['status']='team_id_mismatch'
        elif row['home_missing'] or row['away_missing']:
            row['status']='missing_fields'
        elif old.metrics(stats.get(g['home'],{}),g['home_score']) is None or old.metrics(stats.get(g['away'],{}),g['away_score']) is None:
            row['status']='invalid_stat_values'
        else:
            row['status']='complete'
    except Exception as ex:
        row['status']='fetch_error'
        row['error']=f'{type(ex).__name__}: {ex}'[:300]
        timeout_report.append({'game_id':g['game_id'],'error':row['error']})
    return row

def date_sample(day,max_games):
    games=old.fetch_games(day,day)
    games.sort(key=lambda g:(g['date'],g['game_id']))
    return games[:max_games],len(games)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--target-date',default='2026-11-02')
    ap.add_argument('--control-date',default='2025-11-10')
    ap.add_argument('--max-games-per-date',type=int,default=25)
    ap.add_argument('--out',default='generated/cbb_1_3')
    args=ap.parse_args()
    if not 1<=args.max_games_per_date<=100:ap.error('--max-games-per-date must be from 1 to 100')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    rows=[];notes=[];date_reports=[]
    for label,date_str in [('current',args.target_date),('control',args.control_date)]:
        d=dt.date.fromisoformat(date_str)
        try:
            games,total=date_sample(d,args.max_games_per_date)
        except Exception as ex:
            notes.append({'sample':label,'stage':'scoreboard','error':f'{type(ex).__name__}: {ex}'})
            games=[];total=0
        exceptions=[]
        for g in games:
            r=inspect_event(g,exceptions);r['sample']=label;rows.append(r)
            print(f"{label}: {g['game_id']} {r['status']} {g['away_name']} @ {g['home_name']}",flush=True)
        sm=[r for r in rows if r['sample']==label]
        date_reports.append({'sample':label,'date':date_str,'completed_games_on_scoreboard':total,
            'games_inspected':len(sm),'complete':sum(r['status']=='complete' for r in sm),
            'statuses':dict(Counter(r['status'] for r in sm)),'fetch_errors':len(exceptions),
            'total_games_beyond_sample':max(0,total-len(sm))})
    fields=['sample','date','game_id','away','home','status','home_missing','away_missing','observed_stat_keys','team_boxscore_ids','player_boxscore_teams','error']
    with (out/'cbb_1_3_boxscore_details.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    by_status=Counter(r['status'] for r in rows)
    missing=Counter(k for r in rows for side in ('home_missing','away_missing') for k in r[side].split(';') if k)
    current=next((r for r in date_reports if r['sample']=='current'),{})
    control=next((r for r in date_reports if r['sample']=='control'),{})
    if current.get('complete',0)>0:
        conclusion='Current-season complete team boxscores found. Original 1.1 may need changes only for incomplete games.'
    elif control.get('complete',0)>0:
        conclusion='Prior-season parser works on the control sample but not on current games; inspect timing and fields.'
    elif current.get('games_inspected',0)>0 or control.get('games_inspected',0)>0:
        conclusion='Both samples lacked complete parsed boxscores. Inspect observed_stat_keys, team IDs and missing fields; parser/schema mismatch possible.'
    else:
        conclusion='Neither sample fetched usable game summaries; inspect network and scoreboard errors.'
    report={'phase':'CBB 1.3 boxscore diagnostics TEST ONLY','source':'ESPN unofficial site API',
        'samples':date_reports,'status_totals':dict(by_status),'missing_field_counts':dict(missing),
        'issues':notes,'conclusion':conclusion,'notices':[
          'Sampled coverage is not league-wide coverage. It may include non-D-I opponents.',
          'No D-I filtering, roster/injury checks, accuracy validation or profitable betting claims.',
          'This diagnostic never commits or publishes website data; CBB 1.2 site is untouched.'
        ]}
    (out/'cbb_1_3_diagnostic.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
    # Diagnostics capture is a success even when there are zero complete records.
    # Investigate the report; don't obscure results with exit 1.

if __name__=='__main__':main()
