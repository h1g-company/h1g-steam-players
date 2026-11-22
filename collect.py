import json
import os
import random
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
NOW = datetime.now(UTC)
DATA_DIR = Path('data')
ARCHIVE_DIR = Path('archive')


def parse_time(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(UTC)


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temp.replace(path)


def aggregate(records, period):
    groups = defaultdict(list)
    for r in records:
        t = parse_time(r['timestamp'])
        key = t.strftime('%Y-%m-%d' if period == 'day' else '%Y-%m')
        groups[key].append(r)
    output = []
    for key, group in sorted(groups.items()):
        values = [int(r['players']) for r in group]
        latest = max(group, key=lambda r: parse_time(r['timestamp']))
        output.append({
            'timestamp': latest['timestamp'],
            'players': round(sum(values) / len(values)),
            'min': min(int(r.get('min', r['players'])) for r in group),
            'max': max(int(r.get('max', r['players'])) for r in group),
            'samples': sum(int(r.get('samples', 1)) for r in group),
            'period': period,
            'bucket': key
        })
    return output


def compact(appid, records):
    # Preserve already aggregated records rather than averaging daily aggregates repeatedly.
    cutoff30 = NOW - timedelta(days=30)
    cutoff365 = NOW - timedelta(days=365)
    recent, daily, old = [], [], []
    for r in records:
        t = parse_time(r['timestamp'])
        if t >= cutoff30:
            recent.append(r)
        elif t >= cutoff365:
            daily.append(r)
        else:
            old.append(r)

    # Daily buckets can contain a mix of raw and pre-aggregated samples.
    daily_groups = defaultdict(list)
    for r in daily:
        daily_groups[parse_time(r['timestamp']).strftime('%Y-%m-%d')].append(r)
    daily_result = []
    for key, group in sorted(daily_groups.items()):
        n = sum(int(r.get('samples', 1)) for r in group)
        avg = round(sum(int(r['players']) * int(r.get('samples', 1)) for r in group) / n)
        latest = max(group, key=lambda r: parse_time(r['timestamp']))
        daily_result.append({
            'timestamp': latest['timestamp'], 'players': avg,
            'min': min(int(r.get('min', r['players'])) for r in group),
            'max': max(int(r.get('max', r['players'])) for r in group),
            'samples': n, 'period': 'day', 'bucket': key
        })

    if old:
        archive_path = ARCHIVE_DIR / f'{appid}.json'
        archived = load_json(archive_path, [])
        # Store monthly aggregates, including previously archived months.
        monthly_groups = defaultdict(list)
        for r in archived + old:
            key = r.get('bucket') if r.get('period') == 'month' else parse_time(r['timestamp']).strftime('%Y-%m')
            monthly_groups[key].append(r)
        monthly = []
        for key, group in sorted(monthly_groups.items()):
            n = sum(int(r.get('samples', 1)) for r in group)
            avg = round(sum(int(r['players']) * int(r.get('samples', 1)) for r in group) / n)
            latest = max(group, key=lambda r: parse_time(r['timestamp']))
            monthly.append({
                'timestamp': latest['timestamp'], 'players': avg,
                'min': min(int(r.get('min', r['players'])) for r in group),
                'max': max(int(r.get('max', r['players'])) for r in group),
                'samples': n, 'period': 'month', 'bucket': key
            })
        save_json(archive_path, monthly)

    return sorted(recent + daily_result, key=lambda r: parse_time(r['timestamp']))


def fetch(appid):
    url = ('https://api.steampowered.com/ISteamUserStats/'
           f'GetNumberOfCurrentPlayers/v1/?appid={appid}')
    request = urllib.request.Request(url, headers={'User-Agent': 'H1G-Steam-Players/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response).get('response', {})
    if payload.get('result') != 1:
        raise ValueError('Steam returned unsuccessful result')
    return int(payload['player_count'])


def main():
    games = load_json(Path('games.json'), [])
    ids = list(dict.fromkeys(int(g['appid']) for g in games))
    if not ids:
        raise SystemExit('No AppIDs in games.json')
    failures = []
    for index, appid in enumerate(ids, 1):
        try:
            players = fetch(appid)
            path = DATA_DIR / f'{appid}.json'
            history = load_json(path, [])
            history.append({'timestamp': datetime.now(UTC).isoformat(timespec='seconds'), 'players': players})
            save_json(path, compact(appid, history))
            print(f'[{index}/{len(ids)}] OK {appid}: {players}', flush=True)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError, OSError) as exc:
            failures.append(appid)
            print(f'[{index}/{len(ids)}] ERROR {appid}: {exc}', flush=True)
        if index < len(ids):
            time.sleep(2)
    print(f'Completed: {len(ids)-len(failures)} OK, {len(failures)} errors', flush=True)
    if failures:
        print('Failed AppIDs:', failures, flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
