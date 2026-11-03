#!/usr/bin/env python3
"""CBB Phase 1.2 test-only projection and betting-sign audit; no external dependencies."""
import argparse, json, math
from collections import Counter
from pathlib import Path


def lean(home_margin, market_home_spread, model_total, market_total, spread_cut=3, total_cut=5):
    # Positive home_margin means home is projected to win. Home covers when
    # model home margin + posted home spread > 0.
    cover_edge = home_margin + market_home_spread
    side = ('HOME' if cover_edge > 0 else 'AWAY') if abs(cover_edge) >= spread_cut else 'PASS'
    total_edge = model_total - market_total
    totals = ('OVER' if total_edge > 0 else 'UNDER') if abs(total_edge) >= total_cut else 'PASS'
    return side, totals, round(cover_edge, 2), round(total_edge, 2)


def check_signs():
    cases = [
        (4,-7.5,145,145,'AWAY','PASS'),
        (11,-7.5,151,145,'HOME','OVER'),
        (-5,2,137,143,'AWAY','UNDER'),
        (-1,5,143,143,'HOME','PASS'),
        (6,-6,140,140,'PASS','PASS'),
        (-10,7.5,140,140,'PASS','PASS'),
        (5,0,140,140,'HOME','PASS'),
    ]
    tests=[]
    for m,s,t,mt,exp_s,exp_t in cases:
        got_s,got_t,_,_=lean(m,s,t,mt)
        tests.append({'home_margin':m,'market_home_spread':s,'model_total':t,'market_total':mt,'spread_signal':got_s,'total_signal':got_t,'pass':(got_s,got_t)==(exp_s,exp_t)})
    return tests


def finite(x):return type(x) in (int,float) and math.isfinite(x)

def validate(doc):
    errors=[]; warnings=[]; games=doc.get('games')
    if not isinstance(games,list):return ['games must be a list'],warnings,{}
    day=doc.get('day'); seen=set(); available=0; blocked=0; reasons=Counter()
    for i,g in enumerate(games):
        label=f"games[{i}]"
        if not isinstance(g,dict):errors.append(label+' not an object');continue
        gid=str(g.get('id') or '')
        if not gid:errors.append(label+' missing id')
        if gid in seen:errors.append(label+' duplicate id '+gid)
        seen.add(gid)
        for k in ('away','home'):
            if not g.get(k):errors.append(label+' missing '+k)
        if g.get('away_id')==g.get('home_id'):errors.append(label+' has same home and away team')
        if day and g.get('date')!=day:errors.append(label+' date mismatch: '+str(g.get('date')))
        if g.get('projection_available'):
            available+=1
            keys=('pred_home','pred_away','home_margin','total')
            if not all(finite(g.get(k)) for k in keys):errors.append(label+' incomplete/nonfinite projection')
            else:
                if abs((g['pred_home']-g['pred_away'])-g['home_margin'])>0.16:errors.append(label+' margin does not match scores')
                if abs((g['pred_home']+g['pred_away'])-g['total'])>0.16:errors.append(label+' total does not match scores')
                if not all(20<=g[k]<=150 for k in ('pred_home','pred_away')):warnings.append(label+' unusually extreme score; inspect manually')
            if g.get('completed'):warnings.append(label+' projection for already completed game; check timestamp and leakage')
        else:
            blocked+=1;reasons[str(g.get('reason','unspecified'))]+=1
    if doc.get('matchups')!=len(games):errors.append('matchups count does not equal games length')
    if doc.get('projections_available')!=available:errors.append('projections_available does not match games')
    if doc.get('projections_blocked')!=blocked:errors.append('projections_blocked does not match games')
    if len(games)==0:warnings.append('NO_GAMES: no matchups in published data')
    if available==0:warnings.append('NO_PROJECTIONS: no usable model projections')
    if doc.get('prior_final_games',0)<600:warnings.append('LOW_PRIOR_COVERAGE: fewer than 600 historical final games')
    if doc.get('rating_method','').lower().find('not')>=0:warnings.append('Experimental baseline; not a validated betting model')
    if day is None:warnings.append('Missing source day')
    return errors,warnings,{'day':day,'matchups':len(games),'projections_available':available,'projections_blocked':blocked,'coverage_pct':round(100*available/max(1,len(games)),1),'blocked_reasons':dict(reasons),'prior_final_games':doc.get('prior_final_games')}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',default='docs/data.json');ap.add_argument('--out',default='generated/cbb_validation');a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    tests=check_signs(); errors=[];warnings=[];stats={}
    if not Path(a.input).is_file():errors.append('MISSING_FILE: '+a.input+' not found; run CBB Game-Day Auto Publish first')
    else:
        try: doc=json.loads(Path(a.input).read_text(encoding='utf-8'));errors,warnings,stats=validate(doc)
        except (json.JSONDecodeError,UnicodeError) as ex:errors=['INVALID_JSON: '+str(ex)]
    if not all(x['pass'] for x in tests):errors.append('SPREAD_DIRECTION_TEST_FAILURE')
    result={'phase':'CBB 1.2 projection audit — TEST ONLY','input':a.input,'status':'PASS' if not errors else 'FAIL','errors':errors,'warnings':warnings,'coverage':stats,'spread_total_test_cases':tests,'scope':'Data integrity and direction checks only. Does NOT establish predictive accuracy, profitable edges or calibrated win probabilities.'}
    (out/'cbb_1_2_validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
