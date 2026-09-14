import os
import threading
import logging
from functools import wraps
from dotenv import load_dotenv

load_dotenv(override=True)

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import init_db, get_db, create_user, get_user_by_username, get_user_by_id, verify_password, update_user_settings
from email_monitor import EmailMonitor
from email_sender import EmailReplySender
from security import generate_secret_key
from notification import WhatsAppNotifier

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "").strip() or generate_secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

init_db()
MONITORS = {}
MONITORS_LOCK = threading.Lock()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def get_current_user():
    return get_user_by_id(session.get("user_id")) if session.get("user_id") else None

def get_monitor(user_id):
    with MONITORS_LOCK:
        monitor = MONITORS.get(user_id)
        if monitor and not monitor.is_running:
            MONITORS.pop(user_id, None)
            return None
        return monitor

def start_monitor_for_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found.")
    if not (user.get("email_account") or "").strip():
        raise ValueError("Configure your Gmail address in Settings first.")
    
    from database import get_decrypted_email_password
    if not get_decrypted_email_password(user_id):
        raise ValueError("Configure your Gmail App Password in Settings first.")
    if not (user.get("whatsapp_to") or "").strip():
        raise ValueError("Configure the WhatsApp destination number in Settings first.")
        
    with MONITORS_LOCK:
        existing = MONITORS.get(user_id)
        if existing and existing.is_running:
            return existing
        monitor = EmailMonitor(user_id)
        MONITORS[user_id] = monitor
        monitor.start()
        return monitor

def stop_monitor_for_user(user_id):
    with MONITORS_LOCK:
        monitor = MONITORS.pop(user_id, None)
    if monitor:
        monitor.stop()

@app.route("/")
def index():
    return redirect(url_for("dashboard" if "user_id" in session else "login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(username) < 3:
            flash("Username must contain at least 3 characters.", "danger")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        else:
            try:
                user_id = create_user(username, password)
                session.clear()
                session["user_id"] = user_id
                session["username"] = username
                flash("Account created. Configure email and WhatsApp settings.", "success")
                return redirect(url_for("settings"))
            except ValueError as exc:
                flash(str(exc), "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        if user and verify_password(password, user["password_hash"]):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Login successful.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    if session.get("user_id"):
        stop_monitor_for_user(session["user_id"])
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))
        
    db = get_db()
    try:
        stats = {
            "total_emails": db.execute("SELECT COUNT(*) FROM emails WHERE user_id=?", (user["id"],)).fetchone()[0],
            "high_priority": db.execute("SELECT COUNT(*) FROM emails WHERE user_id=? AND priority='HIGH'", (user["id"],)).fetchone()[0],
            "notifications": db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=?", (user["id"],)).fetchone()[0],
            "important": db.execute("SELECT COUNT(*) FROM emails WHERE user_id=? AND category IN ('Security','Job/Internship','Important')", (user["id"],)).fetchone()[0],
        }
        recent = db.execute("SELECT * FROM emails WHERE user_id=? ORDER BY COALESCE(received_at,processed_at) DESC,id DESC LIMIT 10", (user["id"],)).fetchall()
    finally:
        db.close()
        
    monitor = get_monitor(user["id"])
    return render_template("dashboard.html", user=user, stats=stats, recent=[dict(x) for x in recent], monitoring=bool(monitor and monitor.is_running))

@app.route("/toggle_monitor", methods=["POST"])
@login_required
def toggle_monitor():
    user_id = session["user_id"]
    try:
        monitor = get_monitor(user_id)
        if monitor and monitor.is_running:
            stop_monitor_for_user(user_id)
            return jsonify(success=True, running=False, message="Monitoring stopped.")
        start_monitor_for_user(user_id)
        return jsonify(success=True, running=True, message="Monitoring started.")
    except Exception as exc:
        logger.exception("Unable to toggle monitor")
        return jsonify(success=False, message=str(exc)), 400

@app.route("/test_whatsapp", methods=["POST"])
@login_required
def test_whatsapp():
    try:
        result = WhatsAppNotifier(session["user_id"]).send_test()
        return jsonify(success=bool(result), message="Test WhatsApp message sent." if result else "Message could not be sent.")
    except Exception as exc:
        logger.exception("WhatsApp test failed")
        return jsonify(success=False, message=str(exc)), 400

@app.route("/emails")
@login_required
def emails():
    user_id = session["user_id"]
    category = request.args.get("category", "").strip()
    priority = request.args.get("priority", "").strip()
    
    db = get_db()
    try:
        query = "SELECT * FROM emails WHERE user_id=?"
        params = [user_id]
        if category:
            query += " AND category=?"
            params.append(category)
        if priority:
            query += " AND priority=?"
            params.append(priority)
        query += " ORDER BY COALESCE(received_at,processed_at) DESC,id DESC LIMIT 200"
        rows = db.execute(query, params).fetchall()
    finally:
        db.close()
        
    return render_template("emails.html", emails=[dict(x) for x in rows], selected_category=category, selected_priority=priority)

@app.route("/email/<int:email_id>")
@login_required
def email_detail(email_id):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM emails WHERE id=? AND user_id=?", (email_id, session["user_id"])).fetchone()
        # FIX 1: Changed table reference from 'email_replies' to 'replies'
        replies = db.execute("SELECT * FROM replies WHERE email_id=? AND user_id=? ORDER BY created_at DESC", (email_id, session["user_id"])).fetchall() if row else []
    finally:
        db.close()
        
    if not row:
        flash("Email not found.", "danger")
        return redirect(url_for("emails"))
        
    return render_template("email_detail.html", email=dict(row), replies=[dict(x) for x in replies])

@app.route("/email/<int:email_id>/reply", methods=["POST"])
@login_required
def reply_email(email_id):
    body = request.form.get("body", "").strip()
    try:
        # FIX 2: Validate body content before sending
        if not body:
            raise ValueError("Reply body cannot be empty.")

        result = EmailReplySender(session["user_id"]).reply(email_id, body)
        whatsapp_warning = ""
        
        try:
            WhatsAppNotifier(session["user_id"]).send_reply_confirmation(result["to"], result["subject"])
        except Exception as exc:
            logger.exception("Reply sent but WhatsApp confirmation failed")
            whatsapp_warning = f" Email reply was sent, but WhatsApp confirmation failed: {exc}"
            
        flash("Reply sent successfully." + whatsapp_warning, "success" if not whatsapp_warning else "warning")
    except Exception as exc:
        logger.exception("Email reply failed")
        flash(str(exc), "danger")
        
    return redirect(url_for("email_detail", email_id=email_id))

@app.route("/notifications")
@login_required
def notifications():
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY sent_at DESC,id DESC LIMIT 200", (session["user_id"],)).fetchall()
    finally:
        db.close()
        
    return render_template("notifications.html", notifications=[dict(x) for x in rows])

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = get_current_user()
    if request.method == "POST":
        raw = request.form.get("poll_interval", "15").strip()
        try:
            interval = int(raw)
            if interval < 5:
                raise ValueError("Polling interval must be at least 5 seconds.")
            data = {
                "email_account": request.form.get("email_account", "").strip(),
                "email_password": request.form.get("email_password", "").strip(),
                "whatsapp_to": request.form.get("whatsapp_to", "").strip(),
                "poll_interval": interval,
                "notify_all": 1 if request.form.get("notify_all") else 0,
                "notify_high": 1 if request.form.get("notify_high") else 0,
                "notify_categories": request.form.get("notify_categories", "").strip(),
            }
            update_user_settings(user["id"], data)
            stop_monitor_for_user(user["id"])
            flash("Settings saved successfully.", "success")
        except Exception as exc:
            logger.exception("Settings update failed")
            flash(f"Could not save settings: {exc}", "danger")
        return redirect(url_for("settings"))
        
    return render_template("settings.html", user=user)

@app.route("/api/stats")
@login_required
def api_stats():
    db = get_db()
    uid = session["user_id"]
    try:
        # FIX 3: Changed table reference from 'email_replies' to 'replies'
        result = {
            "total_emails": db.execute("SELECT COUNT(*) FROM emails WHERE user_id=?", (uid,)).fetchone()[0],
            "high_priority": db.execute("SELECT COUNT(*) FROM emails WHERE user_id=? AND priority='HIGH'", (uid,)).fetchone()[0],
            "notifications": db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=?", (uid,)).fetchone()[0],
            "replies": db.execute("SELECT COUNT(*) FROM replies WHERE user_id=? AND status='SENT'", (uid,)).fetchone()[0],
        }
    finally:
        db.close()
        
    return jsonify(result)

if __name__ == "__main__":
    print("EMAIL ALERT AI - starting")
    print("Twilio SID configured:", bool(os.getenv("TWILIO_ACCOUNT_SID")))
    print("Twilio token configured:", bool(os.getenv("TWILIO_AUTH_TOKEN")))
    print("WhatsApp sender configured:", bool(os.getenv("TWILIO_WHATSAPP_FROM")))
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)