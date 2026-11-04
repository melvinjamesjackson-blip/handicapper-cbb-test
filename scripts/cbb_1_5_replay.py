"""Compare early-season projections using only games from earlier dates."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from cbb_1_4_backtest import fit, read


def projection(league, home, away, neutral):
    pace = (home[2] + away[2]) / 2
    home_points = (league + home[0] + away[1]) * pace / 100
    away_points = (league + away[0] + home[1]) * pace / 100
    return home_points - away_points + (0 if neutral else 3), home_points + away_points


def run(prior_rows, current_rows, games):
    if not prior_rows or not current_rows or not games:
        raise ValueError('All three input files must contain rows.')
    if max(r['date'] for r in prior_rows) >= min(g['date'] for g in games):
        raise ValueError('Prior season must end before the replay begins.')
    _, prior_obs, prior_off, prior_def = fit(prior_rows, 12, 3)
    prior = {t: (prior_off[t], prior_def[t], o[3])
             for t, o in prior_obs.items() if o[0] >= 5}
    game_index = {g['game_id']: g for g in games}
    if len(game_index) != len(games):
        raise ValueError('Duplicate game IDs in replay schedule.')
    paired = defaultdict(list)
    for row in current_rows:
        game = game_index.get(row['game_id'])
        if not game or row['date'] != game['date'] or row['team_id'] not in (game['home'], game['away']):
            raise ValueError('Replay boxscores and schedule do not match.')
        paired[row['game_id']].append(row)
    if any(len(pair) != 2 or len({row['team_id'] for row in pair}) != 2 for pair in paired.values()):
        raise ValueError('Incomplete or duplicate team boxscore pair.')
    training = defaultdict(list)
    for row in current_rows:
        training[row['date']].append(row)
    schedule = defaultdict(list)
    for game in games:
        schedule[game['date']].append(game)
    history = []
    skipped = Counter()
    metrics = defaultdict(list)
    for day, slate in sorted(schedule.items()):
        if history:
            league, obs, off, defense = fit(history, 12, 3)
        else:
            obs = {}
        for game in slate:
            home, away = game['home'], game['away']
            counts = [obs[t][0] if t in obs else 0 for t in (home, away)]
            if min(counts) == 0:
                skipped['no_current_game_for_one_or_both'] += 1
            elif min(counts) >= 5:
                skipped['both_have_five_current_games'] += 1
            elif home not in prior or away not in prior:
                skipped['missing_eligible_prior'] += 1
            else:
                current = [(off[t], defense[t], obs[t][3]) for t in (home, away)]
                blended = []
                for t, count, values in zip((home, away), counts, current):
                    blended.append(tuple((count * x + 5 * y) / (count + 5)
                                         for x, y in zip(values, prior[t])))
                actual_home, actual_away = int(game['home_score']), int(game['away_score'])
                neutral = bool(int(game['neutral']))
                baseline_margin, _ = projection(league, *current, neutral)
                for name, ratings in [('current_only', current), ('blend', blended)]:
                    margin, total = projection(league, *ratings, neutral)
                    actual_margin = actual_home - actual_away
                    metrics[name].append((abs(margin - actual_margin),
                                          abs(total - actual_home - actual_away),
                                          margin * actual_margin > 0))
                    if abs(baseline_margin) >= 10:
                        direction = 1 if baseline_margin > 0 else -1
                        metrics[name + '_large'].append(((margin - actual_margin) * direction,))
        history.extend(training[day])
    report = dict(scheduled_games=len(games), compared_games=len(metrics['blend']),
                  skipped=dict(skipped), models={})
    for name in ('current_only', 'blend'):
        rows = metrics[name]
        large = metrics[name + '_large']
        report['models'][name] = dict(
            margin_mae=mean(r[0] for r in rows) if rows else None,
            total_mae=mean(r[1] for r in rows) if rows else None,
            winner_accuracy=mean(r[2] for r in rows) if rows else None,
            large_favorite_games=len(large),
            large_favorite_margin_bias=mean(r[0] for r in large) if large else None)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prior', required=True)
    parser.add_argument('--current', required=True)
    parser.add_argument('--games', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = run(read(args.prior), read(args.current), read(args.games))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not report['compared_games']:
        raise SystemExit('No eligible matched comparisons.')
