"""
Generic Email Tools - Work with any SMTP provider.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional
from agent_harness.tool_registry import tool_registry


@tool_registry.register(category="communication")
def generic_email_sender(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    html: bool = False,
    cc: Optional[str] = None,
    bcc: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generic email sender - works with Gmail, SendGrid, AWS SES, etc.

    Args:
        smtp_host: SMTP server host
        smtp_port: SMTP server port
        smtp_user: SMTP username
        smtp_password: SMTP password
        from_email: Sender email address
        to_email: Recipient email address
        subject: Email subject
        body: Email body
        html: Whether body is HTML
        cc: CC email address
        bcc: BCC email address

    Returns:
        Dict with success status
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc

        # Add body
        mime_type = "html" if html else "plain"
        msg.attach(MIMEText(body, mime_type))

        # Send
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        return {
            "success": True,
            "to": to_email,
            "error": None
        }

    except Exception as e:
        return {
            "success": False,
            "to": to_email,
            "error": str(e)
        }