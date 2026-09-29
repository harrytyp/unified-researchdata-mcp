"""The read-only NOMAD tools.

Every tool maps onto one endpoint of NOMAD's OpenAPI document. They are
annotated ``read_only_hint``, so a client that honours the annotations can
offer them without asking, and they carry an explicit title and description —
what a model sees is what the endpoint does.
"""

import json
import logging
import time
from collections import defaultdict, deque
from typing import Annotated, Any
from urllib.parse import quote

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import auth, client
from .config import settings

log = logging.getLogger("nomad_mcp.server")
audit = logging.getLogger("nomad_mcp.audit")


class NomadMCPServer(MCPServer):
    """An MCPServer that only shows a caller the tools its token carries."""

    async def list_tools(self):  # type: ignore[override]
        tools = await super().list_tools()
        return [tool for tool in tools if auth.allowed(tool.name)]


mcp = NomadMCPServer(
    name="nomad",
    title="NOMAD",
    version="0.1.0",
    instructions=(
        "Read-only access to NOMAD, the materials-science data platform. "
        "Search published entries, read an entry's archive, browse uploads "
        "and datasets of the signed-in account, look up metainfo definitions "
        "and schemas, and fetch crystal structures. Nothing here changes data."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)

# ── call bookkeeping ────────────────────────────────────────────────────────

_calls: dict[str, deque[float]] = defaultdict(deque)


def _throttle(credential: auth.Credential) -> None:
    """A simple per-credential ceiling; the credential itself is never stored."""
    if settings.rate_limit <= 0:
        return
    key = f"{credential.origin}:{hash(credential.api_key)}"
    window = _calls[key]
    now = time.monotonic()
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.rate_limit:
        raise ToolError(
            f"Rate limit reached ({settings.rate_limit} calls per minute). "
            "Wait a moment and try again."
        )
    window.append(now)


def _bounded(data: Any, hint: str = "") -> Any:
    """Keep a response inside what a model can actually read."""
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= settings.max_response_chars:
        return data
    note = (
        f"The response was {len(text)} characters and was cut to "
        f"{settings.max_response_chars}. Ask for fewer fields or a smaller page."
    )
    if hint:
        note = f"{note} {hint}"
    return {
        "truncated": True,
        "note": note,
        "preview": text[: settings.max_response_chars],
    }


async def _call(
    tool_name: str,
    path: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    hint: str = "",
    bound: bool = True,
) -> Any:
    """Authorise, throttle, call, bound, and audit — in that order."""
    if not auth.allowed(tool_name):
        raise ToolError(
            f"This token does not include the '{tool_name}' tool. "
            "Register again and select it."
        )
    credential = auth.resolve()
    _throttle(credential)
    started = time.monotonic()
    try:
        data = await client.request(
            method,
            path,
            base_url=credential.base_url,
            api_key=credential.api_key,
            params=params,
            body=body,
        )
    except client.NomadError as exc:
        audit.info(
            "tool=%s origin=%s status=%s ms=%d",
            tool_name,
            credential.origin,
            exc.status,
            (time.monotonic() - started) * 1000,
        )
        if exc.status in (401, 403):
            scope_hint = (
                " This credential's scopes do not cover that endpoint — the "
                "deployment's own read-only key is limited on purpose; register "
                "a token with your own NOMAD API key for your account's data."
                if exc.status == 403
                else " The credential may have expired — register a token with "
                "your own NOMAD API key."
            )
            raise ToolError(
                f"NOMAD refused this request ({exc.status}): {exc}.{scope_hint}"
            ) from exc
        raise ToolError(f"NOMAD answered {exc.status}: {exc}") from exc
    audit.info(
        "tool=%s origin=%s status=200 ms=%d",
        tool_name,
        credential.origin,
        (time.monotonic() - started) * 1000,
    )
    return _bounded(data, hint) if bound else data


# ── entries ─────────────────────────────────────────────────────────────────

ENTRY_QUERY_HINT = (
    "Narrow 'fields' to keep the answer small; add 'results.*' only when you "
    "need the computed values."
)

# What a search returns unless the caller asks for more: the identifiers, not
# the results tree. A full entry is tens of thousands of characters.
COMPACT_FIELDS: list[str] = [
    "entry_id",
    "upload_id",
    "entry_name",
    "upload_name",
    "entry_type",
    "mainfile",
    "parser_name",
    "published",
    "upload_create_time",
]


@mcp.tool(
    title="Search NOMAD entries",
    description=(
        "Search entries in NOMAD and return their metadata. This is the main "
        "way in: the query language is NOMAD's own (see the search-entries "
        "documentation). Returns 'pagination.total', the number of matching "
        "entries, together with one page of results."
    ),
    annotations=READ_ONLY,
)
async def search_entries(
    ctx: Context,
    query: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "NOMAD search query, e.g. {\"results.method.simulation."
                "program_name\": \"VASP\"} or {\"and\": [{\"results.material."
                "elements\": \"Ti\"}, {\"results.material.elements\": \"O\"}]}. "
                "Empty returns everything."
            )
        ),
    ] = None,
    owner: Annotated[
        str,
        Field(
            description=(
                "Whose entries: 'visible' (default — public plus what the "
                "credential may see), 'public', 'user' (only this account's), "
                "or 'all'."
            )
        ),
    ] = "visible",
    page_size: Annotated[
        int, Field(description="Entries per page.", ge=1, le=100)
    ] = 10,
    page_after_value: Annotated[
        str,
        Field(description="Cursor from the previous page's pagination.next_page_after_value."),
    ] = "",
    fields: Annotated[
        list[str] | None,
        Field(
            description=(
                "Which quantities to return, e.g. ['entry_id', 'results.material."
                "elements']. Defaults to the identifiers only (entry_id, "
                "upload_id, entry_name, upload_name, entry_type, mainfile, "
                "parser_name, published, upload_create_time). Add 'results.*' "
                "when you need computed values — it makes each entry large."
            )
        ),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        Field(description="Quantities to leave out, e.g. ['quantities', 'sections']."),
    ] = None,
) -> Any:
    """Search entries and retrieve their metadata."""
    selection: dict[str, Any] = {}
    if fields:
        selection["include"] = fields
    else:
        selection["include"] = COMPACT_FIELDS
    if exclude:
        selection["exclude"] = exclude
    body: dict[str, Any] = {
        "owner": owner or "visible",
        "query": query if query else {},
        "pagination": {
            "page_size": page_size,
            **({"page_after_value": page_after_value} if page_after_value else {}),
        },
        "required": selection,
    }
    return await _call("search_entries", "/entries/query", method="POST", body=body, hint=ENTRY_QUERY_HINT)


@mcp.tool(
    title="Get one entry",
    description="Read the metadata of a single entry by its entry id.",
    annotations=READ_ONLY,
)
async def get_entry(
    ctx: Context,
    entry_id: Annotated[str, Field(description="The entry id, as returned by search_entries.")],
) -> Any:
    """Get the metadata of an entry by its id."""
    return await _call("get_entry", f"/entries/{entry_id}")


@mcp.tool(
    title="Read an entry's archive",
    description=(
        "The full processed archive of an entry: the complete metainfo tree "
        "with all results of the calculation or measurement. Large — search "
        "first, then read the archive of the entry you need."
    ),
    annotations=READ_ONLY,
)
async def get_entry_archive(
    ctx: Context,
    entry_id: Annotated[str, Field(description="The entry id.")],
) -> Any:
    """Get the archive for an entry by its id."""
    return await _call(
        "get_entry_archive",
        f"/entries/{entry_id}/archive",
        hint="Use search_entries with 'required' to get the same numbers without the tree.",
    )


# ── uploads ─────────────────────────────────────────────────────────────────

UPLOAD_QUERY_HINT = (
    "NOMAD fixes the upload page size at 10; pass pagination.next_page_after_value "
    "as page_after_value to walk the rest."
)


@mcp.tool(
    title="List uploads",
    description=(
        "List the uploads of the signed-in account. An upload is a "
        "submission: the raw files plus the entries parsed from them. "
        "Works only for the account the credential belongs to."
    ),
    annotations=READ_ONLY,
)
async def list_uploads(
    ctx: Context,
    upload_name: Annotated[str, Field(description="Filter by upload name (substring).")] = "",
    is_published: Annotated[
        str, Field(description="Filter: true, false, or empty for both.")
    ] = "",
    process_status: Annotated[
        str, Field(description="Filter by processing status, e.g. SUCCESS or FAILURE.")
    ] = "",
    page_after_value: Annotated[
        str, Field(description="Cursor from the previous page.")
    ] = "",
) -> Any:
    """List uploads of the authenticated user."""
    params = {
        "upload_name": upload_name,
        "is_published": is_published,
        "process_status": process_status,
        "page_after_value": page_after_value,
    }
    return await _call("list_uploads", "/uploads", params=params, hint=UPLOAD_QUERY_HINT)


@mcp.tool(
    title="Get one upload",
    description="Read a single upload: its metadata, its files, and its processing status.",
    annotations=READ_ONLY,
)
async def get_upload(
    ctx: Context,
    upload_id: Annotated[str, Field(description="The upload id.")],
) -> Any:
    """Get a specific upload."""
    return await _call("get_upload", f"/uploads/{upload_id}")


@mcp.tool(
    title="List an upload's entries",
    description="The entries that belong to one upload, with their ids and entry names.",
    annotations=READ_ONLY,
)
async def list_upload_entries(
    ctx: Context,
    upload_id: Annotated[str, Field(description="The upload id.")],
) -> Any:
    """Get the entries of the specific upload as a list."""
    return await _call("list_upload_entries", f"/uploads/{upload_id}/entries")


@mcp.tool(
    title="List an entry's raw files",
    description=(
        "The raw files of an entry as a directory listing: file names and "
        "sizes. Use it to see what was actually submitted before reading an "
        "archive, and to find the path to hand to get_raw_file."
    ),
    annotations=READ_ONLY,
)
async def list_raw_files(
    ctx: Context,
    entry_id: Annotated[str, Field(description="The entry id.")],
    name_contains: Annotated[
        str, Field(description="Only files whose path contains this text.")
    ] = "",
    limit: Annotated[
        int, Field(description="How many files to list.", ge=1, le=500)
    ] = 50,
) -> Any:
    """Get the raw files metadata for an entry by its id."""
    data = await _call("list_raw_files", f"/entries/{entry_id}/rawdir", bound=False)
    payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        return _bounded(data)
    files = payload.get("files") or []
    if name_contains:
        needle = name_contains.lower()
        files = [f for f in files if needle in str(f.get("path", "")).lower()]
    listed = files[:limit]
    out: dict[str, Any] = {
        "entry_id": payload.get("entry_id") or entry_id,
        "upload_id": payload.get("upload_id"),
        "mainfile": payload.get("mainfile"),
        "file_count": len(files),
        "files": listed,
    }
    if len(files) > len(listed):
        out["note"] = (
            f"{len(files)} files match; showing the first {len(listed)}. "
            "Narrow with name_contains or raise limit."
        )
    return _bounded(out)


# ── datasets ────────────────────────────────────────────────────────────────


@mcp.tool(
    title="List datasets",
    description=(
        "List NOMAD datasets — curated collections of entries that may span "
        "several uploads. Datasets can be public or belong to the account."
    ),
    annotations=READ_ONLY,
)
async def list_datasets(
    ctx: Context,
    dataset_name: Annotated[str, Field(description="Filter by dataset name (substring).")] = "",
    dataset_type: Annotated[
        str, Field(description="Filter by type, e.g. owned or custom.")
    ] = "",
    page_after_value: Annotated[str, Field(description="Cursor from the previous page.")] = "",
) -> Any:
    """Get a list of datasets."""
    params = {
        "dataset_name": dataset_name,
        "dataset_type": dataset_type,
        "page_after_value": page_after_value,
    }
    return await _call("list_datasets", "/datasets/", params=params)


@mcp.tool(
    title="Get one dataset",
    description="Read a single dataset by its id, including the entries it collects.",
    annotations=READ_ONLY,
)
async def get_dataset(
    ctx: Context,
    dataset_id: Annotated[str, Field(description="The dataset id.")],
) -> Any:
    """Get a dataset by id."""
    return await _call("get_dataset", "/datasets/", params={"dataset_id": dataset_id})


# ── schemas and metainfo ────────────────────────────────────────────────────


@mcp.tool(
    title="Read an entry's raw file",
    description=(
        "The content of one raw file of an entry, as it was submitted — the "
        "input a parser read. Use list_raw_files first to get the path. Text "
        "files come back as text; large or binary files are cut short."
    ),
    annotations=READ_ONLY,
)
async def get_raw_file(
    ctx: Context,
    entry_id: Annotated[str, Field(description="The entry id.")],
    path: Annotated[
        str, Field(description="Path of the file inside the entry's raw directory.")
    ],
) -> Any:
    """Get the raw data of an entry by its id."""
    quoted = quote(path.lstrip("/"), safe="/")
    return await _call(
        "get_raw_file",
        f"/entries/{entry_id}/raw/{quoted}",
        hint="Binary files are not meant to be read as text.",
    )


@mcp.tool(
    title="Get a schema",
    description=(
        "The serialization of a data schema, e.g. a schema id from the entry "
        "types this deployment knows."
    ),
    annotations=READ_ONLY,
)
async def get_schema(
    ctx: Context,
    schema_id: Annotated[str, Field(description="The schema id.")],
) -> Any:
    """Return a serialization of a specific data schema."""
    return await _call("get_schema", f"/schemas/{schema_id}")


@mcp.tool(
    title="Search searchable quantities",
    description=(
        "Find the quantities this NOMAD deployment can filter on, by name or "
        "data type. Use it before writing a search query, so the query uses "
        "fields that exist here."
    ),
    annotations=READ_ONLY,
)
async def search_quantities(
    ctx: Context,
    text: Annotated[str, Field(description="Substring to look for in quantity names.")] = "",
    dtype: Annotated[
        str, Field(description="Data type filter, e.g. str, float, int.")
    ] = "",
    aggregatable: Annotated[
        str, Field(description="true, false, or empty for both.")
    ] = "",
    page_size: Annotated[int, Field(description="Quantities per page.", ge=1, le=200)] = 20,
) -> Any:
    """Get a list of suggestions for the given quantity names and input."""
    body: dict[str, Any] = {
        "pagination": {"page_size": page_size},
        "query": {"input": text} if text else {},
    }
    if dtype:
        body["query"]["dtype"] = dtype
    if aggregatable:
        body["query"]["aggregatable"] = aggregatable.lower() == "true"
    return await _call("search_quantities", "/apps/search-quantities", method="POST", body=body)


# ── deployment and account ──────────────────────────────────────────────────


@mcp.tool(
    title="Get deployment info",
    description=(
        "What this NOMAD deployment is: version, deployment name, and the "
        "codes, parsers, and metainfo packages it ships. The cheapest way to "
        "check that the connection works and to learn what this instance can "
        "process. The installed plugin lists are omitted unless asked for."
    ),
    annotations=READ_ONLY,
)
async def get_info(
    ctx: Context,
    include_plugins: Annotated[
        bool,
        Field(
            description="Also return the long lists of plugin entry points and packages."
        ),
    ] = False,
) -> Any:
    """Get information about the nomad backend and its configuration."""
    data = await _call("get_info", "/info", bound=False)
    if include_plugins or not isinstance(data, dict):
        return _bounded(data)
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    keep = ("version", "deployment", "oasis", "git", "statistics", "normalizers")
    trimmed = {key: payload[key] for key in keep if key in payload}
    for key in ("codes", "parsers", "metainfo_packages", "plugin_packages", "plugin_entry_points"):
        if isinstance(payload.get(key), list):
            trimmed[f"{key}_count"] = len(payload[key])
    trimmed["note"] = (
        "Codes, parsers, and plugin lists are summarized; call again with "
        "include_plugins=true for the full document."
    )
    return _bounded(trimmed)


@mcp.tool(
    title="Get my account",
    description=(
        "The account the current credential belongs to. Answers 'whose data am "
        "I seeing?' and tells an expired token from an empty result. Needs the "
        "users:read scope; a key without it is refused with 403."
    ),
    annotations=READ_ONLY,
)
async def get_me(ctx: Context) -> Any:
    """Get your account data."""
    return await _call("get_me", "/users/me")


@mcp.tool(
    title="Get a crystal structure",
    description=(
        "Build and return an atomistic structure file from the data of an "
        "entry — the geometry behind a calculation or a measurement."
    ),
    annotations=READ_ONLY,
)
async def get_structure(
    ctx: Context,
    entry_id: Annotated[str, Field(description="The entry id.")],
    path: Annotated[
        str,
        Field(
            description=(
                "Path to the system inside the archive, e.g. 'run/0/system/0' "
                "or 'results/material/topology/0'. Defaults to 'run/0/system/0'."
            )
        ),
    ] = "run/0/system/0",
    format: Annotated[
        str, Field(description="File format: cif (default), xyz, or pdb.")
    ] = "cif",
) -> Any:
    """Build and retrieve an atomistic structure file from data within an entry."""
    params = {"path": path or "run/0/system/0", "format": format}
    return await _call("get_structure", f"/systems/{entry_id}", params=params)


@mcp.tool(
    title="List user groups",
    description="The user groups of this NOMAD deployment, with their members.",
    annotations=READ_ONLY,
)
async def list_groups(ctx: Context) -> Any:
    """List user groups."""
    return await _call("list_groups", "/groups")


# ── discovery helpers used by the register page ─────────────────────────────

def tool_names() -> list[str]:
    """Every tool this server offers, for the registration form."""
    return sorted(_TOOL_NAMES)


_TOOL_NAMES = {
    "search_entries",
    "get_entry",
    "get_entry_archive",
    "list_uploads",
    "get_upload",
    "list_upload_entries",
    "list_raw_files",
    "get_raw_file",
    "list_datasets",
    "get_dataset",
    "get_schema",
    "search_quantities",
    "get_info",
    "get_me",
    "get_structure",
    "list_groups",
}


def tool_descriptions() -> list[tuple[str, str]]:
    """(name, one-line purpose) for the registration form."""
    out: list[tuple[str, str]] = []
    for tool in mcp._tool_manager.list_tools():  # noqa: SLF001 -- SDK has no public listing
        description = (tool.description or "").split(".")[0]
        out.append((tool.name, description.strip() or tool.name))
    return sorted(out)
