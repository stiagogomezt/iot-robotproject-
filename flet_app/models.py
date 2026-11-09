from dataclasses import dataclass


@dataclass
class Message:
    topic: str
    payload: str


@dataclass
class LogEntry:
    timestamp: str
    direction: str  # "RX" o "TX" o "SYS"
    topic: str
    payload: str
