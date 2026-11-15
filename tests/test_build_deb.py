"""
The .deb's layout and maintainer scripts, without dpkg: CI's `deb` job
builds the real package and installs, upgrades and removes it on systemd.
"""

import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "deb"))
sys.path.insert(0, os.path.join(ROOT, "server"))

import build_deb                                            # noqa: E402
import secretspace_setup                                    # noqa: E402
from version import __version__                             # noqa: E402


@pytest.fixture
def tree(tmp_path):
    return build_deb.stage(str(tmp_path / "tree"), build_deb.deb_version(__version__))


def read(tree, path):
    with open(os.path.join(tree, path.lstrip("/")), encoding="utf-8", newline="") as f:
        return f.read()


def test_the_files_are_where_an_install_by_hand_has_them(tree):
    files = sorted(os.path.relpath(os.path.join(d, n), tree).replace(os.sep, "/")
                   for d, _, names in os.walk(tree) for n in names)
    assert files == [
        "DEBIAN/control", "DEBIAN/postinst", "DEBIAN/postrm", "DEBIAN/preinst",
        "DEBIAN/prerm",
        "opt/secretspace/server/secretspace_server.py",
        "opt/secretspace/server/secretspace_setup.py",
        "usr/lib/systemd/system/secretspace-sync.service",
        "usr/sbin/secretspace-setup",
        "usr/share/doc/secretspace-server/copyright",
    ]
    # The paths the setup (and so `migrate`) and the unit use.
    assert build_deb.PROGRAM_DIR == secretspace_setup.PROGRAM_DIR + "/server"
    assert build_deb.CONFIG_DIR == secretspace_setup.CONFIG_DIR
    assert build_deb.DATA_DIR == secretspace_setup.DATA_DIR
    assert build_deb.SERVICE == secretspace_setup.SERVICE
    assert build_deb.USER == secretspace_setup.SERVICE_USER


def test_the_program_is_the_repositorys_byte_for_byte(tree):
    for name in build_deb.PROGRAM_FILES:
        with open(os.path.join(ROOT, "server", name), encoding="utf-8", newline="") as f:
            assert read(tree, f"{build_deb.PROGRAM_DIR}/{name}") == f.read()


def test_the_unit_is_the_one_migrate_writes(tree):
    # postinst removes a hand-installed /etc copy only when it is identical:
    # one written by `migrate` must be, or it would hide the package's.
    assert read(tree, build_deb.UNIT_PATH) == secretspace_setup.unit_text()


def test_control(tree):
    text = read(tree, "DEBIAN/control")
    fields = dict(line.split(": ", 1) for line in text.splitlines()
                  if line and not line.startswith(" "))
    assert fields["Package"] == "secretspace-server"
    assert fields["Version"] == build_deb.deb_version(__version__)
    assert fields["Architecture"] == "all"
    assert fields["Depends"].startswith("python3 (>= 3.10)")
    assert "openssl" in fields["Recommends"]
    assert int(fields["Installed-Size"]) > 50
    assert text.endswith("\n")


def test_deb_version():
    assert build_deb.deb_version("2.3.0") == "2.3.0"
    assert build_deb.deb_version("2.3.0-rc.1") == "2.3.0~rc.1"


def test_setup_command_runs_the_installed_setup_without_bytecode(tree):
    text = read(tree, "/usr/sbin/secretspace-setup")
    assert text.startswith("#!/bin/sh\n")
    assert f"/usr/bin/python3 -B {build_deb.PROGRAM_DIR}/secretspace_setup.py \"$@\"" in text


@pytest.mark.parametrize("name", ["preinst", "postinst", "prerm", "postrm"])
def test_scripts_are_posix_sh_with_set_e(tree, name):
    text = read(tree, f"DEBIAN/{name}")
    assert text.startswith("#!/bin/sh\nset -e\n")
    assert "\r" not in text
    sh = shutil.which("sh")
    if sh and sys.platform != "win32":
        result = subprocess.run([sh, "-n", os.path.join(tree, "DEBIAN", name)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["preinst", "postinst", "prerm", "postrm"])
def test_no_script_deletes_the_vaults_or_the_settings(tree, name):
    for line in read(tree, f"DEBIAN/{name}").splitlines():
        if line.strip().startswith("rm "):
            assert build_deb.DATA_DIR not in line and build_deb.CONFIG_DIR not in line, line


def test_postinst_starts_only_a_server_that_is_set_up(tree):
    text = read(tree, "DEBIAN/postinst")
    restart = text.index(f"systemctl restart {build_deb.SERVICE}")
    guard = text.rindex(f"if [ -f {build_deb.CONFIG_DIR}/sync.env ]", 0, restart)
    assert guard < restart
    # Folders are made only when missing, so an existing server keeps its modes.
    assert f"[ -d {build_deb.CONFIG_DIR} ] ||" in text
    assert "chown -R" not in text and "chmod" not in text


def test_postinst_removes_a_hand_copied_unit_only_when_identical(tree):
    text = read(tree, "DEBIAN/postinst")
    assert (f"if cmp -s {build_deb.LOCAL_UNIT} {build_deb.UNIT_PATH}; then\n"
            f"        rm -f {build_deb.LOCAL_UNIT}") in text


def test_preinst_refuses_a_server_from_before_the_rename(tree):
    text = read(tree, "DEBIAN/preinst")
    assert f"[ -d /etc/passman ] && [ ! -d {build_deb.CONFIG_DIR} ]" in text
    assert "migrate" in text and "exit 1" in text


def test_systemctl_only_where_systemd_runs(tree):
    for name in ("postinst", "prerm", "postrm"):
        text = read(tree, f"DEBIAN/{name}")
        if "systemctl" in text:
            assert "[ -d /run/systemd/system ]" in text, name
