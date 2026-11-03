#!/usr/bin/env python3
"""CBB 1.3.1 test-only: verify ESPN composite field-name repair.
Requires scripts/cbb_1_1.py and scripts/cbb_1_3_boxscore_diagnostic.py.
Never writes website data or modifies the original collector.
"""
import cbb_1_1 as old
import cbb_1_3_boxscore_diagnostic as diagnostic

def corrected_team_stats(data):
    rows = {}
    for team in (data.get('boxscore') or {}).get('teams', []):
        team_id = str((team.get('team') or {}).get('id', ''))
        raw = {}
        for stat in team.get('statistics') or []:
            if isinstance(stat, dict):
                name = old.normkey(stat.get('name', stat.get('label', '')))
                raw[name] = stat.get('displayValue', stat.get('value'))
        vals = {}
        aliases = {
            'fg': ('fieldgoalsmadefieldgoalsattempted','fieldgoalsmadeattempted','fieldgoals','fg'),
            'tp': ('threepointfieldgoalsmadethreepointfieldgoalsattempted',
                   'threepointfieldgoalsmadeattempted','threepointfieldgoals','threepointers','3ptfieldgoals'),
            'ft': ('freethrowsmadefreethrowsattempted','freethrowsmadeattempted','freethrows','ft'),
        }
        for prefix, names in aliases.items():
            for name in names:
                value = old.pair(raw.get(name))
                if value is not None:
                    vals[prefix+'m'], vals[prefix+'a'] = value
                    break
        singles = {
            'orb': ('offensiverebounds','offreb','oreb'),
            'drb': ('defensiverebounds','defreb','dreb'),
            'tov': ('turnovers','totalturnovers'),
        }
        for key, names in singles.items():
            for name in names:
                if name in raw:
                    vals[key] = old.number(raw[name])
                    break
        rows[team_id] = {field: vals.get(field) for field in old.STATS}
    return rows

old.team_stats = corrected_team_stats

if __name__ == '__main__':
    diagnostic.main()
