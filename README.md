# VORTEX Network Panel

VORTEX Network Panel is a lightweight web UI for managing a sing-box based policy-routing gateway.

Key capabilities include device management for VMess clients, local and remote client configuration generation, force-direct and force-VPN routing rules, status and diagnostics, configuration validation, transactional changes, backups and rollback, a root host-agent separated from the unprivileged web UI, and mock development mode.

## Architecture

```text
Web UI container
      ↓ Unix socket
vortex-netctl host agent
      ↓
sing-box / systemd
```

## Development

```bash
docker compose -f docker-compose.dev.yml up --build
```

Open <http://localhost:9080>.

## Production

The host-agent runs on the Linux host and the web panel runs in Docker. Production settings are supplied through environment and configuration files; use the provided examples as a starting point and keep local production configuration outside version control.

From the repository root, install the host-agent with `sudo ./host-agent/install.sh`. Before the first install, create a root-only production JSON config outside the repository at `/etc/vortex-netctl/config.json`; `host-agent/config.example.json` is documentation only and is rejected by the installer. For a missing or placeholder config, pass an explicit validated source with `sudo env VORTEX_NETCTL_CONFIG_SOURCE=/root/vortex-netctl-production.json ./host-agent/install.sh`. Existing validated production config is preserved.

## Security

The web container is unprivileged and has no Docker socket. The host-agent exposes typed operations only, not arbitrary shell RPC. Configuration changes are validated before they are applied.

## Status

This is an early-stage personal project.