"""Collect Steam concurrent player counts for H1G.

Input: games.json, a list of {"appid": number, "wiki": "slug"}.
Output: data/<appid>.json (compatible with existing MediaWiki widget),
        archive/<appid>.json for monthly older data, status/collection.json.
"""
import json
import random
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path('data')
ARCHIVE = Path('archive')
STATUS = Path('status/collection.json')
UTC = timezone.utc


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temp.replace(path)


def stamp(row):
    return datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).astimezone(UTC)


def aggregate(rows, bucket, period):
    weights = [max(1, int(r.get('samples', 1))) for r in rows]
    total = sum(weights)
    latest = max(rows, key=stamp)
    return {
        'timestamp': latest['timestamp'],
        'players': round(sum(int(r['players']) * w for r, w in zip(rows, weights)) / total),
        'min': min(int(r.get('min', r['players'])) for r in rows),
        'max': max(int(r.get('max', r['players'])) for r in rows),
        'samples': total,
        'period': period,
        'bucket': bucket,
    }


def compact(appid, rows, now):
    recent, daily, older = [], defaultdict(list), []
    for row in rows:
        age = now - stamp(row)
        if age <= timedelta(days=30):
            recent.append(row)
        elif age <= timedelta(days=365):
            daily[stamp(row).strftime('%Y-%m-%d')].append(row)
        else:
            older.append(row)

    if older:
        path = ARCHIVE / f'{appid}.json'
        existing = read_json(path, [])
        groups = defaultdict(list)
        for row in existing + older:
            key = row.get('bucket') if row.get('period') == 'month' else stamp(row).strftime('%Y-%m')
            groups[key].append(row)
        write_json(path, [aggregate(group, key, 'month') for key, group in sorted(groups.items())])

    reduced = [aggregate(group, key, 'day') for key, group in sorted(daily.items())]
    return sorted(recent + reduced, key=stamp)


def fetch(appid):
    url = ('https://api.steampowered.com/ISteamUserStats/'
           f'GetNumberOfCurrentPlayers/v1/?appid={appid}')
    req = urllib.request.Request(url, headers={'User-Agent': 'H1G-Steam-Players/1.0'})
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.load(response).get('response', {})
    if payload.get('result') != 1 or 'player_count' not in payload:
        raise ValueError('No valid player count in API response')
    players = int(payload['player_count'])
    if players < 0:
        raise ValueError('Negative player count')
    return players


def main():
    games = read_json(Path('games.json'), [])
    ids = list(dict.fromkeys(int(g['appid']) for g in games if g.get('appid')))
    if not ids:
        raise SystemExit('No AppIDs in games.json')

    now = datetime.now(UTC)
    result = {'started_at': now.isoformat(timespec='seconds'), 'total': len(ids),
              'ok': 0, 'unavailable': [], 'errors': [], 'rate_limited': False}

    for index, appid in enumerate(ids, 1):
        try:
            players = fetch(appid)
            path = DATA / f'{appid}.json'
            history = read_json(path, [])
            history.append({'timestamp': datetime.now(UTC).isoformat(timespec='seconds'),
                            'players': players})
            write_json(path, compact(appid, history, datetime.now(UTC)))
            result['ok'] += 1
            print(f'[{index}/{len(ids)}] OK {appid}: {players}', flush=True)
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                result['unavailable'].append({'appid': appid, 'http': exc.code})
                print(f'[{index}/{len(ids)}] UNAVAILABLE {appid}: HTTP {exc.code}', flush=True)
            elif exc.code == 429:
                result['rate_limited'] = True
                result['errors'].append({'appid': appid, 'error': 'HTTP 429 rate limited'})
                print(f'[{index}/{len(ids)}] RATE LIMITED {appid}: stopping', flush=True)
                break
            else:
                result['errors'].append({'appid': appid, 'error': f'HTTP {exc.code}'})
                print(f'[{index}/{len(ids)}] ERROR {appid}: HTTP {exc.code}', flush=True)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
            result['errors'].append({'appid': appid, 'error': str(exc)[:250]})
            print(f'[{index}/{len(ids)}] ERROR {appid}: {exc}', flush=True)
        if index < len(ids):
            time.sleep(2 + random.uniform(0, 0.5))
