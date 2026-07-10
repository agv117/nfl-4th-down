"""Deploy the NFL 4th-Down Decision Bot to anandvaghasia.com/nfl-4th-down/ via FTPS.

Reads ANANDVAGHASIA_FTP_* from ~/.claude/secrets.env.
Uploads ONLY into /nfl-4th-down/. Never touches /certs/ or anything else.
"""
import os
import sys
from ftplib import FTP_TLS, FTP
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
SECRETS = Path.home() / ".claude" / "secrets.env"
REMOTE_SLUG = "nfl-4th-down"          # under the FTP user's homedir (public_html)

FILES = ["index.html", "styles.css", "app.js", "wp_grid.json", "tables.json", "coaches.json"]


def load_secrets(path):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def connect(host, user, pw):
    for klass in (FTP_TLS, FTP):
        try:
            ftp = klass()
            ftp.connect(host, 21, timeout=30)
            ftp.login(user, pw)
            if isinstance(ftp, FTP_TLS):
                try:
                    ftp.prot_p()
                except Exception:
                    pass
            print(f"connected via {klass.__name__}")
            return ftp
        except Exception as e:
            print(f"{klass.__name__} failed: {e}")
    raise SystemExit("could not connect")


def main():
    env = load_secrets(SECRETS)
    host = env.get("ANANDVAGHASIA_FTP_HOST")
    user = env.get("ANANDVAGHASIA_FTP_USER")
    pw = env.get("ANANDVAGHASIA_FTP_PASS")
    if not (host and user and pw):
        raise SystemExit("missing ANANDVAGHASIA_FTP_* in secrets.env")

    for f in FILES:
        if not (WEB / f).exists():
            raise SystemExit(f"missing build artifact: web/{f} (run the pipeline first)")

    ftp = connect(host, user, pw)
    try:
        # homedir is public_html; make + enter our slug ONLY.
        try:
            ftp.mkd(REMOTE_SLUG)
        except Exception:
            pass
        ftp.cwd(REMOTE_SLUG)
        cwd = ftp.pwd()
        assert REMOTE_SLUG in cwd, f"refusing to upload outside slug (cwd={cwd})"
        total = 0
        for f in FILES:
            with open(WEB / f, "rb") as fh:
                ftp.storbinary(f"STOR {f}", fh)
            sz = (WEB / f).stat().st_size
            total += sz
            print(f"uploaded {f} ({sz:,} bytes)")
        print(f"\ntotal {total:,} bytes")
        print("live: https://anandvaghasia.com/nfl-4th-down/")
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


if __name__ == "__main__":
    main()
