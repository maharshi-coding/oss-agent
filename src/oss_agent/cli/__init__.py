"""Command-line interface (thin; delegates to oss_agent.app.Application)."""

from oss_agent.cli.main import build_parser, main

__all__ = ["build_parser", "main"]
