# PassMan sync server for Linux

A place to keep your encrypted vault so two PCs can stay in step. It stores
one blob per user, numbers each revision, and refuses a write computed against
an old one.

**It cannot read your passwords.** The client encrypts the vault with your
master password before anything is sent, so this process holds AES-256-GCM
ciphertext and no key. There is no account system, no password reset and no
recovery path here, by design — the only secret that matters never leaves
your PC.

Standard library only: no `pip install`, no virtualenv, nothing to keep
patched beyond Python itself.

This repository is the server for **Linux**, run by systemd. The other
parts of PassMan have their own repositories:

| Repository | What it holds |
|---|---|
| [PassMan-Client-Windows](https://github.com/usermaneGermane/PassMan-Client-Windows) | the app for Windows — what your PCs run |
| [PassMan-Client-Linux](https://github.com/usermaneGermane/PassMan-Client-Linux) | the app for Linux — from source or a .deb package |
| [PassMan-Server-Windows](https://github.com/usermaneGermane/PassMan-Server-Windows) | the same server for Windows, with an installer |
| **PassMan-Server-Linux** (this one) | the server for Linux |

## Before you start

You need:

- **A machine that stays on**, with `python3` 3.7 or newer — Ubuntu
  already has it, check with `python3 --version`.
- **Its address**, as your PCs will reach it. Run `ip -4 addr show` on the
  server and look past `127.0.0.1`: on a home network it is something like
  `192.168.1.50/24` on `eth0` or `enp…`; behind a VPN it is the address on
  `wg0` or `tun0`.
- **A fixed address.** Set a DHCP reservation for the server in your router.
  If its address ever changes, every PC's sync setting stops working.

The steps below use `192.168.1.50` for the server, `192.168.1.0/24` for
the network it sits on and `8787` for the port. **Replace them with yours.**
The setup in step 2 prints your exact address, network and port, and the
firewall line to go with them. If `ip` shows your address ending in `/24` —
the usual case at home — the network is the same address with the last
number set to `0`: `192.168.0.3/24` means `192.168.0.0/24`.

## Install on Ubuntu

### 1. Get the code

```bash
git clone --depth 1 https://github.com/usermaneGermane/PassMan-Server-Linux.git ~/PassMan-Server-Linux
```

Or download `passman-server-linux-<version>.tar.gz` from
[Releases](https://github.com/usermaneGermane/PassMan-Server-Linux/releases)
and unpack it; use that folder wherever these steps say
`~/PassMan-Server-Linux`.

This is only the source. The running service gets its own copy in step 2, so
nothing you do in this folder later — pulling, switching branches, deleting
it — touches the live server until you choose to update it.

### 2. Service user, folders, address, port and token

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin passman
sudo mkdir -p /opt/passman/server /var/lib/passman/store /etc/passman
sudo cp ~/PassMan-Server-Linux/server/passman_server.py ~/PassMan-Server-Linux/server/passman_setup.py /opt/passman/server/
sudo chown -R passman:passman /var/lib/passman

sudo python3 /opt/passman/server/passman_setup.py
```

If `useradd` says the user already exists, carry on.

The setup asks two things:

- **Which network to listen on.** It lists this machine's networks, e.g.
  `eth0 only (192.168.1.50/24)`. Press Enter for the default, **every
  network** (`0.0.0.0`): it works on a LAN and behind a VPN at once, and
  does not care which network comes up first at boot. Step 4 limits who can
  connect.
- **The port** the PCs connect on. Press Enter for `8787`, or type another
  from 1024 to 65535.

It writes both to `/etc/passman/sync.env`, which the service reads, and
creates the token in `/etc/passman/token` (readable by `passman` only). If
ufw is already on, it adds the firewall rule for step 4 itself; if not, it
prints the lines to run. At the end it prints the address to enter on your
PCs. Run it again any time to change the address or port — see
[Changing the address or port](#changing-the-address-or-port).

Why the copy into `/opt` rather than running from `~/PassMan-Server-Linux`: the service
unit sets `ProtectHome=yes`, which hides `/home` from it entirely, and on
recent Ubuntu home folders are not readable by other users anyway. Run it
from your home folder and it fails with "file not found".

The token is the one shared secret between the server and your PCs. It is
never passed on the command line, which every user on the machine can read
through `ps`.

### 3. Run it by hand first

With the address and port you chose in step 2 (`0.0.0.0` means every
network):

```bash
sudo -u passman python3 /opt/passman/server/passman_server.py \
    --host 0.0.0.0 --port 8787 \
    --store /var/lib/passman/store --token-file /etc/passman/token
```

It prints a note about plain HTTP; that is expected (see
[Plain HTTP or TLS](#plain-http-or-tls)). If `sudo ufw status` already
says `active` on this machine, run the `allow from …` line from step 4 first,
or the check below is blocked. Leave the server running and, from one of your
PCs, check it answers. In Windows PowerShell use `curl.exe` — plain
`curl` there is an alias for something else:

```
curl.exe http://192.168.1.50:8787/health
```

You want `{"ok": true, "service": "passman-sync"}`. If it fails,
`Test-NetConnection 192.168.1.50 -Port 8787` tells you more: `PingSucceeded`
says whether the PC can reach the server at all, `TcpTestSucceeded` whether
the port answers. See [Troubleshooting](#troubleshooting).

Then stop the server with **Ctrl+C** — the service in step 5 needs the port
free.

### 4. Limit who can connect

Listening on every network (`0.0.0.0`) means exactly that. Your router
already keeps the internet out unless you forward the port, and without the
token every request is refused anyway — this step is a second layer, for the
day the router exposes the machine by accident (UPnP, a "DMZ host" setting, a
forward someone adds) or the machine joins another network. Pick **one**:

**A — Firewall (recommended).** Check first whether ufw is already on:

```bash
sudo ufw status
```

If it says `active`, you are done: the setup in step 2 already added the
rule (`sudo ufw status` lists it). If it says `inactive`, run these three,
**in this order** — the setup printed the middle one with your network and
port, and never switches ufw on itself, for the reason in the warning below:

```bash
sudo ufw allow OpenSSH
sudo ufw allow from 192.168.1.0/24 to any port 8787 proto tcp
sudo ufw enable
```

> ⚠️ `ufw enable` blocks every incoming connection you have not allowed. If
> you are logged in over SSH and skip the first line, your session drops and
> you cannot get back in without a keyboard and screen on the server. The
> first line keeps SSH as it is, on port 22 — it does not move it.

**B — Listen on your LAN address only.** No firewall involved. Run the setup
again and pick the LAN network instead of every network:

```bash
sudo python3 /opt/passman/server/passman_setup.py
```

The catch: if that address changes, the service no longer starts, so the
DHCP reservation stops being a nicety and becomes a requirement.

### 5. Install it as a service

```bash
sudo cp ~/PassMan-Server-Linux/server/passman-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now passman-sync
systemctl status passman-sync
```

You want `active (running)`. Run the `curl.exe` check from step 3 again; at
some point, reboot and check it comes back by itself.

The unit ships with the paths from step 2 and takes the address and port from
`/etc/passman/sync.env`, so it works as copied — there is no port in it to
edit. If it fails with `Failed to load environment files`, step 2's setup
has not been run.

### 6. Connect PassMan

Show the token and copy it:

```bash
sudo cat /etc/passman/token
```

**First PC:** unlock your vault, open **Settings → Sync**, enter the address
the setup printed, e.g. `http://192.168.1.50:8787`, and the token, and press **Save & sync**. It checks
the connection, stores the settings only once the server answers, and uploads
the vault. The address and token are kept **inside your vault**, which is
encrypted — not in `config.json`, which is not.

**Second PC:** on the login screen choose **Restore from server**, and enter
the same address and token, your username and your master password. After
that, press **Sync** on either PC whenever you like.

### 7. Check it worked

```bash
sudo ls -l /var/lib/passman/store/*/     # vault.enc appears after the first sync
journalctl -u passman-sync -n 20         # recent requests
```

The access log records usernames and status codes — never the vault, never
the token.

## Changing the address or port

```bash
sudo python3 /opt/passman/server/passman_setup.py
```

It offers the current values — press Enter to keep one — rewrites
`/etc/passman/sync.env` and restarts the service. With ufw on, it also swaps
the firewall rule: the old network/port rule goes, the new one comes in.
What is left is the new address in Settings → Sync on every PC, in every
synced vault.

For a script, skip the questions: `… passman_setup.py setup --host 0.0.0.0
--port 9443`, or `… setup --keep --port 9443` to change only the port.

## Letting in a PC from another network

The firewall rule covers the networks this machine is on. A PC elsewhere —
behind a router, on a VPN the server is not part of — needs its own rule.
The setup's third question asks for those addresses, or give them directly:

```bash
sudo python3 /opt/passman/server/passman_setup.py setup --keep --allow-from 192.168.0.1
```

Name one address or a network (`10.20.0.0/24`); repeat `--allow-from` or
separate them with commas for more, and `--allow-from none` removes them.
They are saved in `sync.env` as `PASSMAN_ALLOW_FROM`, so a later port change
moves their rules too. Only the firewall changes: the service is not
restarted. A rule you had already typed by hand for the same address and
port is taken over (ufw skips the duplicate); one for another port stays
until you delete it: `sudo ufw status numbered`, then `sudo ufw delete N`.

## If the token leaks

```bash
sudo python3 /opt/passman/server/passman_setup.py new-token
```

It asks for confirmation, writes a new random token to `/etc/passman/token`,
restarts the service and prints the new value. From then on the old token is
refused everywhere. On each PC, unlock each synced vault, open **Settings →
Sync**, paste the new token, keep the address, and press **Save & sync**.

A leaked token lets someone read and overwrite the encrypted blobs, never
decrypt them — but replace it anyway, and if the vault might have been
copied, change the master password too.

## Updating

When `main` has changed:

```bash
cd ~/PassMan-Server-Linux && git pull
sudo cp server/passman_server.py server/passman_setup.py /opt/passman/server/
sudo systemctl restart passman-sync
```

Vaults in `/var/lib/passman/store`, the token in `/etc/passman/token` and
the settings in `/etc/passman/sync.env` are untouched by an update.

**Updating from a server without `passman_setup.py`** (before the address and
port moved into `sync.env`): the new unit file has no `--host`/`--port` and
will not start without `sync.env`, so do it in this order:

```bash
cd ~/PassMan-Server-Linux && git pull
sudo cp server/passman_server.py server/passman_setup.py /opt/passman/server/
sudo python3 /opt/passman/server/passman_setup.py    # Enter, Enter keeps 0.0.0.0 and 8787
sudo cp server/passman-sync.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart passman-sync
```

The setup keeps your existing token. If you had used `sed` to put your LAN
address in the old unit, pick that network in the setup instead.

**If your checkout is of the old `PassMan` repository** (the one that held
the app and the server together, cloned to `~/PassMan`): it gets no more
server updates. Clone this repository as in [step 1](#1-get-the-code) and
update from it as above — the running copy in `/opt/passman`, the token,
the settings and the vaults stay as they are. Then delete `~/PassMan` when
you like.

**Update the server before changing a master password** in PassMan. The
server now records how many times each vault's password has changed; an older
server does not, and after a second change it can send a PC the wrong way —
told to adopt a password that is really its own previous one. If `passman-sync.service` itself changed, copy it
again and run `sudo systemctl daemon-reload` before the restart.

## Troubleshooting

**Start here if a PC cannot connect.** Check the server side first — most
failures are simply that nothing is running. Use your port if it is not 8787
(`cat /etc/passman/sync.env` shows it):

```bash
sudo ss -tlnp | grep 8787                 # anything listening? no output = not running
curl http://127.0.0.1:8787/health         # does it answer on the server itself?
systemctl status passman-sync --no-pager
```

On Windows, a refused connection can still take about 20 seconds to fail —
Windows retries before giving up — so a slow `curl.exe` failure does **not**
by itself mean a firewall is dropping it. Check the server before the
firewall.

| Symptom | Likely cause |
|---|---|
| Nothing listening on 8787; local `curl` refused | The server is not running: `sudo systemctl start passman-sync`, then read `journalctl -u passman-sync -n 50` if it will not stay up |
| `curl` works on the server but not from a PC | Firewall: `sudo ufw status`, and check the network in the `allow` rule matches yours |
| `Test-NetConnection` shows `PingSucceeded: False` | The PC cannot reach the server at all — different networks, or a wrong address. Compare with `ipconfig` on the PC |
| Service restarts over and over | `journalctl -u passman-sync -n 50`. Usually the token file's path or permissions, or `PASSMAN_HOST` in `sync.env` set to an address this machine no longer has — run the setup again |
| `Failed to load environment files` | `/etc/passman/sync.env` is missing — run `sudo python3 /opt/passman/server/passman_setup.py` |
| `PASSMAN_PORT must be a port number` in the log | `sync.env` was edited by hand into something that is not a port — run the setup again |
| `Cannot read the token file` in the log | `/etc/passman/token` is missing, or not owned by `passman` — redo the `chown` in step 2 |
| `Address already in use` | Something else on the port — often the hand-started copy from step 3 still running |
| PassMan: "rejected the sync token" | A stray space or line break when pasting; copy it again. Or the token was replaced with `new-token` — paste the new one |
| PassMan: "Could not reach …" | Wrong address or port in Settings → Sync, the PC is on another network, or the firewall is blocking it |
| It worked, then stopped | The server's address changed — see below |
| PassMan asks for a master password when you press Sync | Expected after a password change on another PC (or on this one while offline) — see [Changing the master password](https://github.com/usermaneGermane/PassMan-Client-Windows#changing-the-master-password-of-a-vault-you-sync) |

## If the server's address changes

Listening on every network (`0.0.0.0`), the service itself needs nothing: it
listens on whatever address the machine has. Three other things do:

1. **Firewall.** If the new address is on a different network, allow it and
   drop the old rule:
   ```bash
   sudo ufw allow from 192.168.0.0/24 to any port 8787 proto tcp   # the new network
   sudo ufw delete allow from 192.168.1.0/24 to any port 8787 proto tcp
   ```
   If you used step 4B instead, run the setup again and pick the new
   address; it restarts the service.
2. **Every PC, every vault.** The address is stored inside each vault, so on
   each PC unlock each synced vault, open Settings → Sync, enter the new
   address, keep the token, and press **Save & sync**.
3. **A DHCP reservation**, so it does not change again. If `ip -4 addr show`
   says `dynamic` next to the address, the server is still getting it from
   DHCP.

## Removing a vault

A vault lives in two kinds of place: each PC that syncs it, and its folder on
the server. Removing only the server's copy does not get rid of it — the next
time any of those PCs syncs, it sees an empty server and **uploads the vault
again**. That is deliberate: an empty server can just as well be a new
server or a lost disk, and wiping your PCs in response would be the one
outcome that loses data.

To get rid of a vault for good:

1. **On every PC that has it:** if you might want it back one day, save a
   copy first (Settings → *Save encrypted backup*). Then unlock it and use
   Settings → **Delete this user**, which removes the vault, its backup and
   its sync state on that PC.
2. **Then on the server:**
   ```bash
   sudo ls /var/lib/passman/store/              # check the exact name
   sudo rm -r /var/lib/passman/store/<username>
   ```
   This removes the current copy, `meta.json` and all its history. The
   service does not need stopping; it reads the files on every request.

PCs first, server second: the other way round, a PC that syncs in between
simply puts it back.

> PassMan builds from before this was fixed did the opposite — a PC syncing
> against a server whose copy had been removed **deleted every entry on the
> PC**. If your PCs have not been rebuilt since, follow the order above
> strictly. To recover from it: close PassMan without saving anything else,
> then copy `vault\<username>.vault.enc.bak` over
> `vault\<username>.vault.enc` — the backup holds the version from just
> before that sync, until the next save replaces it.

## Where things live

| Path | What |
|---|---|
| `/opt/passman/server/passman_server.py` | the running copy of the server |
| `/opt/passman/server/passman_setup.py` | the setup: address, port, `new-token` |
| `/etc/systemd/system/passman-sync.service` | the service definition |
| `/etc/passman/sync.env` | the address and port (`PASSMAN_HOST`, `PASSMAN_PORT`) |
| `/etc/passman/token` | the shared token (`600`, owned by `passman`) |
| `/var/lib/passman/store/` | the encrypted vaults and their history |
| `~/PassMan-Server-Linux/` | your git checkout — only the source |

## LAN or VPN

Nothing in the server cares which. What changes is the address your PCs type
into Settings → Sync, and what you allow through the firewall:

- **Same home network:** the server's LAN address, e.g.
  `http://192.168.1.50:8787`, and allow the LAN range in step 4.
- **Over a VPN:** the server's address *on the VPN*, e.g.
  `http://10.8.0.1:8787`, and allow the VPN's range or interface instead:
  `sudo ufw allow in on wg0 to any port 8787 proto tcp`.

Both at once work too — add one `allow` rule per network. Keep every network
(`0.0.0.0`) in the setup in that case: binding the VPN address directly makes
the service fail at boot whenever it starts before the VPN interface is up.

## Plain HTTP or TLS

Your vault is encrypted before it leaves your PC, so nothing on the network
can read your passwords whether or not TLS is on. What plain HTTP exposes is
the **sync token**: someone else on the same network could capture it, then
read or overwrite the encrypted blobs — without being able to decrypt them.
On a home network or a VPN you trust, that is usually acceptable.

To protect the token too, add TLS with a self-signed certificate that the
client pins. The `subjectAltName` must be the address the PCs connect to:

```bash
cd /etc/passman
sudo openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
    -keyout server.key -out server.crt -subj "/CN=passman.internal" \
    -addext "subjectAltName=IP:192.168.1.50"
sudo chown passman:passman server.key server.crt
sudo chmod 600 server.key
```

Then add `--cert /etc/passman/server.crt --key /etc/passman/server.key` to
the `ExecStart` line of the unit, reload and restart. Copy `server.crt` to
each PC, set it as the certificate file in Settings → Sync, and change the
address to `https://`.

The client pins that certificate rather than switching verification off, so
a machine impersonating the server is refused. Without the `subjectAltName`
the certificate will not validate against an IP address at all — modern TLS
stacks ignore `CN`.

## Running it without systemd

For a quick try-out, from the checkout:

```bash
cd ~/PassMan-Server-Linux/server
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > token
chmod 600 token
python3 passman_server.py --host 0.0.0.0 --port 8787
```

The token is read from `server/token` and vaults land in `server/store/`;
both are gitignored. It stops when you close the terminal, so use the
service for anything real.

## API

Every route but `/health` needs `Authorization: Bearer <token>`.

| Route | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | liveness; no token needed |
| `/vault/<user>/meta` | GET | `{revision, sha256, updated_at, size, key_generation}` — cheap poll |
| `/vault/<user>` | GET | the blob plus its metadata; `blob: null` if nothing stored |
| `/vault/<user>` | PUT | store a new revision |

`PUT` takes `{"blob": "<base64>"}` and requires `If-Match: <revision>` — the
revision you merged against. Two optional headers:

- `X-PassMan-Key-Generation: <n>` — how many times the vault's master
  password has changed. Stored as-is; kept unchanged when absent.
- `X-PassMan-Drop-History: 1` — discard every earlier revision, including
  the one being replaced. Sent after a password change.

The server replies:

- **200** with the new metadata,
- **409** if it has moved on (pull, merge again, retry),
- **428** if `If-Match` was missing on a vault that already exists.

A first push may omit `If-Match`. `If-Match: *` overwrites whatever is there,
which the client never sends — it exists for recovering by hand.

## What it keeps

Inside the store directory (`/var/lib/passman/store` with the service):

```
<user>/vault.enc        the current blob — encrypted
<user>/meta.json        revision, sha256, timestamp, key generation — not encrypted
<user>/history/*.enc    the last 20 revisions — encrypted
```

One folder per PassMan username, so several vaults can share one server
without touching each other. `vault.enc` and the history are the same
AES-256-GCM files as on the PCs; the server never has the key. `meta.json`
and the folder name are plain: they reveal the username, when it last synced
and roughly how large the vault is — never an entry.

Each history file stays encrypted with the master password in use when it was
written. When you change a master password, PassMan offers to delete them —
ticked by default — since they would still open with the old one. The key
generation in `meta.json` counts those changes; it holds nothing secret, and
lets a PC tell whether the copy here is under an older or a newer password
than its own.

History is server-side undo, in the same spirit as the client's archive. To
roll back: `sudo systemctl stop passman-sync`, copy the revision you want over
`vault.enc` (keeping it owned by `passman`), delete `meta.json` so the
numbering restarts, and start the service again. Every client then sees a
revision it did not expect and re-merges, which is the safe outcome.

## Backups

This server is not a backup. It holds one copy of a file your PCs also hold,
and it will happily store a vault you damaged. Keep `/var/lib/passman/store`
in whatever backs up the rest of the machine — the contents are encrypted, so
a backup of it is no more sensitive than the vault itself.

## What it does not do

No rate limiting, and no access logging beyond the basics; put it behind
nginx or Caddy if you want those. No multi-user isolation beyond the username
in the path — everyone with the token can read every user's blob, so treat
the token as a single trust boundary. No push notification: the client syncs
when you press the button.

## Versions

The Linux server has its own version, in `server/version.py`, and each
release is tagged `v<version>` (1.3.0 when the repositories were split). It
is separate from the app's and from the Windows server's: compare a server
and an app by what they can do, not by their numbers.

## Development

```
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests never touch the real `/etc`: they point `--config-dir` at a
temporary folder and fake `ip`, `systemctl` and `ufw`. GitHub Actions runs
them on Ubuntu for every pull request and every push to `main`.

`tests/test_server_http.py` talks to a real server on a free port of
127.0.0.1, with no client involved: the token, which paths exist, If-Match
(including two pushes racing for one revision), malformed and oversized
bodies, the history limit and the access log. It is the same file in
PassMan-Server-Windows.

`server/passman_server.py` and `server/passman_setup.py` are the same files
as in PassMan-Server-Windows — `passman_setup.py` holds the setup for both
systems. Make a change to either in both repositories, so the two servers
never drift apart. PassMan-Client-Windows and PassMan-Client-Linux each keep
a copy of `passman_server.py` for their end-to-end sync tests; refresh
those too.

## License

MIT — see [LICENSE](LICENSE).
