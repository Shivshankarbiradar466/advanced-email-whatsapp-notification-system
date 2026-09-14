import imaplib
import logging
import threading
import time

from database import get_db, get_decrypted_email_password
from email_parser import parse_email
from ai_classifier import EmailAIClassifier
from notification import WhatsAppNotifier

logger = logging.getLogger(__name__)

class EmailMonitor:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.imap = None
        self.is_running = False
        self.thread = None
        self.classifier = EmailAIClassifier()

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(
            target=self._run,
            name=f"EmailMonitor-{self.user_id}",
            daemon=True
        )
        self.thread.start()
        logger.info("Email monitoring started for user %s", self.user_id)

    def stop(self):
        self.is_running = False
        self._disconnect()
        if self.thread and self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
        logger.info("Email monitoring stopped for user %s", self.user_id)

    def _run(self):
        while self.is_running:
            try:
                user = self._get_user()
                if not user:
                    logger.error("User %s no longer exists.", self.user_id)
                    break

                account = user.get("email_account")
                if not account:
                    raise RuntimeError("Gmail address is not configured. Save it in Settings.")

                if self.imap is None or not self._is_connection_alive():
                    self._disconnect()
                    self._connect(account)

                self._check_new_emails(user)
                poll_interval = max(5, int(user.get("poll_interval") or 15))
                self._sleep_interruptibly(poll_interval)
            except Exception as exc:
                logger.exception("Monitoring loop encountered error for user %s: %s", self.user_id, exc)
                self._disconnect()
                self._sleep_interruptibly(10)

    def _sleep_interruptibly(self, seconds: int):
        end = time.time() + seconds
        while self.is_running and time.time() < end:
            time.sleep(min(1, max(0, end - time.time())))

    def _get_user(self):
        db = get_db()
        try:
            row = db.execute("SELECT * FROM users WHERE id=?", (self.user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def _connect(self, account: str):
        password = get_decrypted_email_password(self.user_id)
        if not password:
            raise RuntimeError("Gmail App Password is not configured. Save it in Settings.")

        logger.info("Connecting to Gmail IMAP for user %s...", self.user_id)
        try:
            self.imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            self.imap.login(account, password)
            status, _ = self.imap.select("INBOX")
            if status != "OK":
                raise RuntimeError("Could not select Gmail INBOX.")
            logger.info("Gmail IMAP login successful for user %s (%s)", self.user_id, account)
        except Exception:
            self._disconnect()
            raise

    def _is_connection_alive(self) -> bool:
        if self.imap is None:
            return False
        try:
            status, _ = self.imap.noop()
            return status == "OK"
        except Exception:
            return False

    def _disconnect(self):
        if self.imap is None:
            return
        conn = self.imap
        self.imap = None
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass

    def _normalize_classifier_result(self, result):
        if isinstance(result, dict):
            return {
                "category": result.get("category", "General"),
                "priority": result.get("priority", "NORMAL"),
                "confidence": result.get("confidence", 0.50),
                "reason": result.get("reason", "No classification reason available.")
            }
        if isinstance(result, (tuple, list)) and len(result) >= 4:
            return {
                "category": result[0],
                "priority": result[1],
                "confidence": result[2],
                "reason": result[3]
            }
        return {
            "category": "General",
            "priority": "NORMAL",
            "confidence": 0.50,
            "reason": "Unable to classify this email."
        }

    def _check_new_emails(self, user: dict):
        if self.imap is None:
            return

        status, messages = self.imap.search(None, "ALL")
        if status != "OK" or not messages or not messages[0]:
            return

        ids = messages[0].split()
        if not ids:
            return

        recent_ids = ids[-20:]
        notifier = WhatsAppNotifier(self.user_id)

        for email_id in recent_ids:
            if not self.is_running or self.imap is None:
                break
            try:
                status, data = self.imap.fetch(email_id, "(RFC822)")
                if status != "OK":
                    continue

                raw = next(
                    (part[1] for part in data if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes)),
                    None
                )
                if not raw:
                    continue

                parsed = parse_email(raw)
                if not parsed:
                    continue

                message_uid = email_id.decode(errors="ignore")

                db = get_db()
                try:
                    existing = db.execute("SELECT id FROM emails WHERE user_id=? AND message_uid=?", (self.user_id, message_uid)).fetchone()
                    if existing:
                        continue

                    raw_result = self.classifier.classify(parsed.get("sender", ""), parsed.get("subject", ""), parsed.get("body", ""))
                    result = self._normalize_classifier_result(raw_result)

                    cur = db.execute(
                        """
                        INSERT INTO emails(user_id, message_uid, sender, sender_email, subject, body_preview, category, priority, confidence, ai_reason, received_at, message_id, in_reply_to, email_references)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self.user_id, message_uid, parsed.get("sender", ""), parsed.get("sender_email", ""),
                            parsed.get("subject", ""), parsed.get("body", "")[:3000], result["category"],
                            result["priority"], result["confidence"], result["reason"], parsed.get("received_at"),
                            parsed.get("message_id"), parsed.get("in_reply_to"), parsed.get("references")
                        )
                    )
                    db.commit()
                    saved_email_id = cur.lastrowid
                finally:
                    db.close()

                email_record = {**parsed, **result, "message_uid": message_uid}
                try:
                    notifier.send(email_record, saved_email_id)
                except Exception as whatsapp_err:
                    logger.error("WhatsApp delivery failure for email %s: %s", saved_email_id, whatsapp_err)

                try:
                    if self.imap:
                        self.imap.store(email_id, "+FLAGS", "\\Seen")
                except Exception:
                    pass
            except Exception:
                logger.exception("Failed processing individual email ID %s", email_id)