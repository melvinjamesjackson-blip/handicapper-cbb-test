"""Run an expanding-window comparison using schedule and final score rows."""
import argparse
import csv
import datetime as dt
from statistics import mean

from cbb_gameday import fetch_range, project, ratings


def load_prior(path, cutoff):
    with open(path, encoding='utf-8-sig', newline='') as source:
        return [
            dict(completed=True, home_id=row['home'], away_id=row['away'],
                 home=row['home_name'], away=row['away_name'],
                 home_score=int(row['home_score']), away_score=int(row['away_score']),
                 neutral=row['neutral'].strip().lower() in ('1', 'true'))
            for row in csv.DictReader(source) if row['date'] < cutoff
        ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2026-11-02', type=dt.date.fromisoformat)
    parser.add_argument('--end', default='2026-11-24', type=dt.date.fromisoformat)
    parser.add_argument('--prior', default='research/cbb_1_3_2_games.csv')
    args = parser.parse_args()
    prior, _ = ratings(load_prior(args.prior, args.start.isoformat()))
    games = fetch_range(args.start, args.end)
    errors = []
    published = comparable = 0
    for date in sorted({g['date'] for g in games}):
        cutoff = dt.date.fromisoformat(date) - dt.timedelta(days=1)
        current, _ = ratings([g for g in games if g['date'] < date])
        for game in (g for g in games if g['date'] == date):
            result = project(game, prior, current, cutoff)
            if game['id'] == '401928791':
                print('Ohio vs New Mexico State:', game['neutral'], result)
            if not game['completed']:
                continue
            published += int(result['projection_available'])
            baseline = result.get('prior_home_spread')
            if baseline is None or not (result['home_current_games'] and result['away_current_games']):
                continue
            comparable += 1
            margin = game['home_score'] - game['away_score']
            errors.append((abs(margin + baseline), abs(margin - result['home_margin'])))
    print(f'Final games with a candidate projection: {published}')
    if comparable:
        old, new = zip(*errors)
        print(f'Paired games: {comparable}. Margin MAE: prior {mean(old):.2f}; updated {mean(new):.2f}')


if __name__ == '__main__':
    main()
