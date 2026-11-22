"""Collect Steam concurrent players while tolerating delisted/unreleased apps.

Keep the existing data/<appid>.json contract for MediaWiki widgets.
"""
import json
import random
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
DATA = Path('data')
ARCHIVE = Path('archive')
STATUS = Path('status') / 'collection.json'


def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    tmp.replace(path)


def dt(row):
    return datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).astimezone(UTC)


def weighted_aggregate(rows, bucket, kind):
    total = sum(int(r.get('samples', 1)) for r in rows)
    latest = max(rows, key=dt)
    return {
        'timestamp': latest['timestamp'],
        'players': round(sum(int(r['players']) * int(r.get('samples', 1)) for r in rows) / total),
        'min': min(int(r.get('min', r['players'])) for r in rows),
        'max': max(int(r.get('max', r['players'])) for r in rows),
        'samples': total,
        'period': kind,
        'bucket': bucket,
    }


def compact(appid, records, now):
    cutoff30 = now - timedelta(days=30)
    cutoff365 = now - timedelta(days=365)
    recent, daily, old = [], defaultdict(list), []
    for row in records:
        stamp = dt(row)
        if stamp >= cutoff30:
            recent.append(row)
        elif stamp >= cutoff365:
            daily[stamp.strftime('%Y-%m-%d')].append(row)
        else:
            old.append(row)

    # Archive records only once: archived records are removed from data/.
    if old:
        path = ARCHIVE / f'{appid}.json'
        existing = read_json(path, [])
        groups = defaultdict(list)
        for row in existing + old:
            key = row.get('bucket') if row.get('period') == 'month' else dt(row).strftime('%Y-%m')
            groups[key].append(row)
        write_json(path, [weighted_aggregate(group, key, 'month') for key, group in sorted(groups.items())])

    daily_rows = [weighted_aggregate(group, key, 'day') for key, group in sorted(daily.items())]
    return sorted(recent + daily_rows, key=dt)


def fetch(appid):
    url = ('https://api.steampowered.com/ISteamUserStats/'
           f'GetNumberOfCurrentPlayers/v1/?appid={appid}')
    request = urllib.request.Request(url, headers={'User-Agent': 'H1G-Steam-Players/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response).get('response', {})
    if result.get('result') != 1 or 'player_count' not in result:
        raise ValueError('Steam API did not return a valid player count')
    count = int(result['player_count'])
    if count < 0:
        raise ValueError('Negative player count')
    return count


def main():
    games = read_json(Path('games.json'), [])
    ids = list(dict.fromkeys(int(g['appid']) for g in games if g.get('appid')))
    if not ids:
        raise SystemExit('No AppIDs in games.json')

    now = datetime.now(UTC)
