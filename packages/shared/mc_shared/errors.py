class PlatformError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.type = code


def openai_error(exc: PlatformError) -> dict[str, object]:
    return {"error": {"message": exc.message, "type": exc.type, "code": exc.code}}
