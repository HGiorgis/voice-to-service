import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Get environment variables
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS") == "True"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL")

# Email details
to_email = "your-email@gmail.com"
subject = "Welcome to Voice To Service 🚀"

body = """
Hello 👋,

This email is sent from Voice To Service.

Your email system is working perfectly!

Best regards,  
Voice To Service Team
"""

# Create message
msg = MIMEText(body, "plain", "utf-8")

msg["From"] = formataddr(("Voice To Service", DEFAULT_FROM_EMAIL))
msg["To"] = to_email
msg["Subject"] = subject

try:
    server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)

    if EMAIL_USE_TLS:
        server.starttls()

    server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)

    server.sendmail(DEFAULT_FROM_EMAIL, to_email, msg.as_string())

    print("✅ Email sent successfully!")

except Exception as e:
    print("❌ Error:", e)

finally:
    server.quit()