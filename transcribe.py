"""Amplifi Creative OS — nightly ad transcriber (v2, layered source lookup).

Pulls every video ad from the Meta ad account, resolves each video's playable
file through three doors (ad-account video library, direct video read, page
access token), transcribes with faster-whisper, writes transcripts/<ad>.txt.

Env: META_TOKEN (required), AD_ACCOUNT, MAX_PER_RUN.
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

EXCLUDE = ["Lead Form", "FHL", "Refi", "Shop Rates", "Home Equity",
           "Book a Call", "Webinar Vid"]


def graph_get(path, token=None, **params):
    params["access_token"] = token or TOKEN
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def fetch_url(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def paginate(first):
    data = first
    while True:
        for row in data.get("data", []):
            yield row
        nxt = data.get("paging", {}).get("next")
        if not nxt:
            return
        data = fetch_url(nxt)


def all_ads():
    first = graph_get(
        f"{ACCOUNT}/ads",
        fields="name,effective_status,creative{video_id,effective_object_story_id}",
        limit=200)
    return list(paginate(first))


def advideo_sources():
    """Door 1: the ad account's own video library exposes source URLs."""
    out = {}
    try:
        first = graph_get(f"{ACCOUNT}/advideos", fields="id,source", limit=100)
        for v in paginate(first):
            if v.get("source"):
                out[v["id"]] = v["source"]
    except Exception as exc:
        print(f"note: advideos library unavailable ({exc})")
    return out


def page_tokens():
    """Door 3: per-page access tokens (needs pages_show_list on the token)."""
    out = {}
    try:
        data = graph_get("me/accounts", fields="id,access_token", limit=100)
        for p in data.get("data", []):
            if p.get("access_token"):
                out[p["id"]] = p["access_token"]
    except Exception as exc:
        print(f"note: no page tokens available ({exc})")
    return out


def resolve_source(video_id, page_id, adv_map, ptokens):
    if video_id in adv_map:
        return adv_map[video_id], "advideos"
    try:  # Door 2: direct read with the user token
        src = graph_get(video_id, fields="source").get("source")
        if src:
            return src, "direct"
    except Exception:
        pass
    if page_id and page_id in ptokens:  # Door 3
        try:
            src = graph_get(video_id, token=ptokens[page_id],
                            fields="source").get("source")
            if src:
                return src, "page-token"
        except Exception:
            pass
    return None, None


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:120]


def main():
    os.makedirs("transcripts", exist_ok=True)
    have = set(os.listdir("transcripts"))

    candidates = {}
    for ad in all_ads():
        name = ad.get("name", "")
        if not name or any(x in name for x in EXCLUDE):
            continue
        creative = ad.get("creative") or {}
        video_id = creative.get("video_id")
        if not video_id:
            continue
        story = creative.get("effective_object_story_id") or ""
        page_id = story.split("_")[0] if "_" in story else None
        status = ad.get("effective_status", "")
        if name not in candidates or status == "ACTIVE":
            candidates[name] = (video_id, page_id, status)

    todo = [(n, v, p, s) for n, (v, p, s) in candidates.items()
            if f"{safe(n)}.txt" not in have]
    todo.sort(key=lambda t: (t[3] != "ACTIVE", t[0]))

    adv_map = advideo_sources()
    ptokens = page_tokens()
    print(f"{len(candidates)} video ads in scope; {len(todo)} lack transcripts; "
          f"doing up to {MAX_PER_RUN}. "
          f"[library sources: {len(adv_map)} | page tokens: {len(ptokens)}]")

    if not todo:
        return

    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")

    ok = skipped = errs = 0
    for name, video_id, page_id, status in todo[:MAX_PER_RUN]:
        try:
            src, door = resolve_source(video_id, page_id, adv_map, ptokens)
            if not src:
                skipped += 1
                print(f"SKIP no-source: {name}")
                continue
            urllib.request.urlretrieve(src, "video.mp4")
            segments, info = model.transcribe("video.mp4", language="en")
            lines = [f"[{s.start:6.1f}s] {s.text.strip()}" for s in segments]
            header = (f"ad_name: {name}\n"
                      f"video_id: {video_id}\n"
                      f"status: {status}\n"
                      f"duration_seconds: {info.duration:.1f}\n"
                      f"source_door: {door}\n"
                      f"transcribed: {time.strftime('%Y-%m-%d')}\n---\n")
            with open(f"transcripts/{safe(name)}.txt", "w") as f:
                f.write(header + "\n".join(lines) + "\n")
            ok += 1
            print(f"OK ({door}) {info.duration:5.0f}s: {name}")
        except Exception as exc:
            errs += 1
            print(f"ERROR: {name}: {exc}")

    print(f"Done. {ok} transcribed, {skipped} no-source, {errs} errors.")


if __name__ == "__main__":
    main()
