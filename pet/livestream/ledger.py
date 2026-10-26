"""只记监听期间已观察的礼物和本直播请求用量，不推算抖音提现收入。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import sqlite3
from pathlib import Path

from .rules import gift_fields, number


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


class Ledger:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=1)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS gifts (room TEXT, identity TEXT, count INTEGER,
                PRIMARY KEY(room, identity));
            CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, diamonds INTEGER DEFAULT 0,
                unknown_gifts INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS usage (id TEXT PRIMARY KEY, day TEXT, tokens INTEGER);
            CREATE TABLE IF NOT EXISTS balance (day TEXT PRIMARY KEY, provider TEXT,
                initial TEXT, current TEXT, invalid INTEGER DEFAULT 0, currency TEXT DEFAULT '');
        ''')
        if 'currency' not in {row[1] for row in self.db.execute('PRAGMA table_info(balance)')}:
            self.db.execute("ALTER TABLE balance ADD COLUMN currency TEXT DEFAULT ''")
            self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.db.close()

    def gift(self, room, d, day=None):
        day = day or today()
        uid, gid, group, count, price, _, _ = gift_fields(d)
        if not uid or not gid or not group:
            return 0
        identity = f'{uid}:{gid}:{group}'
        with self.db:
            row = self.db.execute('SELECT count FROM gifts WHERE room=? AND identity=?', (room, identity)).fetchone()
            delta = max(0, count - (row[0] if row else 0))
            if not delta:
                return 0
            self.db.execute('INSERT OR REPLACE INTO gifts VALUES (?,?,?)', (room, identity, count))
            self.db.execute('INSERT OR IGNORE INTO daily(day) VALUES (?)', (day,))
            self.db.execute('UPDATE daily SET diamonds=diamonds+?, unknown_gifts=unknown_gifts+? WHERE day=?',
                            (delta * price, delta if not price else 0, day))
        return delta

    def usage(self, request, usage, day=None):
        total = None
        if isinstance(usage, dict) and isinstance(usage.get('total_tokens'), int) and usage['total_tokens'] >= 0:
            total = number(usage['total_tokens'], maximum=1000000000)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO usage VALUES (?,?,?)', (request, day or today(), total))

    def balance(self, provider, total, day=None, currency=''):
        try:
            value = Decimal(total)
            if not value.is_finite():
                return
        except (InvalidOperation, TypeError, ValueError):
            return
        day = day or today()
        with self.db:
            row = self.db.execute('SELECT provider,current,invalid,currency FROM balance WHERE day=?', (day,)).fetchone()
            if row:
                invalid = row[2] or row[0] != provider or value > Decimal(row[1]) or row[3] != currency
                self.db.execute('UPDATE balance SET current=?,invalid=?,currency=? WHERE day=?', (str(value), bool(invalid), currency, day))
            else:
                self.db.execute('INSERT INTO balance VALUES (?,?,?,?,0,?)', (day, provider, str(value), str(value), currency))

    def today(self, day=None):
        day = day or today()
        gifts = self.db.execute('SELECT diamonds,unknown_gifts FROM daily WHERE day=?', (day,)).fetchone() or (0, 0)
        usage = self.db.execute('SELECT COALESCE(SUM(tokens),0),COUNT(*)-COUNT(tokens) FROM usage WHERE day=?', (day,)).fetchone()
        balance = self.db.execute('SELECT initial,current,invalid,currency FROM balance WHERE day=?', (day,)).fetchone()
        return {'day': day, 'diamonds': gifts[0], 'unknown_gifts': gifts[1], 'tokens': usage[0],
                'unknown_usage': usage[1], 'balance': balance[1] if balance else None, 'currency': balance[3] if balance else '',
                'balance_drop': str(Decimal(balance[0]) - Decimal(balance[1])) if balance and not balance[2] else None}
