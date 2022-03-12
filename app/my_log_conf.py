from pydantic import BaseModel

LOGGER_NAME: str = "uvicorn"
LOG_FORMAT: str = "%(levelprefix)s | %(asctime)s | %(message)s"
LOG_LEVEL: str = "DEBUG"


class LogConfig(BaseModel):
    """Logging configuration to be set for the server"""

    # Logging config
    version = 1
    disable_existing_loggers = True
    formatters = {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": LOG_FORMAT,
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    }
    handlers = {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    }
    loggers = {
        f"{LOGGER_NAME}": {"handlers": ["default"], "level": LOG_LEVEL},
        "uvicorn.access": {"handlers": ["default"], "level": LOG_LEVEL},
        # "uvicorn": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.error": {"handlers": ["default"], "level": "ERROR"},
    }
