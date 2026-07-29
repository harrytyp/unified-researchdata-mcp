# elabFTW Connection Guide

## Connecting Your elabFTW Instance to NOMAD

This guide covers both integration methods: offline (file export) and online (API).

---

## 1. Offline Method — ELN Archive Export

No API configuration needed. This works with any elabFTW instance.

### In elabFTW

1. Open the experiment you want to export
2. Go to **More → Export → ELN Archive**
3. Save the `.eln` file to your computer
4. (Optional) If you have multiple experiments, zip them together

### In NOMAD

1. Go to **PUBLISH → Uploads**
2. Click **CREATE A NEW UPLOAD**
3. Drag-and-drop the `.eln` file(s) into the upload area
4. NOMAD auto-detects the RO-Crate format and parses each experiment
5. Each experiment becomes a separate entry with:

```
Upload
├── Entry: "Experiment 1"           ← auto-named from elabFTW title
│   ├── ELabFTW Project Import      ← schema section
│   │   ├── Experiment Data
│   │   │   ├── body (rich text)
│   │   │   ├── tags
│   │   │   ├── extra_fields
│   │   │   ├── steps
│   │   │   └── experiments_links   ← cross-references
│   │   └── Experiment Files
│   │       ├── File "attachment1.pdf"
│   │       └── File "data.csv"
│   └── metadata.external_id        ← set from elabFTW URL
├── Entry: "Experiment 2"
└── ...
```

### Cross-Referencing

When experiments in elabFTW reference each other (via links), the parser
sets `metadata.external_id` on each entry. During normalization, NOMAD
searches for matching `external_id` values across all entries and creates
internal links (`../uploads/{id}/archive/{id}#data`).

This means experiments linked in elabFTW become linked in NOMAD automatically.

---

## 2. Online Method — API Configuration

### Prerequisites

- elabFTW instance with API access enabled
- An API token from the elabFTW instance
- Network connectivity from the NOMAD Oasis server to the elabFTW instance

### Getting an elabFTW API Token

Each user needs their own token. **Do not share tokens.**

1. Log into your elabFTW instance (e.g. `https://elntest.ub.tum.de`)
2. Go to **My Account → API tokens**
3. Click **Add an API key**
4. Give it a descriptive name (e.g. `nomad-sync`)
5. **Copy the token immediately** — it's only shown once
6. Token format: `72-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

### Testing the API Connection

From the NOMAD Oasis server:

```bash
# Test basic connectivity
curl -s -H "Authorization: Bearer YOUR_TOKEN" \
  "https://your-elabftw-instance/api/v2/me" | head -5

# List experiments
curl -s -H "Authorization: Bearer YOUR_TOKEN" \
  "https://your-elabftw-instance/api/v2/experiments?limit=5" | head -20
```

**Expected response from `/me`** — JSON with your user info.
**Expected response from `/experiments`** — JSON array of experiments.

### ❗ API Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` | Wrong token or missing `72-` prefix | Check token format |
| `404 Not Found` | Wrong API endpoint | Try `/api/v1/` vs `/api/v2/` |
| `Connection refused` | Server can't reach elabFTW | Check firewall/DNS |
| `SSL certificate error` | Self-signed cert on elabFTW | Add `--insecure` for testing, fix cert for production |

---

## 3. Network Requirements

The NOMAD app container must be able to reach your elabFTW API endpoint.

```
NOMAD Oasis (Docker) ──HTTPS──► your-elabftw-instance.com
  app:8000                         /api/v2/experiments/{id}
```

If your elabFTW instance is behind a VPN or firewall, ensure the NOMAD
server's IP is whitelisted.

### Testing from Inside the Container

```bash
docker exec nomad_oasis_app curl -s -o /dev/null -w "%{http_code}" \
  https://your-elabftw-instance/api/v2/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```
