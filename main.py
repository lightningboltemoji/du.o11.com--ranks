import json
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://fn-service-habanero-live-public.ogs.live.on.epicgames.com/api/v1"
TOKEN_URL = (
    "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
)
DEVICE_AUTH_PATH = Path(__file__).parent / ".device_auth.json"
RANKS_PATH = Path(__file__).parent / "ranks.json"

# fortnitePCGameClient — supports authorization_code grant
PC_CLIENT_ID = "ec684b8c687f479fadea3cb2ad83f5c6"
PC_CLIENT_SECRET = "e1f31c211f28413186262d37a13fc84d"

# fortniteAndroidGameClient — has deviceAuths CREATE permission
ANDROID_CLIENT_ID = "3f69e56c7649492c8cc29f1af08a8a12"
ANDROID_CLIENT_SECRET = "b51ee9cb12234f50a69efa67ef53812e"

AUTH_CODE_URL = (
    "https://www.epicgames.com/id/api/redirect"
    f"?clientId={PC_CLIENT_ID}&responseType=code"
)

PLAYERS = {
    "dimes": "f9709bd541154cbfbe0329db46e0b35a",
    "demon": "aba206e21d7a4a81bc93a1762bf70c81",
}

# Division names for Fortnite ranked (0-indexed, 18 total divisions)
DIVISIONS = [
    "Bronze I",
    "Bronze II",
    "Bronze III",
    "Silver I",
    "Silver II",
    "Silver III",
    "Gold I",
    "Gold II",
    "Gold III",
    "Platinum I",
    "Platinum II",
    "Platinum III",
    "Diamond I",
    "Diamond II",
    "Diamond III",
    "Elite",
    "Champion",
    "Unreal",
]


def _token_request(client_id: str, client_secret: str, **data) -> dict:
    """Make a token request and return the full JSON response."""
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=(client_id, client_secret),
        data=data,
    )
    if not resp.ok:
        print(f"Token error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    return resp.json()


def _get_exchange_code(access_token: str) -> str:
    """Get an exchange code from an existing session."""
    resp = requests.get(
        "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/exchange",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if not resp.ok:
        print(f"Exchange code error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    return resp.json()["code"]


def _save_device_auth(device_auth: dict) -> None:
    DEVICE_AUTH_PATH.write_text(json.dumps(device_auth, indent=2))
    print(f"Device auth saved to {DEVICE_AUTH_PATH}")


def _load_device_auth() -> dict | None:
    if DEVICE_AUTH_PATH.exists():
        return json.loads(DEVICE_AUTH_PATH.read_text())
    return None


def _create_device_auth(access_token: str, account_id: str) -> dict:
    """Create device auth credentials for persistent login."""
    url = (
        f"https://account-public-service-prod.ol.epicgames.com"
        f"/account/api/public/account/{account_id}/deviceAuth"
    )
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if not resp.ok:
        print(f"Device auth creation error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    data = resp.json()
    return {
        "account_id": data["accountId"],
        "device_id": data["deviceId"],
        "secret": data["secret"],
    }


def authenticate() -> str:
    """Authenticate and return an access token, using device auth if available."""
    device_auth = _load_device_auth()

    if device_auth:
        print("Using saved device auth credentials...")
        try:
            token_data = _token_request(
                ANDROID_CLIENT_ID,
                ANDROID_CLIENT_SECRET,
                grant_type="device_auth",
                account_id=device_auth["account_id"],
                device_id=device_auth["device_id"],
                secret=device_auth["secret"],
            )
            print("Authenticated successfully.\n")
            return token_data["access_token"]
        except requests.HTTPError:
            print(
                "Device auth failed (password changed?). Falling back to auth code.\n"
            )

    # First-time setup: use authorization code with PC client
    auth_code = input(
        f"Enter your Epic Games authorization code\n(get one at: {AUTH_CODE_URL})\n> "
    )

    print("\nExchanging auth code for access token...")
    pc_token_data = _token_request(
        PC_CLIENT_ID,
        PC_CLIENT_SECRET,
        grant_type="authorization_code",
        code=auth_code.strip(),
    )
    print("Authenticated with PC client.")

    # Exchange to Android client (which has deviceAuths CREATE permission)
    print("Getting exchange code...")
    exchange_code = _get_exchange_code(pc_token_data["access_token"])

    print("Exchanging to Android client...")
    android_token_data = _token_request(
        ANDROID_CLIENT_ID,
        ANDROID_CLIENT_SECRET,
        grant_type="exchange_code",
        exchange_code=exchange_code,
    )
    access_token = android_token_data["access_token"]
    account_id = android_token_data["account_id"]
    print("Authenticated with Android client.")

    # Create and save device auth for future runs
    print("Creating device auth for persistent login...")
    device_auth = _create_device_auth(access_token, account_id)
    _save_device_auth(device_auth)
    print()

    return access_token


def get_current_track_guid(access_token: str, ranking_type: str) -> str | None:
    """Find the trackguid for the current active season."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"{BASE_URL}/games/fortnite/tracks/query"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"rankingType": ranking_type, "endsAfter": now},
    )
    resp.raise_for_status()
    tracks = resp.json()
    # Return the track whose beginTime is in the past (i.e. currently active)
    for track in tracks:
        if track["beginTime"] <= now:
            return track["trackguid"]
    return None


def get_current_zero_build_rank(
    access_token: str, account_id: str, trackguid: str
) -> dict | None:
    """Fetch current season zero build progress for an account."""
    url = f"{BASE_URL}/games/fortnite/trackprogress/{account_id}/byTrack/{trackguid}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def division_name(division: int) -> str:
    return DIVISIONS[division] if division < len(DIVISIONS) else f"Division {division}"


def append_snapshot(snapshot: dict, trackguid: str) -> None:
    """Append a snapshot to the ranks JSON file.

    Format: {"dimes": {"<trackguid>": {"timestamps": [...], "ranks": [...]}}, ...}
    """
    if RANKS_PATH.exists():
        data = json.loads(RANKS_PATH.read_text())
    else:
        data = {}

    for name, (timestamp, rank) in snapshot.items():
        player = data.setdefault(name, {})
        entry = player.setdefault(trackguid, {"timestamps": [], "ranks": []})
        entry["timestamps"].append(timestamp)
        entry["ranks"].append(rank)

    RANKS_PATH.write_text(json.dumps(data, separators=(",", ":")) + "\n")


def main():
    access_token = authenticate()

    print("Finding current zero build season...")
    trackguid = get_current_track_guid(access_token, "ranked-br-combined")
    if not trackguid:
        print("No active zero build season found.")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = {}

    for name, account_id in PLAYERS.items():
        print(f"Fetching rank for {name} ({account_id})...")
        progress = get_current_zero_build_rank(access_token, account_id, trackguid)

        if progress is None:
            print(f"  No zero build ranking found for {name}.")
            continue

        div = division_name(progress["currentDivision"])
        numeric_rank = progress.get("currentPlayerRanking")
        if numeric_rank is not None:
            rank_value = [div, numeric_rank]
        else:
            pct = round(progress["promotionProgress"] * 100)
            rank_value = [div, pct]
        snapshot[name] = (now, rank_value)

        # Print to console
        if numeric_rank is not None:
            print(f"  {div} (#{numeric_rank:,})")
        else:
            print(f"  {div} ({pct}% to next)")

    append_snapshot(snapshot, trackguid)
    print(f"\nSnapshot saved to {RANKS_PATH}")


if __name__ == "__main__":
    main()
