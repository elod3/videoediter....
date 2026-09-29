"""Administrare din terminal pentru fondator (suport manual, până există email):

    vedit-admin users                        # conturile, cu credite
    vedit-admin credits ana@x.ro 10 "bonus"  # adaugă (sau scade, cu minus) credite, cu motiv în istoric
    vedit-admin reset-password ana@x.ro      # parolă temporară nouă + deloghează toate sesiunile

Lucrează direct pe VEDIT_HOME/vedit.db (rulează-l pe server, cu același VEDIT_HOME ca vedit-server).
"""
from __future__ import annotations

import argparse
import secrets
import sys

from ..project import home
from .auth import hash_password
from .db import DB


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vedit-admin", description="Administrare conturi vedit.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("users", help="listează conturile")
    c = sub.add_parser("credits", help="adaugă / scade credite")
    c.add_argument("email")
    c.add_argument("delta", type=int)
    c.add_argument("reason", nargs="?", default="ajustare manuală")
    r = sub.add_parser("reset-password", help="parolă temporară nouă")
    r.add_argument("email")
    args = ap.parse_args(argv)

    db = DB(home() / "vedit.db")
    if args.cmd == "users":
        for u in db._q("SELECT id, email, credits FROM users ORDER BY id"):
            print(f"{u['id']:>5}  {u['credits']:>6} credite  {u['email']}")
        return 0
    user = db.user_by_email(args.email.strip().lower())
    if not user:
        print(f"nu există contul {args.email}", file=sys.stderr)
        return 1
    if args.cmd == "credits":
        applied = db.add_credits(user["id"], args.delta, f"admin: {args.reason}")
        print(f"{args.email}: {applied:+d} → {db.user(user['id'])['credits']} credite")
        return 0
    temp = secrets.token_urlsafe(9)
    db._q("UPDATE users SET pw=? WHERE id=?", (hash_password(temp), user["id"]))
    db._q("DELETE FROM user_sessions WHERE user_id=?", (user["id"],))
    print(f"parolă temporară pentru {args.email}: {temp}\n(trimite-o clientului; toate sesiunile vechi au fost închise)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
