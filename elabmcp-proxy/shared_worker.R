#!/usr/bin/env Rscript
#
# Shared R worker for elabFTW MCP.
# Single R process serves all users. Credentials injected per-request
# via HTTP headers (x-elabftw-api-key, x-elabftw-base-url).
# Write scope (readonly/hybrid/full) injected per-request via X-Write-Scope.

Sys.setenv(ELABFTW_BASE_URL = Sys.getenv("ELABFTW_BASE_URL", "http://placeholder.local"))
Sys.setenv(ELABFTW_API_KEY = Sys.getenv("ELABFTW_API_KEY", "placeholder"))

library(elabrmcp)
library(mcptools)

# ── Patch mcptools: inject per-request credentials + write scope into live config ──
.handle_http_post_original <- mcptools:::handle_http_post

.handle_http_post_patched <- function(req) {
  api_key <- req[["HTTP_X_ELABFTW_API_KEY"]]
  base_url <- req[["HTTP_X_ELABFTW_BASE_URL"]]

  if (!is.null(api_key) && nchar(api_key) > 0
      && !is.null(base_url) && nchar(base_url) > 0) {
    env <- tryCatch(
      get(".server_env", envir = asNamespace("elabrmcp"), inherits = FALSE),
      error = function(e) NULL
    )
    if (!is.null(env) && exists("config", envir = env, inherits = FALSE)) {
      cfg <- env$config
      cfg$elabftw$base_url <- base_url
      cfg$elabftw$api_key <- api_key

      # Per-request write scope from JWT profile (X-Write-Scope header)
      write_scope <- req[["HTTP_X_WRITE_SCOPE"]]
      if (!is.null(write_scope) && nchar(write_scope) > 0) {
        r <- write_scope == "r"
        h <- write_scope == "h"
        f <- write_scope == "f"
        cfg$runtime$effective_write_comments   <- h || f
        cfg$runtime$effective_write_tags       <- h || f
        cfg$runtime$effective_write_metadata   <- h || f
        cfg$runtime$effective_write_create     <- f
        cfg$runtime$effective_write_update     <- f
        cfg$runtime$effective_write_links      <- f
        cfg$runtime$effective_write_steps      <- f
        cfg$runtime$effective_write_inventory  <- f
        cfg$runtime$effective_write_compounds  <- f
      }

      env$config <- cfg
    }
    Sys.setenv(ELABFTW_BASE_URL = base_url)
    Sys.setenv(ELABFTW_API_KEY = api_key)
  }
  .handle_http_post_original(req)
}

assignInNamespace("handle_http_post", .handle_http_post_patched, "mcptools")

# ── Start MCP server ──
port <- as.integer(Sys.getenv("ELABMCP_R_PORT", "18080"))
host <- Sys.getenv("ELABMCP_R_HOST", "127.0.0.1")
elabrmcp::elabr_mcp_server(type = "http", host = host, port = port)
