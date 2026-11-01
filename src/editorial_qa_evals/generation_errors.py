"""Safe generation failures shared by the HTTP client and offline pipeline."""


class GenerationError(ValueError):
    """A generation invariant failed; no dataset should be published."""


class DeadlineReached(GenerationError):
    """The soft deadline leaves time to persist and publish validated survivors."""
