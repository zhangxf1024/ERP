"""SQLite connections and explicit atomic business transactions."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from flask import current_app, g


def get_db():
    if 'db' not in g:
        conn = sqlite3.connect(current_app.config['DATABASE'], timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=15000')
        g.db = conn
    return g.db


def close_db(error=None):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def init_db():
    db = get_db()
    db.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))


@contextmanager
def atomic():
    db = get_db()
    nested = db.in_transaction
    savepoint = 'sp_' + uuid4().hex
    db.execute(f'SAVEPOINT {savepoint}' if nested else 'BEGIN IMMEDIATE')
    try:
        yield db
        if nested:
            db.execute(f'RELEASE SAVEPOINT {savepoint}')
        else:
            db.commit()
    except BaseException:
        if nested:
            db.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
            db.execute(f'RELEASE SAVEPOINT {savepoint}')
        else:
            db.rollback()
        raise


def rows(sql, args=()):
    return [dict(row) for row in get_db().execute(sql, args).fetchall()]


def row(sql, args=()):
    result = get_db().execute(sql, args).fetchone()
    return dict(result) if result is not None else None


def scalar(sql, args=()):
    result = get_db().execute(sql, args).fetchone()
    return result[0] if result is not None else None
