"""Collect Steam concurrent player counts for H1G.
Keep data/<appid>.json as a JSON array for existing MediaWiki widgets.
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
STATUS = Path('status/collection.json')


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temp.replace(path)


def timestamp(row):
    return datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).astimezone(UTC)


def aggregate(rows, bucket, period):
    samples = sum(int(r.get('samples', 1)) for r in rows)
    if not samples:
        raise ValueError('No samples')
    newest = max(rows, key=timestamp)
    return {
        'timestamp': newest['timestamp'],
        'players': round(sum(int(r['players']) * int(r.get('samples', 1)) for r in rows) / samples),
        'min': min(int(r.get('min', r['players'])) for r in rows),
        'max': max(int(r.get('max', r['players'])) for r in rows),
        'samples': samples,
        'period': period,
        'bucket': bucket,
    }


def compact(appid, records, now):
    cutoff30 = now - timedelta(days=30)
    cutoff365 = now - timedelta(days=365)
    recent = []
    daily = defaultdict(list)
    old = []
    for row in records:
        when = timestamp(row)
        if when >= cutoff30:
            recent.append(row)
        elif when >= cutoff365:
            daily[when.strftime('%Y-%m-%d')].append(row)
        else:
            old.append(row)
    if old:
        path = ARCHIVE / f'{appid}.json'
        previous = read_json(path, [])
        groups = defaultdict(list)
        for row in previous + old:
            key = row.get('bucket') if row.get('period') == 'month' else timestamp(row).strftime('%Y-%m')
            groups[key].append(row)
        write_json(path, [aggregate(rows, key, 'month') for key, rows in sorted(groups.items())])
    daily_rows = [aggregate(rows, key, 'day') for key, rows in sorted(daily.items())]
    return sorted(recent + daily_rows, key=timestamp)


def fetch(appid):
    url = f'https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}'
    request = urllib.request.Request(url, headers={'User-Agent': 'H1G-Steam-Players/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response).get('response', {})
    if result.get('result') != 1 or 'player_count' not in result:
        raise ValueError('Steam API returned no valid player count')
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
    result = {'started_at': now.isoformat(timespec='seconds'), 'total': len(ids),
              'ok': 0, 'unavailable': [], 'errors': [], 'rate_limited': False}
    for index, appid in enumerate(ids, 1):
        try:
            players = fetch(appid)
            path = DATA / f'{appid}.json'
            history = read_json(path, [])
            history.append({'timestamp': datetime.now(UTC).isoformat(timespec='seconds'), 'players': players})
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
        if index < len(ids) and not result['rate_limited']:
            time.sleep(2 + random.uniform(0, 0.5))
    result['finished_at'] = datetime.now(UTC).isoformat(timespec='seconds')
    write_json(STATUS, result)
    print(f"Completed: {result['ok']} OK, {len(result['unavailable'])} unavailable, {len(result['errors'])} errors", flush=True)
    if result['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
