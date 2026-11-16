"""Accounts for Aurelia Hall: password mail, Gmail, and Microsoft."""

import hmac
import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).with_name("aurelia.db")

MAIL_PROVIDERS = {
    "gmail.com": "Gmail",
    "googlemail.com": "Gmail",
    "outlook.com": "Outlook",
    "hotmail.com": "Outlook",
    "live.com": "Outlook",
    "msn.com": "Outlook",
    "yahoo.com": "Yahoo",
    "yahoo.co.uk": "Yahoo",
    "ymail.com": "Yahoo",
    "icloud.com": "iCloud",
    "me.com": "iCloud",
    "mac.com": "iCloud",
    "proton.me": "Proton",
    "protonmail.com": "Proton",
    "aol.com": "AOL",
    "gmx.com": "GMX",
    "zoho.com": "Zoho",
}

PROVIDERS = {
    "google": {
        "label": "Gmail",
        "column": "google_sub",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "user_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
        "id_env": "GOOGLE_CLIENT_ID",
        "secret_env": "GOOGLE_CLIENT_SECRET",
    },
    "microsoft": {
        "label": "Microsoft",
        "column": "microsoft_sub",
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "user_url": "https://graph.microsoft.com/v1.0/me",
        "scope": "openid email profile User.Read",
        "id_env": "MICROSOFT_CLIENT_ID",
        "secret_env": "MICROSOFT_CLIENT_SECRET",
    },
}


@contextmanager
def connect():
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                google_sub TEXT UNIQUE,
                microsoft_sub TEXT UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def normalize_email(value):
    email = (value or "").strip().lower()
    if any(character.isspace() for character in email):
        return ""
    return email


def valid_email(value):
    email = normalize_email(value)
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def mail_label(email):
    domain = normalize_email(email).split("@")[-1]
    return MAIL_PROVIDERS.get(domain, "Other mail")


def _row(connection, query, params=()):
    return connection.execute(query, params).fetchone()


def find_by_id(user_id):
    with connect() as connection:
        return _row(connection, "SELECT * FROM users WHERE id = ?", (user_id,))


def find_by_email(email):
    with connect() as connection:
        return _row(connection, "SELECT * FROM users WHERE email = ?", (normalize_email(email),))


def access_label(row):
    parts = []
    if row["password_hash"]:
        parts.append(mail_label(row["email"]))
    if row["google_sub"]:
        parts.append("Gmail")
    if row["microsoft_sub"]:
        parts.append("Microsoft")
    if not parts:
        parts.append(mail_label(row["email"]))
    ordered = []
    for part in parts:
        if part not in ordered:
            ordered.append(part)
    return ", ".join(ordered)


def public_user(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "access": access_label(row),
        "mail": mail_label(row["email"]),
    }


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    row = find_by_id(user_id)
    if row is None:
        session.pop("user_id", None)
        return None
    return public_user(row)


def login_user(user):
    session["user_id"] = user["id"]
    session.permanent = True


def sign_out():
    session.pop("user_id", None)


def register_account(name, email, password):
    name = " ".join((name or "").split())
    email = normalize_email(email)
    if len(name) < 2:
        return None, "Sign your name."
    if not valid_email(email):
        return None, "Enter a real address: Gmail, Outlook, Yahoo, iCloud, or another mail service."
    if len(password or "") < 8:
        return None, "Use a password of at least 8 characters."
    if len(password) > 128:
        return None, "That password is too long."

    existing = find_by_email(email)
    password_hash = generate_password_hash(password)
    with connect() as connection:
        if existing and existing["password_hash"]:
            return None, "That email already has a key. Sign in instead."
        if existing:
            connection.execute(
                "UPDATE users SET name = ?, password_hash = ? WHERE id = ?",
                (name, password_hash, existing["id"]),
            )
            row = _row(connection, "SELECT * FROM users WHERE id = ?", (existing["id"],))
            return public_user(row), None
        cursor = connection.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        row = _row(connection, "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,))
    return public_user(row), None


def sign_in_account(email, password):
    email = normalize_email(email)
    row = find_by_email(email) if valid_email(email) else None
    if row and not row["password_hash"]:
        return None, "That email uses Gmail or Microsoft sign-in, not a password."
    if not row or not check_password_hash(row["password_hash"], password or ""):
        return None, "Those details do not match an account."
    return public_user(row), None


def _local_oauth():
    path = Path(__file__).with_name("oauth.local.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def provider_secrets(provider):
    spec = PROVIDERS[provider]
    local = _local_oauth().get(provider) or {}
    if not isinstance(local, dict):
        local = {}
    client_id = os.environ.get(spec["id_env"]) or local.get("client_id") or ""
    client_secret = os.environ.get(spec["secret_env"]) or local.get("client_secret") or ""
    return client_id.strip(), client_secret.strip()


def oauth_ready(provider):
    client_id, client_secret = provider_secrets(provider)
    return bool(client_id and client_secret)


def begin_oauth(provider, redirect_uri, next_url):
    if provider not in PROVIDERS or not oauth_ready(provider):
        return None
    client_id, _secret = provider_secrets(provider)
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    session["oauth_provider"] = provider
    session["oauth_next"] = next_url or ""
    spec = PROVIDERS[provider]
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": spec["scope"],
            "state": state,
            "prompt": "select_account",
        }
    )
    return spec["auth_url"] + "?" + query


def _post_form(url, data):
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def _get_json(url, headers):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def _profile(provider, access_token):
    spec = PROVIDERS[provider]
    data = _get_json(spec["user_url"], {"Authorization": f"Bearer {access_token}"})
    if provider == "google":
        if not data.get("email") or not data.get("email_verified"):
            raise ValueError("Gmail did not confirm that address.")
        email = normalize_email(data["email"])
        name = " ".join((data.get("name") or "").split()) or email.split("@")[0]
        return data["sub"], email, name

    email = data.get("mail") or data.get("userPrincipalName") or ""
    if "#EXT#" in email:
        email = ""
    email = normalize_email(email)
    if not valid_email(email):
        raise ValueError("Microsoft did not share a usable mail address.")
    name = " ".join((data.get("displayName") or "").split()) or email.split("@")[0]
    return data["id"], email, name


def _save_oauth_user(provider, sub, email, name):
    if provider == "google":
        by_sub = "SELECT * FROM users WHERE google_sub = ?"
        attach = "UPDATE users SET google_sub = ? WHERE id = ?"
        insert = "INSERT INTO users (name, email, google_sub) VALUES (?, ?, ?)"
    elif provider == "microsoft":
        by_sub = "SELECT * FROM users WHERE microsoft_sub = ?"
        attach = "UPDATE users SET microsoft_sub = ? WHERE id = ?"
        insert = "INSERT INTO users (name, email, microsoft_sub) VALUES (?, ?, ?)"
    else:
        raise ValueError("Unknown sign-in service")

    with connect() as connection:
        row = _row(connection, by_sub, (sub,))
        if row:
            return public_user(row)
        row = _row(connection, "SELECT * FROM users WHERE email = ?", (email,))
        if row:
            connection.execute(attach, (sub, row["id"]))
            return public_user(_row(connection, "SELECT * FROM users WHERE id = ?", (row["id"],)))
        cursor = connection.execute(insert, (name, email, sub))
        return public_user(_row(connection, "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)))


def finish_oauth(provider, code, state, redirect_uri, provider_error):
    expected = session.pop("oauth_state", "")
    session.pop("oauth_provider", None)
    next_url = session.pop("oauth_next", "")
    label = PROVIDERS.get(provider, {}).get("label", "That service")
    if provider_error:
        return None, f"{label} did not sign you in.", next_url
    if provider not in PROVIDERS or not expected or not hmac.compare_digest(expected, state or ""):
        return None, "That sign-in attempt expired. Try again.", next_url
    if not code:
        return None, f"{label} did not return a sign-in code.", next_url

    client_id, client_secret = provider_secrets(provider)
    try:
        token = _post_form(
            PROVIDERS[provider]["token_url"],
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        sub, email, name = _profile(provider, token["access_token"])
        user = _save_oauth_user(provider, sub, email, name)
    except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError):
        return None, f"{label} could not confirm that account.", next_url
    return user, None, next_url
