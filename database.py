import os
import sqlite3
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from security import encrypt_value, decrypt_value

load_dotenv(override=True)
DB_PATH = os.getenv("DATABASE_PATH", "database/email_alert.db").strip() or "database/email_alert.db"

def get_db():
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db():
    db = get_db()
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email_account TEXT DEFAULT '',
                email_password_enc TEXT DEFAULT '',
                whatsapp_to TEXT DEFAULT '',
                poll_interval INTEGER DEFAULT 15,
                notify_all INTEGER DEFAULT 1,
                notify_high INTEGER DEFAULT 1,
                notify_categories TEXT DEFAULT 'Security,Job/Internship,Important',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message_uid TEXT,
                sender TEXT,
                sender_email TEXT,
                subject TEXT,
                body_preview TEXT,
                category TEXT,
                priority TEXT,
                confidence REAL DEFAULT 0,
                ai_reason TEXT,
                received_at TEXT,
                message_id TEXT,
                in_reply_to TEXT,
                email_references TEXT,
                processed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, message_uid),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email_id INTEGER,
                recipient TEXT,
                subject TEXT,
                body TEXT,
                status TEXT DEFAULT 'SENT',
                error_message TEXT DEFAULT '',
                message_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email_id INTEGER,
                channel TEXT,
                destination TEXT,
                message TEXT,
                status TEXT,
                provider_sid TEXT,
                error_message TEXT,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE SET NULL
            );
        """)
        db.commit()
    finally:
        db.close()

def create_user(username, password):
    db = get_db()
    try:
        cur = db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, generate_password_hash(password)))
        db.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Username already exists.")
    finally:
        db.close()

def get_user_by_username(username):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()

def get_user_by_id(user_id):
    if not user_id:
        return None
    db = get_db()
    try:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()

def verify_password(password, password_hash):
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False

def update_user_settings(user_id, data):
    db = get_db()
    try:
        email_account = (data.get("email_account") or "").strip()
        email_password = (data.get("email_password") or "").replace(" ", "").strip()
        whatsapp_to = (data.get("whatsapp_to") or "").strip()
        poll_interval = max(5, int(data.get("poll_interval", 15)))
        notify_all = int(data.get("notify_all", 1))
        notify_high = int(data.get("notify_high", 1))
        notify_categories = (data.get("notify_categories") or "Security,Job/Internship,Important").strip()

        if email_password:
            encrypted_password = encrypt_value(email_password)
            db.execute(
                """
                UPDATE users SET email_account=?, email_password_enc=?, whatsapp_to=?, poll_interval=?, notify_all=?, notify_high=?, notify_categories=? WHERE id=?
                """,
                (email_account, encrypted_password, whatsapp_to, poll_interval, notify_all, notify_high, notify_categories, user_id)
            )
        else:
            db.execute(
                """
                UPDATE users SET email_account=?, whatsapp_to=?, poll_interval=?, notify_all=?, notify_high=?, notify_categories=? WHERE id=?
                """,
                (email_account, whatsapp_to, poll_interval, notify_all, notify_high, notify_categories, user_id)
            )
        db.commit()
    finally:
        db.close()

def get_decrypted_email_password(user_id):
    db = get_db()
    try:
        row = db.execute("SELECT email_password_enc FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        db.close()

    if not row or not row["email_password_enc"]:
        return ""

    try:
        return decrypt_value(row["email_password_enc"])
    except Exception as exc:
        raise RuntimeError("Stored Gmail password decryption failed. Verify FERNET_KEY in .env.") from exc

def save_reply(user_id, email_id, recipient, subject, body, status="SENT", error_message="", message_id=""):
    db = get_db()
    try:
        db.execute(
            """
            INSERT INTO notifications (user_id, email_id, channel, destination, message, status, provider_sid, error_message)
            VALUES (?, ?, 'EMAIL_REPLY', ?, ?, ?, ?, ?)
            """,
            (user_id, email_id, recipient, body, status, message_id or "", error_message)
        )
        db.execute(
            """
            INSERT INTO replies (user_id, email_id, recipient, subject, body, status, error_message, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, email_id, recipient, subject, body, status, error_message, message_id or "")
        )
        db.commit()
    finally:
        db.close()