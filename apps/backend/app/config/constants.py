from enum import Enum


class Constants:
    ACTION_RESULT = "result"
    ACTION_STATUS = "execution_status"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    MESSAGE = "message"
    STATUS_CODE = "status_code"
    AUTH_SUCCESSFUL = "Authentication successful"
    CREDENTIALS_VALID = "Credentials valid and can perform API calls"
    RESPONSE = "response"


class ErrorMessage:
    INVALID_METHOD = "Invalid HTTP method requested"
    AUTH_FAILED = "Authentication failed"
    CONNECTION_FAILED = "Connection could not be made to the server"
    NO_DATA_RETURNED = "No content returned"
    SERVER_ERROR = "Server side error occurred"


class HttpMethods(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


SUPPORTED_PROVIDERS = ["openai", "anthropic", "gemini", "llama"]

PROVIDER_MODELS = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    "anthropic": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "gemini": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    "llama": ["llama3.1-70b", "llama3.1-8b"],
}

DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 1024

KAFKA_INFERENCE_TOPIC = "inference-events"
KAFKA_METRICS_TOPIC = "metrics-events"
