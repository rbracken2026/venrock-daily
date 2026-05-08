# Venrock Daily

Automated morning audio briefings for Venrock investors, hosted on GitHub Pages and playable in any podcast app.

Each briefing: fetches news → curates with Claude → writes a spoken script → generates MP3 via OpenAI TTS → publishes to a personal RSS feed.

**~$0.10–0.18/episode** (Claude curation ~$0.04, script ~$0.03, TTS ~$0.07–0.11 depending on length).

---

## Quick start

### 1. Prerequisites

| Secret | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `AZURE_SPEECH_REGION` | Region slug of your Speech resource, e.g. `eastus` |
| `AZURE_SPEECH_RESOURCE_ID` | ARM path: `/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{name}` |
| `M365_CLIENT_ID` | Azure app registration client ID (shared with Outlook) |
| `M365_CLIENT_SECRET` | Azure app registration client secret |
| `M365_TENANT_ID` | Azure tenant ID |
| `GITHUB_TOKEN` | Built-in to Actions — no setup needed |

Add the first two as **repository secrets** (`Settings → Secrets and variables → Actions`).

GitHub Pages must be enabled on the repo: `Settings → Pages → Deploy from branch → main / (root)`.

### 2. Add your config

Visit the **[Build Your Briefing wizard](web/build.html)** (or open `web/build.html` locally), fill in the form, and download your YAML. Save it as `configs/<your-id>.yaml` and open a PR.

Or copy `configs/racquel.yaml` as a starting point and edit directly.

### 3. Initialize your feed (once per person)

```bash
pip install -r requirements.txt

export GITHUB_TOKEN=ghp_...
export GITHUB_REPO=rbracken2026/venrock-daily

python briefing.py --config configs/racquel.yaml --init-show
```

This creates `shows/racquel/feed.xml` and `shows/racquel/episodes/` in the repo.

### 4. Run manually (dry run first)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export AZURE_SPEECH_REGION=eastus
export AZURE_SPEECH_RESOURCE_ID=/subscriptions/.../accounts/my-speech
export M365_CLIENT_ID=...
export M365_CLIENT_SECRET=...
export M365_TENANT_ID=...

# Preview script without TTS or upload
python briefing.py --config configs/racquel.yaml --dry-run

# Full run
python briefing.py --config configs/racquel.yaml
```

### 5. Subscribe

Your RSS feed will be live at:
```
https://rbracken2026.github.io/venrock-daily/shows/<your-id>/feed.xml
```

Paste this URL into Apple Podcasts, Overcast, Pocket Casts, or any podcast app.

---

## Automated delivery

The GitHub Actions workflow (`.github/workflows/briefing.yml`) runs every weekday at **7:00 AM PT** (14:00 UTC). It automatically discovers every `.yaml` file in `configs/` and runs one job per person.

To trigger manually: `Actions → Venrock Daily Briefing → Run workflow`.

---

## Enabling Outlook sources (pending IT approval)

All `outlook:` sources in the YAML default to `active: false`. Once IT approves the Microsoft 365 app registration:

1. Add `M365_CLIENT_ID`, `M365_CLIENT_SECRET`, `M365_TENANT_ID` as repo secrets
2. Flip `active: false` → `active: true` on the relevant source in your YAML

No code changes needed.

---

## Repo structure

```
venrock-daily/
├── .github/workflows/briefing.yml   # weekday cron, matrix over configs/
├── configs/racquel.yaml             # one file per person
├── pipeline/
│   ├── config.py                    # Pydantic models
│   ├── fetcher/                     # rss · scraper · outlook (feature-flagged)
│   ├── curator.py                   # Claude scoring + filtering
│   ├── scripter.py                  # Claude spoken script
│   ├── tts.py                       # OpenAI tts-1-hd chunked
│   ├── uploader.py                  # GitHub Contents API
│   └── feed.py                      # feed.xml initializer
├── briefing.py                      # CLI entrypoint
├── web/
│   ├── index.html                   # team directory (GitHub Pages)
│   └── build.html                   # "build your own" wizard
├── shows/                           # feed.xml + episodes/ per person
├── feeds.json                       # directory manifest
└── tests/
```

## Running tests

```bash
pip install -r requirements.txt
pytest
```
