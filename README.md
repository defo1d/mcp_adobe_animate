# Animate MCP Safe

A local MCP server and CEP panel for Adobe Animate on macOS. Create isolated FLA projects, inspect timelines, apply bounded animation edits, export PNG frames, and review HTML or MP4 previews from Codex or another MCP client.

**Version 1.0.7 — source distribution.** Installation currently requires building and installing a signed Adobe CEP panel. This repository is not an official Adobe or OpenAI product and is not listed in the public Codex Plugins Directory.

Based on [takuroh51/mcp-for-animate](https://github.com/takuroh51/mcp-for-animate), upstream commit `189704afe2380bbe02fd273f6962caead8f099ce`. The upstream MIT license and copyright notice are preserved in [LICENSE.md](LICENSE.md). The public package uses its own small CEP adapter, `host.js`; Adobe's `CSInterface.js` SDK is not redistributed.

## Requirements

- macOS and an installed, licensed Adobe Animate with CEP 12 support.
- Python 3.11 or newer. The server uses only the standard library: no pip, uv, or npm packages are required.
- A client that supports local stdio MCP servers, such as Codex desktop.
- Existing FFmpeg, optionally, for MP4 output. PNG and HTML previews work without it.
- Node.js only for running JavaScript development tests; the panel does not enable Node.js.

The preceding 1.0.6 build was exercised in Animate 2024 (24.0.15.5 / CEP 12) on one Mac: new FLA creation, animation edits with backups, saving and reopening, PNG export, HTML playback, a four-second 96-frame MP4, and native Codex discovery of 11 tools. Version 1.0.7 replaces the Adobe SDK wrapper with the project-owned adapter and passes 35 Python and 30 JavaScript tests, including panel and pairing flows through that adapter. This new adapter has not yet been reinstalled and tested in real Animate. Other Animate versions and Windows are unverified.

## Tools

| Tool | Purpose |
| --- | --- |
| `create_project` | Create a new FLA in a fresh private directory; optional disposable smoke-test template |
| `open_project` | Open a project previously created by this MCP, using its `run_id` |
| `get_documents` | Inspect open documents and their current identifiers |
| `get_timeline`, `get_library` | Inspect layers, frames, instances, and library items |
| `apply_animation` | Apply named-instance poses, graphic-symbol frames, keyframes, and classic tweens after a backup |
| `export_frames` | Export up to 240 PNG frames and a local HTML player |
| `create_preview` | Export PNG/HTML and optionally an MP4 using configured FFmpeg |
| `get_frame` | Return an exported PNG as MCP image content for visual review |
| `export_sprite_sheet`, `export_all_sprite_sheets` | Export bounded PNG/JSON sprite sheets |

Drawings and character rigs must already exist in the FLA for `apply_animation`. Give target instances unique names such as `mouth` or `arm_left`. A `classic_tween` requires existing keyframes at both ends. The server does not create a complete illustrated character from a text prompt.

## Set up private configuration

Clone this repository and work from its root:

```sh
git clone https://github.com/defo1d/mcp_adobe_animate.git
cd mcp_adobe_animate
```

Use a private directory outside the repository. These commands create fresh random keys without printing them; configuration creation refuses to overwrite an existing file:

```sh
umask 077
mkdir -p "$HOME/Library/Application Support/Animate MCP Safe"
python3 mcp/setup_config.py \
  --config "$HOME/Library/Application Support/Animate MCP Safe/config.json" \
  --output "$HOME/Library/Application Support/Animate MCP Safe/exports"
```

The directory must belong to you with mode `700`, and the configuration with mode `600`. The export path must have no symlink components. To enable MP4, add `--ffmpeg /absolute/path/to/your/trusted/ffmpeg` when creating the configuration. No executable is downloaded automatically.

Create a separate panel pairing file with only the panel key and port. This command reads the private configuration locally and does not display either key:

```sh
python3 - <<'PY'
import json, os
from pathlib import Path
os.umask(0o077)
directory = Path.home() / 'Library/Application Support/Animate MCP Safe'
config = json.loads((directory / 'config.json').read_text())
with (directory / 'panel-pairing.json').open('x') as stream:
    json.dump({name: config[name] for name in ('panel_token', 'port')}, stream)
PY
```

Do not share or commit these files. Each installation needs its own keys.

## Build and install the panel

The offline macOS packager uses existing `/usr/bin/openssl` and `/usr/bin/xmllint`. It generates a local self-signed certificate outside the repository and creates a new ZXP; it does not modify trust settings or install anything:

```sh
python3 tools/sign_panel.py \
  --signing-dir "$HOME/Library/Application Support/Animate MCP Safe/signing" \
  --output "$HOME/Library/Application Support/Animate MCP Safe/animate-mcp-safe-1.0.7.zxp" \
  --legacy-cep-signature
```

Install the ZXP with Adobe's installed UnifiedPluginInstallerAgent. A typical Creative Cloud location is:

```sh
"/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS/UnifiedPluginInstallerAgent" \
  --install "$HOME/Library/Application Support/Animate MCP Safe/animate-mcp-safe-1.0.7.zxp"
```

The Adobe executable location can differ between installations. If your installation rejects the package, retain the error and check Adobe compatibility; do not disable signature checks, Gatekeeper, SIP, or enable `PlayerDebugMode`. The packager's certificate lasts 365 days and does not establish an independently verified publisher identity. CEP 12 requires the legacy RSA-SHA1 container signature in the tested installation; file digests and bridge authentication use SHA256. Keep signing keys private. Increase the manifest version when updating an installed panel.

## Connect Codex and Animate

Add a local MCP server to your Codex configuration. Replace every placeholder with an absolute path on your Mac; the TOML values do not expand `$HOME`:

```toml
[mcp_servers.animate_safe]
enabled = true
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/mcp_adobe_animate/mcp/launch.py"]
cwd = "/absolute/path/to/mcp_adobe_animate"
startup_timeout_sec = 15
tool_timeout_sec = 240
disabled_tools = ["execute_extend_script"]

[mcp_servers.animate_safe.env]
ANIMATE_MCP_CONFIG = "/Users/yourname/Library/Application Support/Animate MCP Safe/config.json"
```

Restart the MCP server/client as needed and use a new chat to refresh tool discovery. See [Codex MCP configuration](https://developers.openai.com/codex/mcp).

In Animate, open a new disposable document so CEP panels can load, then open **Window → Extensions → Animate MCP Safe**. Choose the private `panel-pairing.json` file and select **Connect**. Expect `Connected · bounded operations`. Never send a pairing key to the assistant.

For optional automatic connection, copy the panel-only pairing file to `auto-pairing.json` in the same private directory and reload the panel. The panel reads only this fixed per-user file. It authenticates the server before registering, retries connection serially with a 1–30 second backoff, and never replays edits. **Disconnect** cancels automatic retry until the panel is loaded again.

`launch.py` owns a loopback bridge while the MCP client is running, or reuses an already authenticated bridge on the configured port. It never installs a LaunchAgent. Keep the bridge on `127.0.0.1`; do not expose it through a public tunnel.

## Review an animation

1. Use `create_project` to make a fresh FLA, optionally with `template: "smoke_test"`.
2. Inspect its current `document_id` and `timeline_index`; frame and layer indices start at zero.
3. Use `apply_animation` on uniquely named instances. A nonempty FLA backup is required before mutation.
4. Use `create_preview`, then `get_frame` to inspect key poses and the HTML/MP4 player to review motion.
5. Save in Animate. MCP edits do not automatically save the source document.

`open_project` accepts only managed `run_id` values, not arbitrary user paths. Document inspection and animation edits can address other open documents by their explicit identifiers; they are not restricted to managed projects. Do not authorize edits to unrelated documents.

## Security boundaries and limitations

- Loopback-only HTTP with separate random 256-bit MCP and panel keys. HMAC-SHA256 authenticates both requests and replies, with fresh nonces, timestamps, and server instance/session checks.
- Closed command allowlist, bounded strict JSON, Host/Origin checks, no CDN, no CEP Node/mixed context, no debug listener, no installation hooks, and no automatic downloads.
- New private export directories; unsafe paths and symlinks are rejected. PNG size, structure, CRC, and dimensions are checked. Limits include 200 animation operations per call, 240 frames per export, 4096×4096 pixels, 8 MiB per PNG, and 256 MiB per batch.
- Arbitrary JSFL is off by default (`allow_scripts=false`). `execute_extend_script` is deliberately hidden in the Codex example. Local opt-in and manual approval do not turn arbitrary scripts into a sandbox.
- Animation batches are not atomic: a host error can leave partial changes. Restore the backup and inspect state before retrying an edit after a timeout.
- Previews show the authoring timeline. They do not simulate sound, ActionScript, events, or independently playing nested MovieClips. MP4 output is silent and does not preserve alpha.
- Export directories are not deleted automatically. The code does not protect against a compromised Adobe application or another process running as your macOS user. Adobe and optional FFmpeg remain trusted components; tests do not guarantee absence of all vulnerabilities.

## Development checks

Tests use temporary data and simulated Adobe host objects; they do not open user FLA projects:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/*.test.cjs
```

Set `ANIMATE_TEST_FFMPEG=/absolute/path/to/ffmpeg` for the optional real FFmpeg check. No private configurations, signing material, FLA projects, exported frames, local audit logs, or upstream unsafe server history are included in this public snapshot.
