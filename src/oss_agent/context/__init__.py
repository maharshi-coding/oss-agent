"""Repository context selection.

Deterministic infrastructure that builds a compact, inspectable slice of a
repository (likely files, related tests, relevant symbols) *before* implementation
— so the AI backend reasons over a focused, grounded context instead of the whole
repository or only the issue text. Selection is filename/keyword/symbol search;
the *reasoning* over the result stays with the AI layer.
"""

from oss_agent.context.builder import RepositoryContextBuilder
from oss_agent.context.sources import FileSource, GitHubFileSource, LocalFileSource

__all__ = [
    "RepositoryContextBuilder",
    "FileSource",
    "LocalFileSource",
    "GitHubFileSource",
]
