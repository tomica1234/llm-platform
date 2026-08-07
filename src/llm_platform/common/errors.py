from dataclasses import dataclass


@dataclass(slots=True)
class PlatformError(Exception):
    code: str
    message: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


class ConfigurationError(PlatformError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_configuration", message, 400, False)


class RouteUnavailableError(PlatformError):
    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(
            "route_unavailable",
            message,
            409 if conflict else 503,
            not conflict,
        )


class AuthorizationError(PlatformError):
    def __init__(self, message: str = "request is not authorized") -> None:
        super().__init__("forbidden", message, 403, False)


class AuthenticationError(PlatformError):
    def __init__(self, message: str = "invalid authentication credentials") -> None:
        super().__init__("invalid_api_key", message, 401, False)
