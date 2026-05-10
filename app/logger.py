import logging
import logging.handlers
import os
import json
from datetime import datetime, timezone


# ── ANSI colours for console ──────────────────────────────────────────────────
COLOURS = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # green
    "WARNING":  "\033[33m",   # yellow
    "ERROR":    "\033[31m",   # red
    "CRITICAL": "\033[35m",   # magenta
    "RESET":    "\033[0m",
}


class ColouredFormatter(logging.Formatter):
    """Human-readable coloured formatter for console output."""

    FMT = "{colour}[{levelname:<8}]{reset} {asctime} | {name:<35} | {message}"

    def format(self, record: logging.LogRecord) -> str:
        colour = COLOURS.get(record.levelname, "")
        reset  = COLOURS["RESET"]
        formatter = logging.Formatter(
            self.FMT.format(colour=colour, reset=reset, levelname="{levelname}",
                            asctime="{asctime}", name="{name}", message="{message}"),
            datefmt="%H:%M:%S",
            style="{",
        )
        return formatter.format(record)


class JSONFormatter(logging.Formatter):
    """
    Structured JSON formatter for file/production output.
    Every log line is a valid JSON object — easy to ship to Datadog, Loki, etc.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level":     record.levelname,
            "logger":    record.name,
            "message":   record.getMessage(),
            "module":    record.module,
            "function":  record.funcName,
            "line":      record.lineno,
        }
        # Attach any extra fields passed via `extra={}`
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = val

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def setup_logging(log_level: str = "INFO", log_file: str = "logs/bioguard.log") -> None:
    """
    Call once at application startup (in main.py lifespan).
    Sets up console + rotating file handlers on the root logger.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Clear any existing handlers (prevents duplicates on hot reload)
    root.handlers.clear()

    # ── Console handler ───────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(ColouredFormatter())
    root.addHandler(console)

    # ── Rotating file handler (JSON) ──────────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,   # 10 MB per file
        backupCount=5,                # keep 5 rotated files
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(JSONFormatter())
    root.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("bioguard").info(
        "Logging initialised",
        extra={"log_level": log_level, "log_file": log_file},
    )


def get_logger(name: str) -> logging.Logger:
    """Returns a named logger scoped under 'bioguard.*'."""
    return logging.getLogger(f"bioguard.{name}")
