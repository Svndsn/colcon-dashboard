"""The update note (registry.update_status): apt for the deb package,
PyPI for other installs, and a restart note after an upgrade."""

import json
import os
import stat
import tempfile
import time
import unittest
from unittest import mock

from colcon_dashboard import __version__
from colcon_dashboard import registry as registry_mod
import tests.helpers  # noqa: F401  (it points CONFIG at a test path)

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
        self.assertEqual(note, {"kind": "restart", "latest": "99.0.0",
                                "current": __version__})



class DiskVersion(unittest.TestCase):
    def test_equals_the_running_version(self):
        self.assertEqual(registry_mod._disk_version(), __version__)


if __name__ == "__main__":
    unittest.main()
