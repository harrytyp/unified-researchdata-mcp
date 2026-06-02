## DuckDNS Setup

This deployment uses [DuckDNS](https://duckdns.org) for dynamic DNS. A cronjob on the server updates the IP every 5 minutes:

```bash
*/5 * * * * curl -s 'https://www.duckdns.org/update?domains=researchmcp&token=YOUR_TOKEN&ip=' > /dev/null
```

DuckDNS automatically resolves `*.researchmcp.duckdns.org` wildcard subdomains — no per-service DNS records needed. The following subdomains are routed in the Caddyfile:

| Subdomain | Service |
|---|---|
| `elab-app.researchmcp.duckdns.org` | Streamlit elabFTW companion app |
| `proespm.researchmcp.duckdns.org` | Streamlit measurement report viewer |

### First-time DuckDNS setup

1. Sign in at [duckdns.org](https://duckdns.org) with your GitHub/Google account
2. Register a subdomain (e.g., `researchmcp`)
3. Copy the token shown on the page
4. On your server, install the cronjob with your token:
   ```bash
   crontab -e
   # Add: */5 * * * * curl -s 'https://www.duckdns.org/update?domains=YOURDOMAIN&token=YOUR_TOKEN&ip=' > /dev/null
   ```
