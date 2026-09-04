"""Learning reports: teach the developer what a contribution actually does.

Grounded in the real diff, plan, and captured test results — never a generic
narrative. See :func:`build_learning_report`.
"""

from oss_agent.learning.report import build_learning_report, render_learning_report

__all__ = ["build_learning_report", "render_learning_report"]
