import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from database import get_decrypted_email_password, save_reply, get_db

class EmailReplySender:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
        self.smtp_port = int(os.getenv("SMTP_PORT", "465"))

    def reply(self, email_id: int, body: str) -> dict:
        body = (body or "").strip()
        if not body:
            raise ValueError("Reply message body cannot be empty.")

        db = get_db()
        try:
            row = db.execute("SELECT * FROM emails WHERE id=? AND user_id=?", (email_id, self.user_id)).fetchone()
            user = db.execute("SELECT email_account FROM users WHERE id=?", (self.user_id,)).fetchone()
        finally:
            db.close()

        if not row:
            raise ValueError("Email record not found.")
        if not user or not user["email_account"]:
            raise ValueError("Configure your Gmail address in Settings first.")

        to_address = row["sender_email"] or parseaddr(row["sender"] or "")[1]
        if not to_address:
            raise ValueError("Could not determine sender email address.")

        gmail_password = get_decrypted_email_password(self.user_id)
        if not gmail_password:
            raise ValueError("Configure your Gmail App Password in Settings first.")

        subject = row["subject"] or "(No Subject)"
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject

        msg = EmailMessage()
        msg["From"] = user["email_account"]
        msg["To"] = to_address
        msg["Subject"] = subject
        reply_msg_id = make_msgid()
        msg["Message-ID"] = reply_msg_id

        if row["message_id"]:
            msg["In-Reply-To"] = row["message_id"]
            refs = (row["email_references"] or "").strip()
            msg["References"] = f"{refs} {row['message_id']}".strip()

        msg.set_content(body)

        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30) as smtp:
                smtp.login(user["email_account"], gmail_password)
                smtp.send_message(msg)

            save_reply(self.user_id, email_id, to_address, subject, body, "SENT", "", reply_msg_id)
            return {"to": to_address, "subject": subject, "message_id": reply_msg_id}
        except Exception as exc:
            save_reply(self.user_id, email_id, to_address, subject, body, "FAILED", str(exc), reply_msg_id)
            raise RuntimeError(f"SMTP Email Reply failure: {exc}") from exc