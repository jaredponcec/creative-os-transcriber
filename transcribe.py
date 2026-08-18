"""Amplifi Creative OS — nightly ad transcriber.

Pulls every video ad from the Meta ad account, downloads each video's source
file, transcribes it locally with faster-whisper, and writes one text file per
ad into transcripts/. Ads that already have a transcript are skipped, so the
backlog drains across nightly runs (MAX_PER_RUN per night, actives first).

Runs inside GitHub Actions. Requires env: META_TOKEN (system-user token with
ads_read + pages_read_engagement). Optional env: AD_ACCOUNT, MAX_PER_RUN.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request

API = "https://graph.facebook.com/v23.0"
TOKEN = os.environ["META_TOKEN"]
ACCOUNT = os.environ.get("AD_ACCOUNT", "act_1505073096814143")
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "25"))

# Same scope rule as the Notion morning sync: Wealth Rewritten purchase engine.
EXCLUDE = ["Lead Form", "FHL", "Refi", "Shop Rates", "Home Equity",
           "Book a Call", "Webinar Vid"]


def graph_get(path, **params):
    params["access_token"] = TOKEN
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def fetch_url(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def all_ads():
    """Every ad in the account with its creative's video_id (paginated)."""
    ads = []
    data = graph_get(f"{ACCOUNT}/ads",
                     fields="name,effective_status,creative{video_id}",
                     limit=200)
    while True:
        ads.extend(data.get("data", []))
        nxt = data.get("paging", {}).get("next")
        if not nxt:
            return ads
        data = fetch_url(nxt)


def safe(name):
    """Ad name -> filesystem-safe filename (original name kept in file header)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:120]


def main():
    os.makedirs("transcripts", exist_ok=True)
    have = set(os.listdir("transcripts"))

    candidates = {}
    for ad in all_ads():
        name = ad.get("name", "")
        if not name or any(x in name for x in EXCLUDE):
            continue
        video_id = (ad.get("creative") or {}).get("video_id")
        if not video_id:
            continue  # static / carousel — no audio to transcribe
        status = ad.get("effective_status", "")
        # Copies share a name; keep one entry, prefer the ACTIVE instance.
        if name not in candidates or status == "ACTIVE":
            candidates[name] = (video_id, status)

    todo = [(n, v, s) for n, (v, s) in candidates.items()
            if f"{safe(n)}.txt" not in have]
    todo.sort(key=lambda t: (t[2] != "ACTIVE", t[0]))  # actives first
    print(f"{len(candidates)} video ads in scope; "
          f"{len(todo)} lack transcripts; doing up to {MAX_PER_RUN} this run.")

    if not todo:
        return

    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")

    ok = errs = 0
    for name, video_id, status in todo[:MAX_PER_RUN]:
        try:
            src = graph_get(video_id, fields="source").get("source")
            if not src:
                print(f"SKIP no-source: {name}")
                continue
            urllib.request.urlretrieve(src, "video.mp4")
            segments, info = model.transcribe("video.mp4", language="en")
            lines = [f"[{s.start:6.1f}s] {s.text.strip()}" for s in segments]
            header = (f"ad_name: {name}\n"
                      f"video_id: {video_id}\n"
                      f"status: {status}\n"
                      f"duration_seconds: {info.duration:.1f}\n"
                      f"transcribed: {time.strftime('%Y-%m-%d')}\n---\n")
            with open(f"transcripts/{safe(name)}.txt", "w") as f:
                f.write(header + "\n".join(lines) + "\n")
            ok += 1
            print(f"OK {info.duration:5.0f}s: {name}")
        except Exception as exc:  # keep the batch moving
            errs += 1
            print(f"ERROR: {name}: {exc}")

    print(f"Done. {ok} transcribed, {errs} errors.")


if __name__ == "__main__":
    main()
