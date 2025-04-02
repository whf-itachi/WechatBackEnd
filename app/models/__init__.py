# app/models/__init__.py
from .user import User
from .ticket import Ticket, Attachment


__all__ = ["User", "Ticket", "Attachment"]
