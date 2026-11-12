"""
The version of the Linux server: the systemd unit, the setup and the
server as this repository ships them. Bump it on release and tag the
release commit v<version>.

It is kept apart from passman_server.py on purpose: that file is the same
in SecretSpace-Server-Windows, which has its own version.
"""

__version__ = "2.0.0"
