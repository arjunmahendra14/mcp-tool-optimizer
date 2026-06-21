"""Load and validate mcpforge.yaml into typed config objects."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env(value: str) -> str:
    """Replace ${VAR} placeholders with environment variable values."""
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


@dataclass
class ServerConfig:
    name: str
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @property
    def is_stdio(self) -> bool:
        return self.command is not None


@dataclass
class ProxyConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    pool_size: int = 4
    queue_wait_timeout: float = 5.0
    pool_wait_timeout: float = 30.0
    health_check_interval: float = 60.0


@dataclass
class OptimizerConfig:
    interval_minutes: int = 15
    default_threshold: float = 10.0
    token_budget: int = 8000
    thresholds: dict[str, float] = field(default_factory=lambda: {
        "incident": 5.0,
        "planning": 15.0,
        "code": 10.0,
        "general": 10.0,
    })


@dataclass
class DatabaseConfig:
    path: str = "mcpforge.db"


@dataclass
class Config:
    servers: list[ServerConfig] = field(default_factory=list)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)


def load_config(path: str = "mcpforge.yaml") -> Config:
    """Load mcpforge.yaml and return a validated Config object."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    raw_servers = data.get("servers", [])
    servers = []
    for s in raw_servers:
        s = dict(s)
        headers = {k: _expand_env(v) for k, v in s.pop("headers", {}).items()}
        env = {k: _expand_env(v) for k, v in s.pop("env", {}).items()}
        servers.append(ServerConfig(**s, headers=headers, env=env))
    proxy_data = data.get("proxy", {})

    # Thresholds is a nested dict — extract before passing to dataclass
    optimizer_raw = dict(data.get("optimizer", {}))
    thresholds_override = optimizer_raw.pop("thresholds", {})
    optimizer_config = OptimizerConfig(**optimizer_raw)
    if thresholds_override:
        optimizer_config.thresholds = {**optimizer_config.thresholds, **thresholds_override}

    database_data = data.get("database", {})

    return Config(
        servers=servers,
        proxy=ProxyConfig(**proxy_data),
        optimizer=optimizer_config,
        database=DatabaseConfig(**database_data),
    )
