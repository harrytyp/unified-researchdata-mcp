# NOMAD Oasis: Cross-User Access with an Admin PAT (Service Account)

How the TGA pipeline gives a single PAT access to **all uploads of all
users** on the NOMAD Oasis, so the operator app can download every `.tprc`
and upload results back. This documents what was done on
`researchmcp.duckdns.org` and how to reproduce it on a fresh install.

## The problem

NOMAD Oasis restricts upload visibility per user:

- The upload **list** endpoint (`GET /api/v1/uploads`) filters by the user's
  roles (`main_author`, `coauthor`, `reviewer`) — even **admins** only see
  their own uploads in the list (verified in `get_role_query`).
- The **single-upload** endpoint (`GET /api/v1/uploads/{id}`) does honor
  admin rights (`is_user_upload_viewer` → `user.is_admin` → allow).

So a non-admin PAT sees only its own uploads; an admin PAT can fetch any
upload by ID but still gets an empty list.

## What was set up (3 parts)

### 1. Admin user via `nomad.yaml` (`services.admin_user_id`)

NOMAD derives admin status locally — no central Keycloak needed:

```python
# nomad/configs/nomad.yaml
services:
  api_host: "localhost"
  api_base_path: "/nomad-oasis"
  upload_limit: 100
  admin_user_id: "41875c3d-785d-4c2f-a7f5-1c81e6290276"   # kolja.knodel
```

The user whose `user_id` matches `services.admin_user_id` gets
`User.is_admin = True` (derived property — verified). This grants full
read/write access to **every upload by ID** and to all entries.

### 2. `tga-operators` user group on all uploads (`coauthor_groups`)

Because the upload **list** used to ignore admin, the operator had to appear
as coauthor on the uploads — a user group is the scalable way. **Since the
2026-08-13 admin fix** (`plugins/patch_uploads_admin.sh`) admins see ALL
uploads regardless of roles; the group is still needed for NON-admin PATs
with group membership and for auto-sharing from `instrument_data/processor.py`.

> **WICHTIG (Bug-Fix 2026-08-13):** The group document MUST be schema-conform —
> with `group_id` (the primary-key field!), `owner` and `members_info`.
> Without `group_id`, `MongoUserGroup.get_ids_by_user_id()` does not return
> the group (the code reads `group.group_id`), which drops every upload that
> is only visible via the group — AND the groups serialization crashes with
> HTTP 500 in the UI (required `members_info`/`owner` missing).

```python
# In MongoDB (nomad_oasis_v1), via mongosh:
# 1. Create the group schema-conform (STRING _id; group_id = same string;
#    owner = operator user_id; members_info = [{user_id, role}]):
db.user_group.insertOne({
    _id: "tga-operators-<random>",
    group_id: "tga-operators-<random>",           # REQUIRED (primary-key field)
    group_name: "tga-operators",
    owner: "41875c3d-785d-4c2f-a7f5-1c81e6290276",   # operator user_id
    members: ["41875c3d-785d-4c2f-a7f5-1c81e6290276"],
    members_info: [{"user_id": "41875c3d-785d-4c2f-a7f5-1c81e6290276", "role": "owner"}],
    created: new Date()
})

# 2. Attach the group to every upload (existing + future):
db.upload.updateMany({}, { $addToSet: { coauthor_groups: "tga-operators-<random>" } })
```

Then `MongoUserGroup.get_ids_by_user_id(user_id)` returns the group id, the
role query matches `coauthor_groups`, and the list endpoint shows all uploads
for NON-admin PATs with group membership.

> **Admin-PAT (empfohlen):** `plugins/patch_uploads_admin.sh` (invoked by
> `plugins/startup.sh` on every container start) patches `get_role_query`
> so that admins (`is_admin: True`) see ALL uploads — independent of roles
> or groups. Verify: `GET /uploads` with the admin PAT returns all uploads
> (pagination `total` = row count in DB), paged via `page_after_value`
> (page_size is capped at 10; `per_page` is ignored).

### 3. PAT scopes

The PAT used by the app needs these scopes (created/extended in
`db.personal_access_tokens` or via the GUI Settings → API Tokens):

```
uploads:read, uploads:write, uploads:process, entries:read, entries:write,
schemas:read, metainfo:read, info:read
```

`uploads:process` is required to trigger `POST /api/v1/uploads/{id}/action/process`
after a result file is uploaded (403 without it — verified).

## How to reproduce on a fresh install

1. **Create the operator account** — the Oasis uses central user management
   (`uses_central_user_management: true`), so the operator registers/logs in
   via the central NOMAD (nomad-lab.eu). Local account creation is not
   possible. Find their `user_id` (e.g. from an upload's
   `entry_metadata.main_author.user_id`, or via the admin in the GUI).
2. **Set `services.admin_user_id`** in `nomad/configs/nomad.yaml` to that
   `user_id`, then restart the app container.
   ⚠️ After changing `admin_user_id`, **restart the app container** — the
   `User` cache (TTL 24h) otherwise keeps the old `is_admin` value and the
   first API call still 401s.
3. **Create the group + attach it** (see MongoDB snippet above). Use a
   **string** `_id` — an ObjectId id breaks `UploadProcData` validation
   ("Input should be a valid string"). Re-run the `updateMany` for new
   uploads, or make it part of the schema/processing setup.
4. **Create the PAT** with the container recipe in the last section of this
   document - there is neither a GUI page nor a `nomad admin token`
   subcommand in 1.4.2. To widen an existing token instead:
   `$addToSet: { scopes: "uploads:process" }` in `db.personal_access_tokens`.
5. Store the PAT only in `nomad/.env` (gitignored) — never commit it.

## Pitfalls encountered

| Symptom | Cause | Fix |
|---|---|---|
| `GET /uploads` returns 0 despite admin | list ignores `is_admin` | coauthor group (step 2) |
| `GET /uploads/{id}` → 401 right after config change | 24h user cache | restart app container |
| 500 "validation errors for UploadProcData, coauthor_groups.0" | group `_id` is ObjectId | use string group id |
| `POST .../action/process` → 403 "Missing scopes: uploads:process" | PAT lacks scope | add scope to token |
| `GET /users/{user_id}` → 403 | PAT lacks `users:read` | not needed — names come from `entry_metadata.main_author.name` |

## Reference

- App: `tga/src/tga_nomad_app.pyw` (`NomadClient`, `_author_name`,
  `_refresh_worker`)
- API: `nomad/app/v1/routers/uploads.py` — `get_role_query`,
  `is_user_upload_writer`, `is_user_upload_viewer`
- Group model: `nomad/mongo/groups.py` — `MongoUserGroup`

## Creating a PAT: neither the GUI nor the CLI can do it (verified 2026-11-03)

What is NOT available on this deployment:

- `nomad admin` has no `token` subcommand (`nomad admin token --help` -> "No such
  command"). Its only user command is `users import` (Keycloak import).
- The GUI has no API-token page, so step 4 above is wrong for NOMAD 1.4.2 - do
  not send anyone to "Settings -> API Tokens".
- `POST /api/v1/auth/pats` exists, but it requires a real Keycloak session with
  the `tokens:create` scope; a PAT cannot mint another PAT.

What a PAT is: `nomad_pat_` + `secrets.token_urlsafe(32)` (53 chars), stored
**only** as a sha256 hex digest in `personal_access_tokens`
(`nomad/mongo/pat.py`, `nomad/auth/tokens.py:create_pat`). The raw value exists
exactly once, in the return value of the creating call, so it has to be captured
then - it can never be read back out of the database.

### Recipe (run inside the app container)

```python
# /tmp/mint_pat.py, executed with /opt/venv/bin/python inside nomad_oasis_app
from nomad.infrastructure import setup_mongo   # required: a bare process has no mongo connection
setup_mongo()
from nomad.auth.tokens import PATMetadata, create_pat

res = create_pat(
    user_id='<user_id>',
    metadata=PATMetadata(name='tga-operator-<lab>', scopes=[
        'uploads:read', 'uploads:write', 'uploads:process', 'entries:read']),
    expires_in_days=365,
)
open('/tmp/pat.txt', 'w').write(res.raw_token)   # to a file, never to stdout
```

```bash
docker cp /tmp/mint_pat.py nomad_oasis_app:/tmp/mint_pat.py
docker exec nomad_oasis_app /opt/venv/bin/python /tmp/mint_pat.py
docker exec nomad_oasis_app cat /tmp/pat.txt      # only to move it into the app config
```

`create_pat` enforces `config.auth.pat_max_lifetime` and
`pat_max_active_per_user` and rejects `tokens:*` scopes, so prefer it over
inserting a digest by hand. A manual insert is
`db.personal_access_tokens.insertOne({user_id, name, token_digest: <sha256 hex>,
scopes: [...], revoked: false, created_at: new Date()})` - no expiry unless
`expired_at` is set, and no validation at all.

### Making a PAT see the TGA uploads (tga-operators)

Two independent things have to hold; the second is the one that fails in practice:

1. **The upload carries the group** in `coauthor_groups`
   (`tga-operators-6a7ae5e4cec5e87bf39df8a3`). Measured 2026-11-03: 29 of the 33
   uploads that hold a `.tprc` had it, 4 did not, and 8 uploads of other users
   never appear for a non-admin operator at all.
2. **The PAT's user is a member** of that group:

```javascript
// mongosh nomad_oasis_v1
const u = '<operator user_id>';
db.user_group.updateOne({group_name: 'tga-operators'},
  {$addToSet: {members: u, members_info: {user_id: u, role: 'member'}}});
```

Measured effect, same PAT, no app restart needed: visible uploads 18 -> 43, TGA
uploads 8 -> 31 (of 37 known `.tprc` upload ids). Reads work end to end:
`GET /uploads/{id}/rawdir/` lists `*.tprc`, `GET /uploads/{id}/raw/<name>`
downloads it; `PUT /uploads/{id}/raw/<name>?file_name=<name>` with
`Content-Type: application/octet-stream` and `POST /uploads/{id}/action/process`
both answer 200. An admin PAT sees all 51 uploads; a group-less non-admin PAT
sees its own 18.

### Pitfalls found while testing

| Symptom | Cause | Fix |
|---|---|---|
| "You have not defined a default connection" | bare python process, no mongo init | call `nomad.infrastructure.setup_mongo()` first |
| PAT answers 401 everywhere | value mangled by shell quoting, or the digest belongs to a revoked token | mint a new one; the raw value is unrecoverable |
| `GET /uploads/{id}` -> "No matching upload found" | `db.entry.upload_id` can point at an already deleted upload; the API id is `db.upload._id` (22 chars) | resolve ids through the API, not through entries |
| Group member sees no new uploads | the upload lacks `coauthor_groups` | attach the group (the share step in `processor.py`) |
| worker log: "Could not share upload ... HTTP 400 `'NoneType' object has no attribute 'is_blocking'`" | `POST /uploads/{id}/edit` with `metadata.coauthor_groups` hits a NOMAD 1.4.2 bug when the upload has no current process | attach the group in mongosh, or retry the edit once the upload is processed |
