"""
Generic tools package.

Import all tools to register them in the tool registry.
"""

from . import generic_api
from . import generic_db
from . import generic_email
from . import generic_content
from . import pdf_reader
from . import agent_delegation
from . import web_search

__all__ = [
    "generic_api",
    "generic_db",
    "generic_email",
    "generic_content",
    "pdf_reader",
    "agent_delegation",
    "web_search"
]
