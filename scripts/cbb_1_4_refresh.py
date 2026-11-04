"""Build the test site's CBB 1.4 ratings JSON from complete team boxscores."""
import argparse
import json
from pathlib import Path

from cbb_1_4_backtest import fit, read


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('team_games')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    rows = read(args.team_games)
    if not rows:
        raise SystemExit('No complete team boxscores.')
    league, observations, offense, defense = fit(rows, 12, 3)
    names = {row['team_id']: row['team'] for row in rows}
    teams = [
        dict(id=team, name=names[team], games=values[0], pace=values[3],
             off=offense[team], defense=defense[team])
        for team, values in sorted(observations.items(), key=lambda item: names[item[0]])
    ]
    snapshot = dict(cutoff=max(row['date'] for row in rows),
                    usable_games=len(rows) // 2, league=league, teams=teams)
    if args.output.exists():
        previous = json.loads(args.output.read_text())
        if (snapshot['cutoff'] < previous['cutoff']
                or snapshot['usable_games'] < previous['usable_games']
                or len(teams) < len(previous['teams'])):
            raise SystemExit('Coverage regressed. Previous snapshot retained.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, allow_nan=False) + '\n')
    print(f"Ratings through {snapshot['cutoff']}: {len(teams)} teams, {snapshot['usable_games']} games")


if __name__ == '__main__':
    main()
