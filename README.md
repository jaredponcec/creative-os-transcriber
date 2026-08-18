# Amplifi Creative OS — Ad Transcriber

Nightly robot: pulls every video ad from the Amplifi2 Meta ad account,
downloads each video, transcribes it with Whisper, and saves one text file per
ad in `transcripts/`. Claude's Creative OS sync reads those files and writes
transcripts + auto-tags onto the Notion cards.

## One-time setup

1. **Create this repo** (private) on GitHub and upload these files, keeping the
   folder structure (`.github/workflows/transcribe.yml` must keep its path).
2. **Add the token**: repo → Settings → Secrets and variables → Actions →
   New repository secret. Name: `META_TOKEN`. Value: the Meta system-user
   token (scopes: ads_read, pages_read_engagement).
3. **Enable workflows**: Actions tab → enable if prompted.
4. **First run**: Actions → transcribe-ads → Run workflow. Each run processes
   up to 25 ads (~30–60 min); re-run until the backlog is drained, then the
   nightly schedule keeps up on its own.

## Notes

- The token is read-only. Revoke it anytime in Business Manager →
  System users.
- Ads with no video (statics) and lead-gen funnels are skipped automatically.
- Transcript files carry the exact ad name in their header — the Notion sync
  matches on that, so filenames never need human attention.
- To re-transcribe an ad, delete its file in `transcripts/` and re-run.
