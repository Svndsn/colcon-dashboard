"""The server configuration file, read once at startup.

~/.config/colcon-dashboard/config.ini (configparser format; YAML would
need a dependency, and tomllib needs Python 3.11). Every value is
optional, and the command line always wins:

    [server]
    host = 0.0.0.0
    port = 8642
    log_base = log
    check_updates = true

    [builds]
    auto_prune_keep = 10

    [ai]
    claude_bin = /custom/path/claude

    [ui]
    editor_url = vscode://file{path}:{line}
    browser = auto

    [discover]
    scan_home = ask
    extra_roots = /mnt/data, ~/ros

    [notify]
    command = notify-send "colcon {outcome}" "{name}: {summary}"

A missing file, a broken file, or a bad value must never stop the
server: unreadable values resolve to None, like missing ones.
"""

import configparser
import os
import re
import stat


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "colcon-dashboard", "config.ini")


TEMPLATE = """\
# colcon-dashboard configuration.
# Every key is optional and shown with its default; the command line
# always wins. Uncomment a key to change it, then restart the server
# (colcon-dashboard --restart-service when it runs as a service).

[server]
# The bind address. 0.0.0.0 serves the dashboard to your network.
#host = 127.0.0.1

# The HTTP port.
#port = 8642

# The log directory colcon writes, relative to each workspace.
#log_base = log

# Show a note in the workspace picker when a newer version is out.
# The deb package asks apt (the local package lists, no network) and
# checks by default. A pip or pipx install asks PyPI once a day, only
# when this key is true. "Check now" in the settings asks one time,
# also when this key is false.
#check_updates = false

[builds]
# After a build finishes, delete old runs, keeping the newest N of
# each kind (build_*/test_*). Unset or -1: never delete anything.
# For example 10 keeps the newest 10 builds and 10 test runs.
#auto_prune_keep = -1

[ai]
# The claude CLI used for failure analysis (default: found on PATH).
#claude_bin = /path/to/claude

[ui]
# Turn file:line references in failure logs into editor links.
# Placeholders: {path}, {line}, {line0} (= {line} - 1), and
# {project} (the workspace directory name). Unset: no links.
#editor_url = vscode://file{path}:{line}
# JetBrains IDEs need the open project's name and count lines from
# zero, hence {project} and {line0}:
#editor_url = jetbrains://clion/navigate/reference?project={project}&path={path}:{line0}

# The browser that the tray, colcon-dashboard --app, and clicks on
# notifications open. auto follows the default browser of the desktop:
# for Chrome, Chromium, Brave, or Edge it opens the installed dashboard
# app or an app window, and for Firefox a new window. chromium and
# firefox pick that browser. default always opens the default browser.
#browser = auto

[discover]
# Search your home directory for colcon workspaces: ask (the workspace
# picker asks once and saves the answer here), yes, or no.
#scan_home = ask

# More directories for the workspace scan.
# Separate them with commas or newlines. ~ expands to your home.
#extra_roots = /mnt/data, ~/ros

[notify]
# A command to run when a build ends, also with no dashboard page open.
# It runs for the workspaces that the server watches. The server does not
# use a shell: it splits the line into arguments, then fills them in.
# Placeholders: {workspace}, {name} (the workspace directory name),
# {build}, {outcome} (passed, failed, or aborted), {summary}, {failed}.
#command = notify-send "colcon {outcome}" "{name}: {summary}"
# A webhook works through curl:
#command = curl -s -X POST -d "{name}: {summary}" https://example.com/hook
"""


def write_template(path=None):
    """Write a fully commented template so the keys are discoverable.

    The CLI calls this when no config file exists. Mode "x" never
    clobbers a file that appeared meanwhile, and any failure returns
    None: the template is a convenience, never a requirement.
    """
    path = path or config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "x") as f:
            f.write(TEMPLATE)
    except OSError:
        return None
    return path


def _parse(text):
    """The values of an ini text, read like Config reads them, or None
    when configparser cannot read the text."""
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    try:
        cp.read_string(text)
        return {s: dict(cp.items(s, raw=True))
                for s in [cp.default_section, *cp.sections()]}
    except configparser.Error:
        return None


def _ini_value(line):
    """A line as configparser sees it: no comment, no outer spaces."""
    if line.strip()[:1] in ("#", ";"):
        return ""
    for i, c in enumerate(line):  # an inline comment needs a space before
        if c in "#;" and i and line[i - 1].isspace():
            line = line[:i]
            break
    return line.strip()


def _edit(lines, section, key, new):
    """lines with "key = value" set in [section], like configparser
    finds them: the section name is case-sensitive, the key is not, and
    a line indented deeper than its key continues that key's value."""
    def header(line):
        m = configparser.ConfigParser.SECTCRE.match(_ini_value(line))
        return m and m.group("header")
    head = next((i for i, ln in enumerate(lines) if header(ln) == section),
                None)
    if head is None:
        return lines + ["\n", "[%s]\n" % section, new + "\n"]
    end = next((i for i in range(head + 1, len(lines)) if header(lines[i])),
               len(lines))
    keys, opt_indent = [], None  # (line, indent) of each option line
    for i in range(head + 1, end):
        text = _ini_value(lines[i])
        if not text:
            continue
        indent = len(lines[i]) - len(lines[i].lstrip())
        if opt_indent is not None and indent > opt_indent:
            continue  # a continuation line
        opt_indent = indent
        keys.append((i, indent, re.split(r"[=:]", text, 1)[0].strip().lower()))
    hit = next(((i, ind) for i, ind, name in keys if name == key), None)
    if hit is not None:
        at, ind = hit
        stop = at + 1
        while stop < end and lines[stop].strip() and \
                len(lines[stop]) - len(lines[stop].lstrip()) > ind:
            stop += 1
        return lines[:at] + [lines[at][:ind] + new + "\n"] + lines[stop:]
    # below the commented example, when no indented option follows it
    # (that line would continue the new value); else at the section end
    hint = [i for i in range(head + 1, end)
            if re.match(r"\s*[#;]\s*%s\s*[=:]" % re.escape(key), lines[i])]
    if hint and all(ind == 0 for i, ind, _ in keys if i > hint[-1]):
        at = hint[-1] + 1
    else:
        at = end
        while at > head + 1 and not lines[at - 1].strip():
            at -= 1  # keep the blank lines before the next section
    return lines[:at] + [new + "\n"] + lines[at:]


def save_value(section, key, value, path=None):
    """Write "key = value" into [section] of the ini file.

    Edits that one line in place, so every comment and every other key
    stays as the user wrote it. A missing file starts from the template.
    The write happens only when the new text reads back with that one
    value changed and every other value the same: a file that the edit
    cannot handle stays untouched. Returns the written path, or None.
    """
    path = os.path.realpath(path or config_path())  # keep a symlink
    try:
        with open(path) as f:
            text = f.read()
    except FileNotFoundError:
        text = TEMPLATE
    except (OSError, UnicodeDecodeError):
        return None
    if text and not text.endswith("\n"):
        text += "\n"
    out = "".join(_edit(text.splitlines(keepends=True), section, key,
                        "%s = %s" % (key, value)))
    before, after = _parse(text), _parse(out)
    if before is None or after is None:
        return None
    want = {s: dict(v) for s, v in before.items()}
    want.setdefault(section, dict(before.get(configparser.DEFAULTSECT, {})))
    want[section][key] = value
    if after != want:
        return None
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            f.write(out)
        try:  # a token in [notify] command stays as private as before
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        except FileNotFoundError:
            pass
        os.replace(tmp, path)  # a crash mid-write never truncates it
    except OSError:
        return None
    return path


def save_extra_roots(roots, path=None):
    """Write roots as the [discover] extra_roots line of the ini file."""
    return save_value("discover", "extra_roots", ", ".join(roots), path)


def save_scan_home(value, path=None):
    """Write the [discover] scan_home line: "yes" or "no"."""
    return save_value("discover", "scan_home", value, path)


class Config:
    """A typed view over the ini file; unset keys resolve to None."""

    def __init__(self, path=None):
        self.path = path or config_path()
        cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
        try:
            self.exists = bool(cp.read(self.path))
        except (configparser.Error, OSError, UnicodeDecodeError):
            # a broken file behaves like a missing one: half-applied
            # values, with every diagnostic denying them, would be worse
            cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
            self.exists = False
        self.host = self._get(cp, "server", "host")
        self.port = self._get_int(cp, "server", "port")
        self.log_base = self._get(cp, "server", "log_base")
        # None (unset): the install decides (registry.update_check_on)
        self.check_updates = self._get_bool(cp, "server", "check_updates")
        self.auto_prune_keep = self._get_int(cp, "builds", "auto_prune_keep")
        self.claude_bin = self._get(cp, "ai", "claude_bin")
        self.editor_url = self._get(cp, "ui", "editor_url")
        self.browser = self._get(cp, "ui", "browser")
        # "ask" until the user answers the question in the workspace picker
        self.scan_home = self._get_choice(cp, "discover", "scan_home")
        self.extra_roots = self._get_list(cp, "discover", "extra_roots")
        self.notify_command = self._get(cp, "notify", "command")

    @staticmethod
    def _get(cp, section, key):
        try:
            value = cp.get(section, key).strip()
        except (configparser.Error, ValueError):
            return None
        return value or None

    @classmethod
    def _get_int(cls, section_cp, section, key):
        value = cls._get(section_cp, section, key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @classmethod
    def _get_list(cls, cp, section, key):
        """Comma- or newline-separated paths, ~-expanded; unset: []."""
        value = cls._get(cp, section, key)
        if value is None:
            return []
        return [os.path.expanduser(v.strip())
                for v in re.split(r"[,\n]", value) if v.strip()]

    @classmethod
    def _get_choice(cls, cp, section, key):
        """yes, no, or ask: unset and unknown values ask."""
        value = (cls._get(cp, section, key) or "").lower()
        if value in ("1", "true", "yes", "on"):
            return "yes"
        if value in ("0", "false", "no", "off"):
            return "no"
        return "ask"

    @classmethod
    def _get_bool(cls, cp, section, key):
        value = cls._get(cp, section, key)
        if value is None:
            return None
        return value.lower() in ("1", "true", "yes", "on")


CONFIG = Config()
