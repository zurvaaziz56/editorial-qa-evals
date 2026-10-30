"""Safe generation failures shared by the HTTP client and offline pipeline."""


class GenerationError(ValueError):
    """A generation invariant failed; no dataset should be published."""
