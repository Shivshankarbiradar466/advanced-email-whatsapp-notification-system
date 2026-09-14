# Email Alert AI - Updated Major Project

This version monitors Gmail over IMAP, classifies incoming emails locally with scikit-learn, stores them in SQLite, sends WhatsApp alerts through Twilio, and adds dashboard-based email replies through Gmail SMTP.

## Important external-service limits

- Gmail requires an App Password for this project; never put your normal Gmail password into the app.
- Twilio WhatsApp Sandbox recipients must join your Sandbox.
- WhatsApp business-initiated free-form messages can be rejected outside the 24-hour customer-service window. For reliable notifications outside that window, configure an approved `TWILIO_CONTENT_SID` template.
- The code cannot guarantee delivery if Gmail, Twilio, WhatsApp, account permissions, or network access are unavailable.

## Windows setup

1. Open PowerShell in the project folder.
2. Create/activate the virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install packages:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Generate secrets:

```powershell
python generate_keys.py
```

5. Create a file named `.env` in the same folder as `app.py`. Copy the generated `FERNET_KEY=` and `FLASK_SECRET_KEY=` lines into it. Add your current Twilio Account SID, Auth Token and WhatsApp sender. Do not add quotation marks around the values.

6. Verify environment variables:

```powershell
python -c "from dotenv import load_dotenv; import os; load_dotenv(override=True); print('FERNET:',bool(os.getenv('FERNET_KEY'))); print('FLASK:',bool(os.getenv('FLASK_SECRET_KEY'))); print('SID:',bool(os.getenv('TWILIO_ACCOUNT_SID'))); print('TOKEN:',bool(os.getenv('TWILIO_AUTH_TOKEN')))"
```

7. Start:

```powershell
python app.py
```

8. Open `http://127.0.0.1:5000`, register, save Gmail/App Password and WhatsApp number, click Test WhatsApp, then Start Monitoring.

## WhatsApp Sandbox

Join the Sandbox from the phone that should receive notifications using the join code shown by Twilio. The sender is normally `whatsapp:+14155238886` for the Sandbox. If the user has not joined, messages will not be delivered.

For business-initiated messages outside the 24-hour window, configure an approved Twilio Content Template SID in `.env` as `TWILIO_CONTENT_SID=HX...`.

## Dashboard reply

Click `Open / Reply` next to an email. Enter the reply and click `Send Reply`. The app uses the stored Gmail App Password to send through Gmail SMTP and uses `Message-ID`, `In-Reply-To` and `References` headers to preserve email threading when available. A WhatsApp confirmation is attempted after the email is sent.

## Existing database

Do not delete `database/email_alert.db` just to add the reply feature. The app automatically adds the new email/reply columns to an existing database. Keep the same `FERNET_KEY` that was used to encrypt stored Gmail App Passwords.
