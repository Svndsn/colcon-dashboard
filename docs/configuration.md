---
icon: lucide/settings
description: >-
  Configure the Colcon Dashboard server with config.ini: port, bind address,
  update checks, automatic pruning, and editor links for file:line log lines.
---

# Configuration

The server reads `~/.config/colcon-dashboard/config.ini` at startup. The file is optional, and a command line flag always wins over it. This is how service users set the port or the bind address, because the systemd unit passes no flags.

If the file does not exist, the server writes a template with every key commented out. The `--install-service` command does the same. Open the template and uncomment the keys that you need. After a change, run `colcon-dashboard --restart-service`.

```ini
[server]
host = 127.0.0.1        ; use 0.0.0.0 to reach the page from another machine
port = 8642
log_base = log
check_updates = false   ; true: show a note when a newer version is out
                        ; (the deb package asks apt and is true by
                        ; default, other installs ask PyPI once a day.
                        ; "Check now" in the settings works also
                        ; when this is false)

[builds]
auto_prune_keep = -1    ; N >= 1: keep the newest N builds and N test
                        ; runs after each build the server watches
                        ; -1 (the default): never delete anything

[ai]
claude_bin =            ; explicit path to the claude CLI

[ui]
editor_url =            ; e.g. vscode://file{path}:{line} - file:line log
                        ; lines get a link that opens your editor.
browser = auto          ; auto, chromium, firefox, or default

[discover]
scan_home = ask         ; yes, no, or ask - scan the home directory for
                        ; workspaces. ask: the picker asks once.
extra_roots =           ; e.g. /mnt/data, ~/ros - more directories for
                        ; the workspace scan.

[notify]
command =               ; a command to run when a build ends
```

## Home directory scan

The workspace picker can scan your home directory for colcon workspaces. The scan reads only directory names, and the dashboard never sends them to the internet. Before the first scan, the picker asks you:

- **Scan my home folder**: the picker scans your home directory each time you open the dashboard.
- **Choose folders…**: the picker scans only the scan roots that you add.
- **Not now**: the picker does not scan your home directory.

The picker saves your answer as the `scan_home` key in `config.ini` and does not ask again. Every browser and the app window use the same answer. Below the found workspaces, the picker names the directories that it scans automatically. If the server cannot write `config.ini`, the answer applies until the server restarts.

When the server listens on the network (`host = 0.0.0.0`), every viewer of the dashboard can give the answer and see the found workspaces. This is the same as the other actions of the page, such as a server restart.

To change the answer, click "Scan roots…" in the picker, or open the settings. Then set or clear the check box on the row of your home directory. You can also set the key in the file by hand:

```ini
[discover]
scan_home = yes
```

## Extra scan roots

If your workspaces are on another drive, add their parent directories as scan roots. The picker scans the scan roots also when it does not scan your home directory.

You can edit the scan roots in the page. Open the workspace picker and click "Scan roots…", or open the settings (the gear button). Type a directory and click Add. To change a root, edit its path and press Enter. To remove a root, click ✕. The page saves the list as the `extra_roots` key in `config.ini` and changes only that line. A change applies at once, with no restart.

You can also set `extra_roots` in the file by hand. Separate the directories with commas or newlines:

```ini
[discover]
extra_roots = /mnt/data, ~/ros
```

The scan goes four directory levels down from each root. It skips hidden directories and symbolic links.

## Editor links

If you set `editor_url`, each `file:line` position in the logs gets a ↗ link. The link opens your editor at that line. For VS Code:

```ini
[ui]
editor_url = vscode://file{path}:{line}
```

JetBrains IDEs need the project name (`{project}`, the workspace directory name) and count lines from zero (`{line0}`, `{line}` minus one):

```ini
[ui]
editor_url = jetbrains://clion/navigate/reference?project={project}&path={path}:{line0}
```

## Browser

The tray icon, `colcon-dashboard --app`, and a click on a notification open the dashboard in a browser. The `browser` key chooses which one:

| Value | What opens |
|---|---|
| `auto` (the default) | It follows the default browser of your desktop. For Chrome, Chromium, Edge, or Brave, the [installed app](desktop-app.md) or an app window. For Firefox, a new window. |
| `chromium` | The first of Chrome, Chromium, Brave, Edge, and Vivaldi that is installed, as `auto` uses it |
| `firefox` | A new Firefox window |
| `default` | A tab in the default browser |

## Build notifications

If the page runs on the same machine as the server, the bell hands its choice to the server. The server then shows the notifications on your desktop, also with no page open (see [Desktop app](desktop-app.md#desktop-notifications)). For other channels, set a command in `[notify]`. The server runs it once when a build ends:

```ini
[notify]
command = notify-send "colcon {outcome}" "{name}: {summary}"
```

The command can use these placeholders:

| Placeholder | Value |
|---|---|
| `{outcome}` | `passed`, `failed`, or `aborted` |
| `{summary}` | For example `498 of 502 packages in 44m 12s, 4 failed` |
| `{failed}` | The number of failed packages |
| `{name}` | The workspace directory name |
| `{workspace}` | The full workspace path |
| `{build}` | The build id, for example `build_2026-10-20_16-50-56` |

The server does not use a shell. It splits the line into arguments first, and then it fills in the placeholders. So a package or a path name can never act as shell syntax. A webhook works through `curl`:

```ini
[notify]
command = curl -s -X POST -d "{name}: {summary}" https://example.com/hook
```

The command runs for the workspaces that the server watches: each workspace that a page opened, or that `colcon-dashboard .` registered, since the server started.

## Network exposure

When the server binds `0.0.0.0`, it prints the real LAN URL next to the loopback one.

!!! warning "The server trusts every caller"

    Expose the port only to a network that you trust. The server serves logs,
    and it deletes them on request, for every caller.
