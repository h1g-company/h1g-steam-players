
import json
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

# 対象ゲーム。将来はここにAppIDを追加できます。
APP_IDS = [3841510]

for appid in APP_IDS:
    url = (
        "https://api.steampowered.com/"
        "ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
        f"?appid={appid}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "H1G-Steam-Players/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)["response"]

    if result.get("result") != 1:
        raise RuntimeError(f"Steam API error: {appid}")

    players = int(result["player_count"])
    timestamp = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    path = Path("data") / f"{appid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    history = []
    if path.exists():
        history = json.loads(path.read_text(encoding="utf-8"))

    history.append({
        "timestamp": timestamp,
        "players": players
    })

    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print(f"AppID {appid}: {players:,} players")
