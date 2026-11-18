class RowError(Exception):
    """A problem with one document. It is recorded and the row is retried on a later run."""


class FatalError(Exception):
    """Bad API key / no credits. Stops the whole run instead of failing every row."""
