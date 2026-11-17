"""The update note (registry.update_status): apt for the deb package,
PyPI for other installs, and a restart note after an upgrade."""

import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from colcon_dashboard import __version__
from colcon_dashboard import registry as registry_mod
import tests.helpers  # noqa: F401  (it points CONFIG at a test path)

_NEW_CODE_LOADS = registry_mod._new_code_loads  # the real one, unpatched

POLICY = """python3-colcon-dashboard:
  Installed: 0.11.1ppa1~ubuntu24.04.1
  Candidate: 0.11.2ppa1~ubuntu24.04.1
  Version table:
"""


class UpdateCheck(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.addCleanup(setattr, registry_mod, "CACHE_DIR", registry_mod.CACHE_DIR)
        registry_mod.CACHE_DIR = tmp.name
        # no real check runs in the background
        for p in (mock.patch.object(registry_mod, "_check_update_now"),
                  mock.patch.object(registry_mod.CONFIG, "check_updates", None),
                  mock.patch.object(registry_mod, "_disk_version",
                                    return_value=__version__)):
            p.start()
            self.addCleanup(p.stop)

    def cache(self, source, latest):
        with open(os.path.join(self.tmp, "update.json"), "w") as f:
            json.dump({"checked_at": time.time(), "source": source,
                       "latest": latest}, f)

    def install(self, kind):
        p = mock.patch.object(registry_mod, "install_source", return_value=kind)
        p.start()
        self.addCleanup(p.stop)

    def test_deb_version_to_upstream(self):
        self.assertEqual(registry_mod._upstream("0.11.2ppa1~ubuntu24.04.1"), "0.11.2")
        self.assertEqual(registry_mod._upstream("1:0.11.2-1"), "0.11.2")
        self.assertIsNone(registry_mod._upstream("(none)"))

    def test_apt_candidate_reads_the_untranslated_policy(self):
        # a fake apt-cache that answers only under LC_ALL=C
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        tool = os.path.join(bindir, "apt-cache")
        with open(tool, "w") as f:
            f.write('#!/bin/sh\n[ "$LC_ALL" = C ] || exit 1\ncat <<EOF\n'
                    + POLICY + "EOF\n")
        os.chmod(tool, os.stat(tool).st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, {"PATH": bindir + os.pathsep + os.environ.get("PATH", ""),
                                         "LC_ALL": "tr_TR.UTF-8"}):
            self.assertEqual(registry_mod._apt_candidate(), "0.11.2")
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):  # no apt-cache
            self.assertIsNone(registry_mod._apt_candidate())

    def test_deb_install_checks_by_default(self):
        self.install("apt")
        self.assertTrue(registry_mod.update_check_on())
        with mock.patch.object(registry_mod.CONFIG, "check_updates", False):
            self.assertFalse(registry_mod.update_check_on())

    def test_pip_install_checks_only_when_asked(self):
        self.install("pipx")
        self.assertFalse(registry_mod.update_check_on())
        self.cache("pypi", "99.0.0")
        self.assertIsNone(registry_mod.update_status())
        with mock.patch.object(registry_mod.CONFIG, "check_updates", True):
            note = registry_mod.update_status()
        self.assertEqual(note["kind"], "upgrade")
        self.assertEqual(note["command"], "pipx upgrade colcon-dashboard")

    def test_pip_command_uses_the_pip_of_this_python(self):
        # a venv install is not on PATH: a plain "pip" upgrades another copy
        self.install("pip")
        self.cache("pypi", "99.0.0")
        with mock.patch.object(registry_mod.CONFIG, "check_updates", True):
            note = registry_mod.update_status()
        self.assertTrue(note["command"].endswith(
            " -m pip install --upgrade colcon-dashboard"))
        self.assertIn(sys.executable, note["command"])

    def test_deb_install_shows_the_apt_version_with_the_apt_command(self):
        self.install("apt")
        self.cache("apt", "99.0.0")
        note = registry_mod.update_status()
        self.assertEqual((note["kind"], note["latest"], note["source"]),
                         ("upgrade", "99.0.0", "apt"))
        self.assertIn("apt install --only-upgrade python3-colcon-dashboard",
                      note["command"])

    def test_deb_install_ignores_a_pypi_answer(self):
        # PyPI has the release before the PPA builds it
        self.install("apt")
        self.cache("pypi", "99.0.0")
        self.assertIsNone(registry_mod.update_status())
        registry_mod._check_update_now.assert_called()

    def test_no_note_for_the_running_version(self):
        self.install("apt")
        self.cache("apt", __version__)
        self.assertIsNone(registry_mod.update_status())

    def test_restart_note_when_the_files_on_disk_are_newer(self):
        self.install("pip")  # no update check: the restart note still shows
        with mock.patch.object(registry_mod, "_disk_version", return_value="99.0.0"):
            note = registry_mod.update_status()
        self.assertEqual(note, {"kind": "restart", "latest": "99.0.0", "auto": True,
                                "current": __version__})

    def test_info_shows_a_cached_answer_also_with_the_check_off(self):
        # a click on "Check now" filled the cache: the settings show it
        self.install("pipx")
        self.cache("pypi", "99.0.0")
        info = registry_mod.update_info()
        self.assertFalse(info["auto"])
        self.assertEqual((info["current"], info["latest"], info["newer"], info["source"]),
                         (__version__, "99.0.0", True, "pypi"))
        self.assertEqual(info["command"], "pipx upgrade colcon-dashboard")
        self.assertIsNone(info["installed"])

    def test_info_before_the_first_check(self):
        self.install("apt")
        self.cache("pypi", "99.0.0")  # an answer for another install
        info = registry_mod.update_info()
        self.assertEqual((info["latest"], info["newer"], info["checked_at"]),
                         (None, False, None))
        self.assertIn("apt install --only-upgrade", info["command"])

    def test_info_shows_the_newer_files_on_disk(self):
        self.install("pip")
        with mock.patch.object(registry_mod, "_disk_version", return_value="99.0.0"):
            self.assertEqual(registry_mod.update_info()["installed"], "99.0.0")

    def test_check_now_runs_also_with_the_check_off(self):
        self.install("pipx")
        registry_mod._check_update_now.return_value = "99.0.0"
        info = registry_mod.check_update()
        registry_mod._check_update_now.assert_called_once_with("pypi")
        self.assertTrue(info["ok"])
        registry_mod._check_update_now.return_value = None
        self.assertFalse(registry_mod.check_update()["ok"])



class CheckNow(unittest.TestCase):
    """_check_update_now itself, with apt-cache stubbed."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(setattr, registry_mod, "CACHE_DIR", registry_mod.CACHE_DIR)
        registry_mod.CACHE_DIR = tmp.name

    def test_returns_the_answer_and_none_when_the_check_fails(self):
        with mock.patch.object(registry_mod, "_apt_candidate", return_value="0.12.0"):
            self.assertEqual(registry_mod._check_update_now("apt"), "0.12.0")
        with mock.patch.object(registry_mod, "_apt_candidate", return_value=None):
            self.assertIsNone(registry_mod._check_update_now("apt"))
        # a failed check keeps the earlier answer in the cache
        self.assertEqual(registry_mod._read_update()["latest"], "0.12.0")


class DiskVersion(unittest.TestCase):
    def test_equals_the_running_version(self):
        self.assertEqual(registry_mod._disk_version(), __version__)


class UpgradeRestart(unittest.TestCase):
    """The server restarts by itself into a newer version on disk."""

    def setUp(self):
        registry_mod._upgrade.update(seen=None, error=None)
        self.addCleanup(registry_mod._upgrade.update, seen=None, error=None)
        self.busy = False
        self.reg = mock.Mock(busy=lambda grace: self.busy)
        for p in (mock.patch.object(registry_mod, "_disk_version", return_value="99.0.0"),
                  mock.patch.object(registry_mod, "_pkg_stamp", return_value=(40, 900, 1.0)),
                  mock.patch.object(registry_mod, "_new_code_loads",
                                    return_value=(True, None))):
            setattr(self, p.attribute, p.start())
            self.addCleanup(p.stop)

    def look(self):
        with mock.patch("sys.stderr"):
            return registry_mod.upgrade_ready(self.reg)

    def test_waits_for_two_equal_looks_and_no_work(self):
        self.assertFalse(self.look())  # the upgrade can still write files
        self.busy = True
        self.assertFalse(self.look())  # a build, its end, or an analysis
        self.busy = False
        self.assertTrue(self.look())

    def test_files_that_still_change_wait(self):
        self.assertFalse(self.look())
        self._pkg_stamp.return_value = (41, 950, 2.0)
        self.assertFalse(self.look())
        self.assertTrue(self.look())

    def test_no_restart_for_the_running_version(self):
        self._disk_version.return_value = __version__
        for _ in range(3):
            self.assertFalse(self.look())
        self._new_code_loads.assert_not_called()

    def test_new_code_that_does_not_load_keeps_this_server(self):
        self._new_code_loads.return_value = (False, "SyntaxError: invalid syntax")
        for _ in range(4):
            self.assertFalse(self.look())
        # the note no longer promises a restart by itself
        self.assertFalse(registry_mod.update_status()["auto"])
        self._new_code_loads.return_value = (True, None)
        self.assertFalse(self.look())  # a new first look
        self.assertTrue(self.look())
        self.assertTrue(registry_mod.update_status()["auto"])

    def test_watch_restarts_once(self):
        restart = mock.Mock()
        with mock.patch.object(registry_mod, "upgrade_ready", side_effect=[False, True]), \
                mock.patch("sys.stderr"):
            registry_mod.watch_upgrade(self.reg, restart, look=0)
        restart.assert_called_once_with()

    def test_auto_restart_can_be_off(self):
        with mock.patch.object(registry_mod.CONFIG, "auto_restart", False):
            self.assertFalse(registry_mod.auto_restart_on())
            self.assertFalse(registry_mod.update_status()["auto"])
        self.assertTrue(registry_mod.auto_restart_on())  # unset: on

    def test_new_code_loads_needs_the_same_version(self):
        # a real Python that imports this package
        self.assertEqual(_NEW_CODE_LOADS(__version__), (True, None))
        ok, why = _NEW_CODE_LOADS("99.0.0")
        self.assertFalse(ok)
        self.assertEqual(why, "it loads version " + __version__)


class RegistryBusy(unittest.TestCase):
    """The work that a restart into an upgrade must not cut off."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = os.path.join(tmp.name, "ws")
        self.log = os.path.join(self.ws, "log", "build_2026-11-17_10-00-00",
                                "events.log")
        os.makedirs(os.path.dirname(self.log))
        with open(self.log, "w") as f:
            f.write("")
        self.reg = registry_mod.Registry()
        self.state = {"build_id": "build_2026-11-17_10-00-00", "active": False}
        self.mon = mock.Mock(lock=threading.Lock(), analyses={})
        type(self.mon).state_json = mock.PropertyMock(
            side_effect=lambda: json.dumps(self.state))
        self.reg.monitors[(self.ws, None)] = self.mon

    def test_a_running_build(self):
        self.state["active"] = True
        os.utime(self.log, (0, 0))
        self.assertTrue(self.reg.busy(120))

    def test_a_build_that_just_ended(self):
        # its notification, [notify] command, and prune run now
        self.assertTrue(self.reg.busy(120))
        old = time.time() - 300
        os.utime(self.log, (old, old))
        self.assertFalse(self.reg.busy(120))

    def test_a_running_analysis(self):
        os.utime(self.log, (0, 0))
        self.mon.analyses[("b", "pkg")] = mock.Mock(running=True)
        self.assertTrue(self.reg.busy(120))
        self.mon.analyses[("b", "pkg")].running = False
        self.assertFalse(self.reg.busy(120))


if __name__ == "__main__":
    unittest.main()
