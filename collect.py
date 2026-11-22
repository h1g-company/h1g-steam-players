
import json
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

# Steam AppID一覧
# 今後はここに追加するだけで収集対象を増やせます。
APP_IDS = [
    3841510,  # 真・三國無双2 with 猛将伝 Remastered
    1361350,  # DEAD OR ALIVE Xtreme Venus Vacation
    2860490,  # ワロタ、俺の家のとなり魔王城www
    4113810,  # ブループロトコル スターレゾナンス
    3259780,  # ファイナルファンタジー レゾナンス
    4017880,  # アノマリス
    3159330,  # アサシン クリード シャドウズ
    4910440,  # 華京夜探
    3259600,  # 紅の錬金術士と白の守護者
    3123410,  # ユミアのアトリエ
]

errors = []

for appid in dict.fromkeys(APP_IDS):
    try:
        url = (
            "https://api.steampowered.com/"
            "ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
            f"?appid={appid}"
        )

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "H1G-Steam-Players/1.0"}
        )

        with urllib.request.urlopen(
            request, timeout=20
        ) as response:
            result = json.load(response)["response"]

        if result.get("result") != 1:
            raise ValueError("Steam API returned an error")

        players = int(result["player_count"])
        timestamp = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )

        path = Path("data") / f"{appid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        history = []
        if path.exists():
            history = json.loads(
                path.read_text(encoding="utf-8")
            )

        history.append({
            "timestamp": timestamp,
            "players": players
        })

        path.write_text(
            json.dumps(
                history, ensure_ascii=False, indent=2
            ) + "\n",
            encoding="utf-8"
        )

        print(f"OK {appid}: {players:,} players")

    except Exception as error:
        print(f"ERROR {appid}: {error}")
        errors.append(appid)

    # Steam APIへの連続アクセスを避ける
    time.sleep(2)

print(
    f"Finished: {len(APP_IDS) - len(errors)} success, "
    f"{len(errors)} errors"
)

if errors:
    print("Failed AppIDs:", errors)
    raise SystemExit(1)
