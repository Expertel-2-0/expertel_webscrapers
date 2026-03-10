"""
Abstract base classes for the Mailable email pattern.

Defines the contract that all email types must implement and the interface
for email delivery backends.
"""

from abc import ABC, abstractmethod


class Mailable(ABC):
    """Abstract base class that defines the contract for all email types."""

    @abstractmethod
    def get_subject(self) -> str:
        """Get the email subject line."""

    @abstractmethod
    def get_from_email(self) -> str:
        """Get the sender email address."""

    @abstractmethod
    def get_to(self) -> list[str]:
        """Get the list of recipient email addresses."""

    @abstractmethod
    def get_template(self) -> str:
        """Get the path to the HTML template."""

    @abstractmethod
    def get_context(self) -> dict:
        """Get the template context variables."""

    @abstractmethod
    def get_text_content(self) -> str:
        """Get the plain text fallback content."""


class EmailBackend(ABC):
    """Abstract base class for email delivery mechanisms."""

    @abstractmethod
    def send(self, mailable: Mailable) -> None:
        """Send an email synchronously."""
