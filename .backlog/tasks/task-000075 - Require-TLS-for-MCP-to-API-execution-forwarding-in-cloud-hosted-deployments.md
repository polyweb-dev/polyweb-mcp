---
id: TASK-000075
title: Require TLS for MCP-to-API execution forwarding in cloud-hosted deployments
status: To Do
assignee: []
created_date: '2026-11-14T13:17:00Z'
labels:
  - security
  - backend
dependencies: []
priority: high
type: task
ordinal: 64000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Today `POLYWEB_EXECUTION_AUTHORITY_URL` may use plain `http://` in every deployment. The validator in `src/polyweb/configuration/config.py` exempts this one field from the HTTPS rule that applies to the public issuer and MCP resource URLs, and it does not check the host, so a public hostname is also accepted over HTTP. The Compose stack sets `http://api:8001`. For each search or fetch call, the MCP server forwards the caller's verified project API key to the API as a bearer token over cleartext HTTP. The API re-verifies that key.

This is acceptable for the current self-hosted, single-host Compose stack. The hop stays on the Docker bridge network on one host. It is not acceptable once the MCP server and the API run on different hosts, in a cloud-hosted deployment, or on any network an attacker can observe. A passive observer on that path could capture project keys, and a captured key grants the same access as the caller's own API calls. Cloud deployments also usually need a rule that forbids cleartext credentials between services.

The API port is also published on the host (`${API_PORT:-8001}:8001`), so a client that calls the API directly sends its key over HTTP on loopback or the LAN. This task covers the MCP-to-API hop, but the direct client path needs the same TLS treatment in a cloud deployment.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Cloud deployment mode rejects every execution_authority_url that is not https://
- [ ] #2 Self-hosted mode may keep plain HTTP for the authority URL, limited to loopback or a single-host Compose service name such as http://api:8001
- [ ] #3 The deployment mode is an explicit documented setting, not inferred from the URL
- [ ] #4 Cloud deployments carry the MCP-to-API hop over TLS (or mTLS), and the MCP forwarder validates the API certificate, so the bearer key never crosses a host boundary in cleartext
- [ ] #5 Direct client access to the published API port is either served over TLS in cloud deployments or documented as out of scope with a reason
- [ ] #6 Unit tests in tests/unit/configuration cover the policy: https accepted in all modes; http to loopback or the Compose service name accepted in self-hosted mode; http to a public or other non-local host rejected in cloud mode
- [ ] #7 The self-hosted Compose stack still starts with POLYWEB_EXECUTION_AUTHORITY_URL=http://api:8001 and passes the existing Compose config tests
- [ ] #8 security.md (MCP-to-API execution forwarding section) and configuration.md describe the cloud requirement and the mode setting
<!-- AC:END -->
