"""Unit tests for agent_harness.tools.generic_email.generic_email_sender."""

from agent_harness.tools import generic_email


class FakeSMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_args = None
        self.sent_message = None
        self.login_error = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        if self.login_error:
            raise self.login_error
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent_message = msg


class TestGenericEmailSender:
    def test_success_sends_with_cc_bcc_and_credentials(self, monkeypatch):
        fake_server = FakeSMTP("smtp.example.com", 587)
        monkeypatch.setattr(generic_email.smtplib, "SMTP", lambda host, port: fake_server)

        result = generic_email.generic_email_sender(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
            from_email="from@example.com",
            to_email="to@example.com",
            subject="Hello",
            body="Body text",
            cc="cc@example.com",
            bcc="bcc@example.com",
        )

        assert result == {"success": True, "to": "to@example.com", "error": None}
        assert fake_server.started_tls is True
        assert fake_server.login_args == ("user", "pass")
        assert fake_server.sent_message["Cc"] == "cc@example.com"
        assert fake_server.sent_message["Bcc"] == "bcc@example.com"

    def test_html_flag_sets_html_mime_subtype(self, monkeypatch):
        fake_server = FakeSMTP("smtp.example.com", 587)
        monkeypatch.setattr(generic_email.smtplib, "SMTP", lambda host, port: fake_server)

        generic_email.generic_email_sender(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
            from_email="from@example.com",
            to_email="to@example.com",
            subject="Hello",
            body="<b>Body</b>",
            html=True,
        )

        body_part = fake_server.sent_message.get_payload()[0]
        assert body_part.get_content_subtype() == "html"

    def test_smtp_error_is_caught_and_reported(self, monkeypatch):
        fake_server = FakeSMTP("smtp.example.com", 587)
        fake_server.login_error = OSError("auth failed")
        monkeypatch.setattr(generic_email.smtplib, "SMTP", lambda host, port: fake_server)

        result = generic_email.generic_email_sender(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="wrong",
            from_email="from@example.com",
            to_email="to@example.com",
            subject="Hello",
            body="Body",
        )

        assert result["success"] is False
        assert result["to"] == "to@example.com"
        assert "auth failed" in result["error"]
