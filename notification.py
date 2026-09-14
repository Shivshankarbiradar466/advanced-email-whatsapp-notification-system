import os
import logging
from dotenv import load_dotenv
from twilio.rest import Client
from database import get_user_by_id, get_db

load_dotenv(override=True)
logger = logging.getLogger(__name__)

def format_whatsapp_number(number: str) -> str:
    if not number:
        return ""
    clean = number.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not clean.startswith("whatsapp:"):
        if not clean.startswith("+"):
            # Default to India (+91) if no country code provided
            clean = "+" + clean
        clean = "whatsapp:" + clean
    return clean

class WhatsAppNotifier:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.from_number = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()
        self.content_sid = os.getenv("TWILIO_CONTENT_SID", "").strip()

    def _get_client(self):
        if not self.account_sid or not self.auth_token:
            raise RuntimeError("Twilio Account SID or Auth Token is missing in .env.")
        return Client(self.account_sid, self.auth_token)

    def _log_notification(self, email_db_id, destination, message, status, sid="", error=""):
        db = get_db()
        try:
            db.execute(
                """
                INSERT INTO notifications (user_id, email_id, channel, destination, message, status, provider_sid, error_message)
                VALUES (?, ?, 'WHATSAPP', ?, ?, ?, ?, ?)
                """,
                (self.user_id, email_db_id, destination, message, status, sid, error)
            )
            db.commit()
        except Exception as exc:
            logger.exception("Failed to write notification log to database: %s", exc)
        finally:
            db.close()

    def _dispatch_message(self, whatsapp_to: str, body: str, email_db_id: int = None) -> bool:
        try:
            client = self._get_client()
            from_num = format_whatsapp_number(self.from_number)
            
            logger.info("Sending WhatsApp message via Twilio from %s to %s", from_num, whatsapp_to)
            
            msg_args = {
                "body": body,
                "from_": from_num,
                "to": whatsapp_to
            }
            if self.content_sid:
                msg_args["content_sid"] = self.content_sid

            message = client.messages.create(**msg_args)
            
            self._log_notification(email_db_id, whatsapp_to, body, "SENT", message.sid, "")
            logger.info("WhatsApp notification delivered successfully (SID: %s)", message.sid)
            return True
        except Exception as exc:
            err_msg = str(exc)
            logger.error("Twilio API Error: %s", err_msg)
            self._log_notification(email_db_id, whatsapp_to, body, "FAILED", "", err_msg)
            return False

    def send_test(self) -> bool:
        user = get_user_by_id(self.user_id)
        if not user:
            raise ValueError("User not found.")
        
        whatsapp_to = format_whatsapp_number(user.get("whatsapp_to"))
        if not whatsapp_to or len(whatsapp_to) < 12:
            raise ValueError("Invalid WhatsApp number configured in Settings.")

        msg = "🔔 *Email Alert AI Test Notification*\nYour WhatsApp notification service is working perfectly!"
        return self._dispatch_message(whatsapp_to, msg)

    def send_reply_confirmation(self, recipient: str, subject: str) -> bool:
        user = get_user_by_id(self.user_id)
        if not user:
            return False
        whatsapp_to = format_whatsapp_number(user.get("whatsapp_to"))
        if not whatsapp_to:
            return False

        msg = f"📤 *Email Reply Sent*\n*To:* {recipient}\n*Subject:* {subject}"
        return self._dispatch_message(whatsapp_to, msg)

    def send(self, email_record: dict, email_db_id: int = None) -> bool:
        user = get_user_by_id(self.user_id)
        if not user:
            logger.error("User %s missing from database during notification dispatch.", self.user_id)
            return False

        whatsapp_to = format_whatsapp_number(user.get("whatsapp_to"))
        if not whatsapp_to:
            logger.warning("No valid WhatsApp recipient address found for user %s.", self.user_id)
            return False

        notify_all = bool(user.get("notify_all", 1))
        notify_high = bool(user.get("notify_high", 1))
        raw_allowed = user.get("notify_categories") or "Security,Job/Internship,Important"
        allowed_categories = [c.strip().lower() for c in raw_allowed.split(",") if c.strip()]

        priority = (email_record.get("priority") or "NORMAL").upper()
        category = (email_record.get("category") or "General").strip()

        # Robust notification decision logic
        category_match = any(cat in category.lower() for cat in allowed_categories)
        should_send = notify_all or (notify_high and priority == "HIGH") or category_match

        if not should_send:
            logger.info("Email ID %s skipped due to user preference filters.", email_db_id)
            return False

        preview_text = email_record.get("body", "")[:250]
        message_body = (
            f"📧 *New Email Alert*\n"
            f"*From:* {email_record.get('sender', 'Unknown')}\n"
            f"*Subject:* {email_record.get('subject', '(No Subject)')}\n"
            f"*Category:* {category} | *Priority:* {priority}\n\n"
            f"*Preview:* {preview_text}..."
        )

        return self._dispatch_message(whatsapp_to, message_body, email_db_id)