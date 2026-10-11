# Animate MCP Safe

A local MCP server and CEP panel for Adobe Animate on macOS. Create isolated FLA projects, inspect timelines, apply bounded animation edits, export PNG frames, and review HTML or MP4 previews from Codex or another MCP client.

**Version 1.3.0 — source distribution.** Installation currently requires building and installing a signed Adobe CEP panel. This repository is not an official Adobe or OpenAI product and is not listed in the public Codex Plugins Directory.

Based on [takuroh51/mcp-for-animate](https://github.com/takuroh51/mcp-for-animate), upstream commit `189704afe2380bbe02fd273f6962caead8f099ce`. The upstream MIT license and copyright notice are preserved in [LICENSE.md](LICENSE.md). The public package uses its own small CEP adapter, `host.js`; Adobe's `CSInterface.js` SDK is not redistributed.

## Requirements

- macOS and an installed, licensed Adobe Animate with CEP 12 support.
- Python 3.11 or newer. The server uses only the standard library: no pip, uv, or npm packages are required.
- A client that supports local stdio MCP servers, such as Codex desktop.
- Existing FFmpeg, optionally, for MP4 output. PNG and HTML previews work without it.
- Node.js only for running JavaScript development tests; the panel does not enable Node.js.

The 1.3.0 signed panel was installed through Adobe's existing installer on one Mac, and its installed source files match this repository byte for byte. Native Codex discovers 24 default tools and hides arbitrary scripts. The test suite includes deterministic motion, stale revisions, matrix readback, private audio uploads, a movie crossing the 240-frame batch boundary, and real FFmpeg encoding with audio. Live Animate validation created a new 24-second native vector FLA, verified every baked pose, saved it with a validated archive backup, and exported all 576 frames plus a PCM chime to H.264/AAC. PNG inspection caught and corrected default text styling, title overlap and camera coverage. After closing and reopening the saved FLA, both endpoint renders preserved the composition, rig playback and audio cue; fewer than 0.02% of pixels had small edge-rasterization differences. A successful test is not a claim of professional acting or artistic quality. The preceding 1.0.6 build completed a real four-second FLA/PNG/MP4 test in Animate 2024 (24.0.15.5 / CEP 12). Other Animate versions and Windows are unverified.

## Tools

| Tool | Purpose |
| --- | --- |
| `create_project`, `open_project` | Create a fresh private FLA or reopen an MCP-created project by its generated ID |
| `get_documents`, `get_timeline`, `get_library` | Inspect open documents and authoring metadata |
| `get_animation_state` | Read scoped keyframes, matrices, pivots, poses, spans, labels and sound cues; issue a single-use edit revision |
| `get_symbol_graph` | Read nested dependencies, cycles and independent MovieClip timing warnings |
| `author_scene` | Create editable native vector graphics, pose frames and named parts in root or nested timelines |
| `plan_motion` | Preview the numerical motion plan without touching Animate |
| `apply_motion` | Bake exact sampled poses after a revision check and backup; read native matrices back |
| `retime_motion` | Rescale motion-key timings without editing Animate; reject collapsed keys |
| `solve_two_bone_ik` | Calculate a planar two-bone solution with reach/error diagnostics |
| `save_project` | Save a matching managed FLA after a revision check and backup |
| `begin_audio_upload`, `append_audio_chunk`, `finish_audio_upload` | Upload and validate bounded integer PCM WAV data without paths or a decoder |
| `set_audio` | Add a recorded stream-sound cue to a new managed timeline layer |
| `export_movie` | Render up to 1440 PNGs in batches and encode a full MP4, optionally mixing recorded PCM cues |
| `review_frames`, `get_frame` | Review original renders, a contact sheet, gross-change/blank-alpha diagnostics and MCP image content |
| `export_frames`, `create_preview` | Render up to 240 PNGs, an HTML player and optional silent MP4 |
| `export_sprite_sheet`, `export_all_sprite_sheets` | Export bounded PNG/JSON sprite sheets |

The legacy `apply_animation` write path is retired and rejected by the adapter and broker. New editing tools accept only projects created by this MCP. Give every part and layer a unique stable name. Graphics provide deterministic timeline playback; independently timed MovieClips require a separate runtime renderer.

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
  --output "$HOME/Library/Application Support/Animate MCP Safe/animate-mcp-safe-1.3.0.zxp" \
  --legacy-cep-signature
```

Install the ZXP with Adobe's installed UnifiedPluginInstallerAgent. A typical Creative Cloud location is:

```sh
"/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS/UnifiedPluginInstallerAgent" \
  --install "$HOME/Library/Application Support/Animate MCP Safe/animate-mcp-safe-1.3.0.zxp"
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

## Build and review an animation

1. Create a fresh FLA with `create_project`. Retain its `run_id`, current `document_id` and `timeline_index`.
2. Read `get_animation_state` for the intended layers and frame range. For nested work, supply the library `symbol_name`.
3. Create native vector graphic symbols and named parts with `author_scene`, using the returned `revision_id`. Existing symbols/layers are never replaced.
4. Plan motion with `plan_motion`, then inspect again and apply with `apply_motion`. Every guarded write consumes its revision, requests a native snapshot, waits for its complete archive and CRC checks, and creates a private durable backup first. Animate rechecks the same revision before applying the edit.
5. Render with `export_movie` or `create_preview`. Read PNGs with `get_frame`, inspect key poses with `review_frames`, and watch playback at normal and reduced speeds.
6. Save with `save_project`. Reopening changes the document ID: read it again and obtain a fresh revision.

A revision covers the requested authoring metadata and keyframe elements. It is not a cryptographic snapshot of every vector point or the entire FLA. Inspection returns authoring keys and span durations; it does not pretend that a stored endpoint value is the rendered value of every in-between frame. PNGs remain the visual authority.

### Motion semantics

- All frame indices start at zero. The easing and interpolation on a key describe the segment leaving that key.
- Custom cubic timing curves solve their x component before evaluating y. Spatial curves, anticipation, overshoot, bounce and explicit holds can be baked on ones or twos.
- Rotation defaults to explicit angles, preserving full turns. `rotation_mode: "shortest"` selects the shortest angular path.
- `x`/`y` place a local `pivot` in timeline coordinates. Earlier tracks can be parents; full affine multiplication preserves nonuniform scales and skew instead of approximating them with separate rotations.
- `firstFrame` is discrete. Use `playback: "play once"` with `sync_to_timeline: true` for nested rigs/camera graphics whose phase must continue across baked keys. Use `single frame` for eye, mouth and expression poses.
- Sampling retains exact off-grid keys. At most 400 poses are accepted per write, with a 240-frame inspection range. Split longer shots into inspected batches. This is sampled animation, not a claim of native procedural constraints or a joint-limit bone solver.

### Original classroom example

The included example creates its own 24-second, 1280×720, 24 fps FLA with original classroom artwork, two nested head rigs, separate eye/mouth tracks, pauses and reactions, a phone arc, camera cuts and a generated PCM chime. It does not use an existing project or download media. Mouth poses are time-coded expressive animation; they do not claim automatic phoneme alignment.

```sh
ANIMATE_MCP_CONFIG="$HOME/Library/Application Support/Animate MCP Safe/config.json" \
  python3 examples/classroom_demo.py --report-dir /absolute/new/private/report-directory
```

The report directory must not already exist. The example records results and backups, stops on an error, and never automatically retries an edit. Read-only readiness checks may be retried. Rendered FLA/media and private reports are excluded from Git.

## Security boundaries and limitations

- Loopback-only HTTP uses separate random 256-bit MCP/panel keys. HMAC-SHA256 authenticates requests and replies with nonces, timestamps and server/session checks. No public tunnel, background LaunchAgent or external service is needed.
- Fixed host functions receive closed, bounded data schemas. The new default write path checks both the document ID and the matching managed FLA, rechecks the scoped state before snapshotting and again before editing. A separate native request lets Adobe finish its FLA snapshot; the broker validates the archive and CRCs before copying a durable backup. Mac URI/platform-path differences are handled with exact validated paths.
- The panel has no Node mode, CDN, mixed context, debug listener or downloaded executable. Python uses the standard library only. General JSFL remains disabled by default; explicit local opt-in plus manual panel approval is required and does not constitute a sandbox.
- Art is limited to native rectangles, ellipses, Bezier paths and bounded text. Tools accept no SVG scripts, arbitrary save/import paths, URLs, executable paths or shell commands. Dependency preflight rejects recursive symbol placement.
- Jobs are fresh private directories. Unsafe paths/symlinks are rejected; PNG structure, CRC, dimensions and byte sizes are checked. Limits include 8 MiB per PNG, 256 MiB per export/movie, 1440 movie frames, and 400 baked poses per command.
- PCM uploads are append-only with locked offsets and immutable finalized hashes: up to 16 MiB, 60 seconds, mono/stereo, integer PCM and 8–48 kHz. Native sound cues must match their recorded timeline positions before preview mixing. FFmpeg runs without a shell, with generated paths, file-only inputs, a sanitized environment and a timeout.
- Host edits are not atomic: an error can leave partial changes. Error messages identify a recovery backup when one exists. Inspect before retrying. Movie export is not atomic across batches; avoid concurrent manual editing during render.
- Frame metrics detect gross changes, repeated sample grids, transparent renders and sampled partial transparency that can reveal camera coverage errors. A still frame may be a deliberate hold. These diagnostics do not score acting, anatomy, continuity or artistic quality.
- PNG/HTML exports do not simulate ActionScript/events or independent MovieClip timing. `export_movie` mixes only validated recorded PCM cues, not arbitrary imported sounds, effects or runtime audio. MP4 uses H.264/AAC and does not preserve alpha.
- Existing read-only inspection/export tools can address explicitly pinned open documents; managed editing tools cannot write to unrelated projects. Export directories are retained. A compromised Adobe/FFmpeg application or another process running as your macOS user remains outside this boundary. Tests and manual review cannot guarantee absence of every vulnerability.

## Development checks

Tests use temporary data and simulated Adobe host objects; they do not open user FLA projects:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/*.test.cjs
```

The verified suite passes 60 Python checks (including real FFmpeg) and 40 JavaScript checks. Tests cover completed/partial FLA snapshots and CRCs, immutable backups, native text style readback, stale revisions and malformed input.

Set `ANIMATE_TEST_FFMPEG=/absolute/path/to/ffmpeg` for the optional real FFmpeg check. No private configurations, signing material, FLA projects, exported frames, local audit logs, or upstream unsafe server history are included in this public snapshot.
