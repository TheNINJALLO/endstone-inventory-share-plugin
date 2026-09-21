"""Durable snapshots and fenced, transactional inventory handoffs.

Only immutable JSON data crosses the server thread boundary. A single worker
orders database operations; session tokens also fence writes across servers.
"""

import json
from pathlib import Path
import sqlite3
import threading

import pymysql


class SessionBusy(RuntimeError):
    pass


class LegacySessionBusy(SessionBusy):
    """An old login flag has no token/journal with which to prove ownership."""


class StaleSession(RuntimeError):
    pass


def retryable_load_error(error):
    if isinstance(error, LegacySessionBusy):
        return False
    return isinstance(error, SessionBusy) or (
        isinstance(error, pymysql.err.OperationalError)
        and error.args and error.args[0] in {1040, 1205, 1213, 2002, 2003, 2006, 2013}
    )


class SnapshotJournal:
    """Keep the most recent complete snapshot until its session is released."""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._lock = threading.Lock()
        db = self._connect()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS pending ("
                       "token TEXT PRIMARY KEY, xuid TEXT NOT NULL, payload TEXT)")
            db.commit()
        finally:
            db.close()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def put(self, token, xuid, data=None):
        payload = json.dumps(data, ensure_ascii=False) if data is not None else None
        with self._lock:
            db = self._connect()
            try:
                with db:
                    db.execute("INSERT INTO pending VALUES (?, ?, ?) "
                               "ON CONFLICT(token) DO UPDATE SET payload=excluded.payload",
                               (token, xuid, payload))
            finally:
                db.close()

    def remove(self, token):
        with self._lock:
            db = self._connect()
            try:
                with db:
                    db.execute("DELETE FROM pending WHERE token=?", (token,))
            finally:
                db.close()

    def entries(self):
        with self._lock:
            db = self._connect()
            try:
                return [(token, xuid, json.loads(payload) if payload else None)
                        for token, xuid, payload in
                        db.execute("SELECT token,xuid,payload FROM pending ORDER BY rowid")]
            finally:
                db.close()


class InventoryStore:
    def __init__(self, connect, server_name):
        self.connect = connect
        self.server_name = server_name

    def claim(self, xuid, token):
        conn, cursor = self.connect()
        try:
            cursor.execute("INSERT IGNORE INTO player_data (player_xuid) VALUES (%s)", (xuid,))
            cursor.execute("SELECT is_logged_in, session_token FROM player_data "
                           "WHERE player_xuid=%s FOR UPDATE", (xuid,))
            logged_in, owner = cursor.fetchone()
            if logged_in and owner != token:
                if not owner:
                    raise LegacySessionBusy("Legacy login lock without a session token; "
                                            "an administrator must confirm the player is offline on all servers")
                raise SessionBusy("Inventory is still in use or waiting for a save on another server")
            cursor.execute("UPDATE player_data SET is_logged_in=1, session_token=%s "
                           "WHERE player_xuid=%s", (token, xuid))
            cursor.execute("SELECT player_inv, player_enderchest, unresolved_items, "
                           "player_xp_level, player_xp_progress, player_money_score, "
                           "player_tags, player_locations, player_bundles FROM player_data "
                           "WHERE player_xuid=%s", (xuid,))
            row = dict(zip((column[0] for column in cursor.description), cursor.fetchone()))
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    def save(self, xuid, token, data=None, *, release=False):
        """Commit every field and the optional lock release in one transaction."""
        conn, cursor = self.connect()
        try:
            cursor.execute("SELECT session_token, player_locations FROM player_data "
                           "WHERE player_xuid=%s FOR UPDATE", (xuid,))
            row = cursor.fetchone()
            if not row or row[0] != token:
                raise StaleSession(f"Session no longer owns inventory {xuid}")
            if data is not None:
                locations = json.loads(row[1]) if row[1] else {}
                locations[self.server_name] = data["current_location"]
                vault = data["updated_vault"]
                bundles = data.get("bundle_data")
                preserve = set(data.get("preserve_fields", []))
                cursor.execute(
                    "UPDATE player_data SET player_inv=%s, player_enderchest=%s, "
                    "player_xp_level=COALESCE(%s,player_xp_level), "
                    "player_xp_progress=COALESCE(%s,player_xp_progress), "
                    "player_money_score=COALESCE(%s,player_money_score), "
                    "player_tags=COALESCE(%s,player_tags), "
                    "unresolved_items=%s, player_locations=%s, "
                    "player_bundles=COALESCE(%s,player_bundles) WHERE player_xuid=%s",
                    (data["inv_json"], data["ec_json"],
                     None if "xp" in preserve else data["xp_level"],
                     None if "xp" in preserve else data["xp_progress"],
                     None if "money" in preserve else data["money_score"],
                     None if "tags" in preserve else json.dumps(data["tags"], ensure_ascii=False),
                     json.dumps(vault, ensure_ascii=False), json.dumps(locations, ensure_ascii=False),
                     json.dumps(bundles, ensure_ascii=False) if bundles is not None else None, xuid),
                )
            if release:
                cursor.execute("UPDATE player_data SET is_logged_in=0, session_token=NULL "
                               "WHERE player_xuid=%s", (xuid,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()


    def release_legacy(self, xuid):
        """Console recovery only, after the operator confirms network-wide logout."""
        conn, cursor = self.connect()
        try:
            cursor.execute("UPDATE player_data SET is_logged_in=0 "
                           "WHERE player_xuid=%s AND is_logged_in=1 "
                           "AND (session_token IS NULL OR session_token='')", (xuid,))
            changed = cursor.rowcount == 1
            conn.commit()
            return changed
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()


def recover_pending(store, journal, logger, *, entries=None):
    """Replay only snapshots whose original token still owns the shared row."""
    failures = 0
    for token, xuid, data in journal.entries() if entries is None else entries:
        try:
            store.save(xuid, token, data, release=True)
        except StaleSession:
            # A committed release or a newer owner makes this journal obsolete.
            journal.remove(token)
        except Exception as error:
            failures += 1
            logger.error(f"Inventory recovery pending for {xuid}: {error}")
        else:
            journal.remove(token)
    return failures
