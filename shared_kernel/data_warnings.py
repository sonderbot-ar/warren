"""The base class for warnings Warren raises about the data it reads (backlog #196).

Only these become a run's notes; any other warning caught while reading facts (a library's
deprecation, say) is passed on to the log instead of being stored as untranslatable text."""


class DataWarning(UserWarning):
    """A warning Warren raises about the data behind an analysis."""
