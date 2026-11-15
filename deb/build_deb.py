"""
Build the SecretSpace Server .deb on Debian or Ubuntu:

    python3 deb/build_deb.py

writes build/secretspace-server_<version>_all.deb. Install it with

    sudo apt install ./build/secretspace-server_<version>_all.deb

or from the SecretSpace apt repository (README.md). Needs dpkg-deb, which
every Debian and Ubuntu has. Standard library only, like the server.

What the package holds - the same paths as the install by hand in README.md,
so the package can take over a server set up that way:

    /opt/secretspace/server/secretspace_server.py   the server
    /opt/secretspace/server/secretspace_setup.py    its setup
    /usr/sbin/secretspace-setup                     runs the setup
    /usr/lib/systemd/system/secretspace-sync.service
    /usr/share/doc/secretspace-server/copyright

What it does NOT hold, and never removes: the settings and the token
(/etc/secretspace, written by the setup) and the vaults (/var/lib/secretspace).
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER_DIR = os.path.join(ROOT, "server")

PACKAGE = "secretspace-server"
SERVICE = "secretspace-sync"
USER = "secretspace"
PROGRAM_DIR = "/opt/secretspace/server"
CONFIG_DIR = "/etc/secretspace"
DATA_DIR = "/var/lib/secretspace"
UNIT_PATH = f"/usr/lib/systemd/system/{SERVICE}.service"
#: Where an install by hand (and `migrate`) put the unit.
LOCAL_UNIT = f"/etc/systemd/system/{SERVICE}.service"
PROGRAM_FILES = ("secretspace_server.py", "secretspace_setup.py")
MAINTAINER = "usermaneGermane <scoop-shabby-wad@duck.com>"
HOMEPAGE = "https://github.com/usermaneGermane/SecretSpace-Server-Linux"
REPO_URL = HOMEPAGE

#: Ubuntu 22.04 ships Python 3.10, the oldest the server supports.
DEPENDS = ["python3 (>= 3.10)", "passwd"]
#: openssl makes the certificate of the `tls` command; ufw is the firewall
#: the setup adds its rule to when it is on.
RECOMMENDS = ["openssl"]
SUGGESTS = ["ufw"]

# -B: no __pycache__ in /opt when root runs the setup (it imports the server).
SETUP_COMMAND = f"""#!/bin/sh
exec /usr/bin/python3 -B {PROGRAM_DIR}/secretspace_setup.py "$@"
"""

# A server from before the rename (PassMan, older than 2.1.0) has its files
# in /opt|/etc|/var/lib/passman. `migrate` moves them, and refuses while the
# new folders exist - which this package would create. So: migrate first.
PREINST = f"""#!/bin/sh
set -e
if [ "$1" = install ] || [ "$1" = upgrade ]; then
    if [ -d /etc/passman ] && [ ! -d {CONFIG_DIR} ]; then
        cat >&2 <<'EOF'

This machine has a sync server from before SecretSpace Server 2.1.0 (when it
was called PassMan): /etc/passman. Give it the current names first, then
install this package again:

    git clone --depth 1 {REPO_URL}.git ~/SecretSpace-Server-Linux
    sudo python3 ~/SecretSpace-Server-Linux/server/secretspace_setup.py migrate

(README.md, "Updating a server from before 2.1.0".) Nothing was changed.

EOF
        exit 1
    fi
fi
"""

POSTINST = f"""#!/bin/sh
set -e
if [ "$1" != configure ]; then
    exit 0
fi

# Bytecode left by running the setup with plain python3 (an install by hand).
rm -rf {PROGRAM_DIR}/__pycache__

if ! getent group {USER} >/dev/null; then
    groupadd --system {USER}
fi
if ! getent passwd {USER} >/dev/null; then
    useradd --system --gid {USER} --no-create-home --home-dir /nonexistent \\
        --shell /usr/sbin/nologin {USER}
fi
# Made only when missing: an existing server keeps its owners and modes.
[ -d {CONFIG_DIR} ] || install -d -m 0755 {CONFIG_DIR}
for dir in {DATA_DIR} {DATA_DIR}/store; do
    [ -d "$dir" ] || install -d -o {USER} -g {USER} -m 0755 "$dir"
done

# A server installed by hand (or moved by `migrate`) has its own copy of the
# unit in /etc, which would hide this package's. It goes only when it is the
# same; a changed one stays, and wins, as systemd intends.
if [ -f {LOCAL_UNIT} ]; then
    if cmp -s {LOCAL_UNIT} {UNIT_PATH}; then
        rm -f {LOCAL_UNIT}
        echo "Removed {LOCAL_UNIT}: it is the same as the package's."
    else
        echo "Note: {LOCAL_UNIT} differs from the package's unit and is used"
        echo "instead of it. Remove it to use the package's:"
        echo "    sudo rm {LOCAL_UNIT} && sudo systemctl daemon-reload"
    fi
fi

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi

if [ -f {CONFIG_DIR}/sync.env ]; then
    # Set up already (an upgrade, or a server installed by hand): run the
    # new version.
    if [ -d /run/systemd/system ]; then
        systemctl enable {SERVICE} >/dev/null 2>&1 || true
        if systemctl restart {SERVICE}; then
            echo "Restarted {SERVICE}."
        else
            echo "Could not start {SERVICE}. Look at: journalctl -u {SERVICE} -n 50"
        fi
    fi
else
    cat <<'EOF'

SecretSpace Server is installed. Set it up and start it:

    sudo secretspace-setup                       # address, port, token, firewall
    sudo systemctl enable --now {SERVICE}

Then turn HTTPS on with: sudo secretspace-setup tls
EOF
fi
"""

PRERM = f"""#!/bin/sh
set -e
if [ "$1" = remove ] && [ -d /run/systemd/system ]; then
    systemctl disable --now {SERVICE} >/dev/null 2>&1 || true
fi
# Left by running the setup with plain python3 instead of secretspace-setup.
rm -rf {PROGRAM_DIR}/__pycache__
"""

POSTRM = f"""#!/bin/sh
set -e
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload >/dev/null 2>&1 || true
fi
if [ "$1" = purge ]; then
    echo "Kept: the vaults in {DATA_DIR}, the token and settings in"
    echo "{CONFIG_DIR}, and the user {USER}. Delete them yourself if you"
    echo "are sure you no longer need the vaults."
fi
"""

COPYRIGHT = f"""\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: SecretSpace Server
Source: {HOMEPAGE}

Files: *
Copyright: usermaneGermane
License: GPL-3.0-only
 SecretSpace Server is free software under the GNU General Public License,
 version 3 only. On Debian systems its text is in
 /usr/share/common-licenses/GPL-3.
"""


def read_version(server_dir=SERVER_DIR):
    with open(os.path.join(server_dir, "version.py"), encoding="utf-8") as f:
        match = re.search(r'^__version__\s*=\s*"([^"]+)"', f.read(), re.M)
    if not match:
        raise SystemExit("no __version__ in server/version.py")
    return match.group(1)


def deb_version(version: str) -> str:
    """2.3.0-rc.1 -> 2.3.0~rc.1: a tilde sorts before the release."""
    return version.replace("-", "~", 1)


def control(version, installed_size_kb):
    return (
        f"Package: {PACKAGE}\n"
        f"Version: {version}\n"
        "Architecture: all\n"
        f"Maintainer: {MAINTAINER}\n"
        f"Installed-Size: {installed_size_kb}\n"
        f"Depends: {', '.join(DEPENDS)}\n"
        f"Recommends: {', '.join(RECOMMENDS)}\n"
        f"Suggests: {', '.join(SUGGESTS)}\n"
        "Section: net\n"
        "Priority: optional\n"
        f"Homepage: {HOMEPAGE}\n"
        "Description: sync server for the SecretSpace password manager\n"
        " Keeps SecretSpace accounts and vaults in step across devices and\n"
        " people. It stores them encrypted and never has a key to open them.\n"
        " One Python file, standard library only, run by systemd as its own\n"
        " user; `secretspace-setup` sets the address, port, token, firewall\n"
        " rule and HTTPS.\n"
    )


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.chmod(path, mode)


def unit_file(server_dir=SERVER_DIR):
    with open(os.path.join(server_dir, f"{SERVICE}.service"),
              encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def stage(tree, version, server_dir=SERVER_DIR):
    """Lay out the package's files under ``tree`` (the future /)."""
    program = os.path.join(tree, PROGRAM_DIR.lstrip("/"))
    os.makedirs(program)
    for name in PROGRAM_FILES:
        with open(os.path.join(server_dir, name), encoding="utf-8") as f:
            write(os.path.join(program, name), f.read().replace("\r\n", "\n"),
                  0o755 if name == "secretspace_setup.py" else 0o644)
    write(os.path.join(tree, "usr", "sbin", "secretspace-setup"),
          SETUP_COMMAND, 0o755)
    write(os.path.join(tree, UNIT_PATH.lstrip("/")), unit_file(server_dir))
    write(os.path.join(tree, "usr", "share", "doc", PACKAGE, "copyright"),
          COPYRIGHT)

    size = 0
    for folder, _, files in os.walk(tree):
        size += sum(os.path.getsize(os.path.join(folder, n)) for n in files)
    debian = os.path.join(tree, "DEBIAN")
    write(os.path.join(debian, "control"),
          control(version, max(1, (size + 1023) // 1024)))
    for name, text in (("preinst", PREINST), ("postinst", POSTINST),
                       ("prerm", PRERM), ("postrm", POSTRM)):
        write(os.path.join(debian, name), text, 0o755)
    return tree


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the SecretSpace Server .deb.")
    parser.add_argument("--out", default=os.path.join(ROOT, "build"),
                        help="folder for the .deb (default: build/)")
    args = parser.parse_args(argv)

    if not shutil.which("dpkg-deb"):
        raise SystemExit("dpkg-deb not found: build the package on Debian or Ubuntu")

    version = deb_version(read_version())
    os.makedirs(args.out, exist_ok=True)
    deb = os.path.join(args.out, f"{PACKAGE}_{version}_all.deb")
    with tempfile.TemporaryDirectory(prefix="secretspace-server-deb-") as tmp:
        tree = stage(os.path.join(tmp, "tree"), version)
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build",
                        tree, deb], check=True)
    print(deb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
