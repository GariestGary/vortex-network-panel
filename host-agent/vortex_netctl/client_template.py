from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


PLACEHOLDERS = {
    "__VORTEX_UUID__",
    "__VORTEX_LAN_HOST__",
    "__VORTEX_LAN_PORT__",
    "__VORTEX_LAN_SSIDS__",
    "__VORTEX_REMOTE_DOMAIN__",
    "__VORTEX_REMOTE_PORT__",
}
REQUIRED_PLACEHOLDER_COUNTS = {
    "__VORTEX_UUID__": 2,
    "__VORTEX_LAN_HOST__": 1,
    "__VORTEX_LAN_PORT__": 1,
    "__VORTEX_LAN_SSIDS__": 1,
    "__VORTEX_REMOTE_DOMAIN__": 3,
    "__VORTEX_REMOTE_PORT__": 1,
}
PLACEHOLDER_PATTERN = re.compile(r"__VORTEX_[A-Z0-9_]*__")


class ClientTemplateError(ValueError):
    pass


def _walk_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    elif isinstance(value, str):
        yield value


def validate_template(template: Any) -> None:
    if not isinstance(template, dict):
        raise ClientTemplateError("Client template must be a JSON object")
    values = list(_walk_values(template))
    unknown = sorted({value for value in values if PLACEHOLDER_PATTERN.fullmatch(value) and value not in PLACEHOLDERS})
    if unknown:
        raise ClientTemplateError("Client template contains an unknown placeholder")
    for placeholder, minimum in REQUIRED_PLACEHOLDER_COUNTS.items():
        if values.count(placeholder) < minimum:
            raise ClientTemplateError("Client template is missing a required placeholder")


def load_template(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as template_file:
            template = json.load(template_file)
    except FileNotFoundError as exc:
        raise ClientTemplateError("Client template is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise ClientTemplateError("Client template JSON is invalid") from exc
    except OSError as exc:
        raise ClientTemplateError("Client template is unavailable") from exc
    validate_template(template)
    return template


def _replace(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, str) and value in replacements:
        return deepcopy(replacements[value])
    return value


def render_client_template(path: Path, *, uuid: str, lan_host: str, lan_port: int, lan_ssids: tuple[str, ...] | list[str], remote_domain: str, remote_port: int) -> dict[str, Any]:
    template = load_template(path)
    rendered = _replace(template, {
        "__VORTEX_UUID__": uuid,
        "__VORTEX_LAN_HOST__": lan_host,
        "__VORTEX_LAN_PORT__": lan_port,
        "__VORTEX_LAN_SSIDS__": list(lan_ssids),
        "__VORTEX_REMOTE_DOMAIN__": remote_domain,
        "__VORTEX_REMOTE_PORT__": remote_port,
    })
    remaining = [value for value in _walk_values(rendered) if PLACEHOLDER_PATTERN.search(value)]
    if remaining:
        raise ClientTemplateError("Client template contains an unresolved placeholder")
    return rendered