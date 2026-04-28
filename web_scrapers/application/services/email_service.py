"""
Email service and Django email backend for the mailable pattern.

Provides the EmailService orchestrator and a concrete DjangoEmailBackend
that renders HTML templates and sends via Django's SMTP integration.
"""

import logging

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from web_scrapers.domain.mailables.base import EmailBackend, Mailable

logger = logging.getLogger(__name__)


class DjangoEmailBackend(EmailBackend):
    """Concrete email backend using Django's built-in email system."""

    def send(self, mailable: Mailable) -> None:
        """
        Send an email using Django's SMTP backend.

        Renders the HTML template from the mailable, attaches it as an
        alternative to the plain-text body, and sends.

        Args:
            mailable: A Mailable instance with all email data.
        """
        subject = mailable.get_subject()
        from_email = mailable.get_from_email()
        to = mailable.get_to()
        text_content = mailable.get_text_content()
        html_content = render_to_string(mailable.get_template(), mailable.get_context())

        if to:
            email = EmailMultiAlternatives(subject, text_content, from_email, to)
            email.attach_alternative(html_content, "text/html")
            for filename, content, mimetype in mailable.get_attachments():
                email.attach(filename, content, mimetype)
            email.send()


class EmailService:
    """Main service for email operations using the mailable pattern."""

    def __init__(self, backend: EmailBackend):
        """
        Initialize the email service with a delivery backend.

        Args:
            backend: An EmailBackend implementation for sending emails.
        """
        self.backend = backend

    def send(self, mailable: Mailable) -> None:
        """
        Send an email through the configured backend.

        Args:
            mailable: A Mailable instance to send.
        """
        self.backend.send(mailable)