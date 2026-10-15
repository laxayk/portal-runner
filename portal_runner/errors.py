"""Error classes. Retryable errors are retried with backoff. Final errors never are."""


class RunnerError(Exception):
    stage = None


class RetryableError(RunnerError):
    """Timeouts, network blips, element not ready yet."""


class FinalError(RunnerError):
    """Retrying cannot help and may do harm (lockout, bot challenge)."""


class WrongCodeError(FinalError):
    """The second factor was rejected twice."""


class ChallengeError(FinalError):
    """The portal showed a bot check or device check. We stop instead of bypassing it."""


class ResolverExhausted(FinalError):
    """No strategy found exactly one visible element."""

    def __init__(self, target, attempts):
        super().__init__("could not resolve target %r" % target)
        self.target = target
        self.attempts = attempts


class StageFailed(RunnerError):
    def __init__(self, stage, cause, attempts):
        super().__init__("stage %s failed: %s" % (stage, cause.__class__.__name__))
        self.stage = stage
        self.cause = cause
        self.attempts = attempts
