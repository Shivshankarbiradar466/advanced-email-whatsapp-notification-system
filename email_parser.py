import email
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime, parseaddr

def decode_mime(value: str) -> str:
    if not value:
        return ""
    output = []
    for text, encoding in decode_header(value):
        if isinstance(text, bytes):
            enc = encoding or "utf-8"
            try:
                output.append(text.decode(enc, errors="ignore"))
            except (LookupError, UnicodeDecodeError):
                output.append(text.decode("utf-8", errors="ignore"))
        else:
            output.append(str(text))
    return "".join(output).strip()

def extract_body(msg) -> str:
    chunks = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition.lower():
                continue
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        chunks.append(payload.decode(charset, errors="ignore"))
                    except Exception:
                        chunks.append(payload.decode("utf-8", errors="ignore"))
        if not chunks:
            for part in msg.walk():
                if part.get_content_type() == "text/html" and "attachment" not in str(part.get("Content-Disposition", "")).lower():
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            text = payload.decode(charset, errors="ignore")
                        except Exception:
                            text = payload.decode("utf-8", errors="ignore")
                        clean_text = re.sub(r"<[^>]+>", " ", text)
                        chunks.append(clean_text)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                chunks.append(payload.decode(charset, errors="ignore"))
            except Exception:
                chunks.append(payload.decode("utf-8", errors="ignore"))

    text = re.sub(r"\s+", " ", "\n".join(chunks)).strip()
    return text[:10000]

def parse_email(raw_bytes: bytes) -> dict:
    if not raw_bytes:
        return {}
    msg = email.m
    essage_from_bytes(raw_bytes)
    subject = decode_mime(msg.get("Subject", "(No Subject)"))
    sender = decode_mime(msg.get("From", "Unknown Sender"))
    _, sender_email = parseaddr(sender)
    
    date_header = msg.get("Date", "")
    received_at = ""
    if date_header:
        try:
            received_at = parsedate_to_datetime(date_header).isoformat()
        except Exception:
            received_at = ""

    return {
        "sender": sender,
        "sender_email": sender_email,
        "subject": subject,
        "body": extract_body(msg),
        "received_at": received_at,
        "message_id": (msg.get("Message-ID") or "").strip(),
        "in_reply_to": (msg.get("In-Reply-To") or "").strip(),
        "references": (msg.get("References") or "").strip(),
    }