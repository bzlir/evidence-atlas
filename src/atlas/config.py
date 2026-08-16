from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 7331
    token: str = ""


class ProjectConfig(BaseModel):
    id: str
    name: str
    path: str


class Config(BaseModel):
    server: ServerConfig = ServerConfig()
    projects: list[ProjectConfig] = []
    default_domain_account: str = ""


def load_config(path: str | Path | None = None) -> Config:
    import os
    import tomllib

    if path is None:
        path = Path("config.toml")
    path = Path(path)

    if not path.exists():
        token = os.environ.get("ATLAS_TOKEN", "")
        return Config(server=ServerConfig(token=token))

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg = Config.model_validate(raw)

    if not cfg.server.token:
        cfg.server.token = os.environ.get("ATLAS_TOKEN", "")
    return cfg
