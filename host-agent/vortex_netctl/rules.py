from __future__ import annotations
import re
from copy import deepcopy

DOMAIN_RE = re.compile(r"^(?:\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)

def normalize_domain(value: str) -> str:
    value = value.strip().lower()
    if not DOMAIN_RE.fullmatch(value): raise ValueError("Enter a domain or *.wildcard domain only")
    return value

def _entry(domain: str) -> dict:
    # sing-box source rule-set v5 supports exact domain and domain_suffix.
    return {"domain_suffix": ["."+domain[2:]]} if domain.startswith("*.") else {"domain": [domain]}

def _decode(rule: dict) -> str | None:
    if set(rule) == {"domain"} and isinstance(rule["domain"], list) and len(rule["domain"]) == 1: return rule["domain"][0]
    if set(rule) == {"domain_suffix"} and isinstance(rule["domain_suffix"], list) and len(rule["domain_suffix"]) == 1: return "*." + rule["domain_suffix"][0].lstrip(".")
    return None

def parse_ruleset(data: dict) -> tuple[list[str], list[str]]:
    if data.get("version") != 5 or not isinstance(data.get("rules"), list): raise ValueError("Expected sing-box source rule-set version 5")
    domains, unsupported = [], []
    for rule in data["rules"]:
        domain = _decode(rule)
        if domain is None: unsupported.append("complex rule")
        else: domains.append(normalize_domain(domain))
    if len(domains) != len(set(domains)): raise ValueError("Duplicate domain entries in rule-set")
    return domains, unsupported

def mutate_ruleset(data: dict, domain: str, remove: bool) -> dict:
    domain = normalize_domain(domain); result = deepcopy(data); domains, _ = parse_ruleset(result)
    if remove:
        result["rules"] = [r for r in result["rules"] if _decode(r) != domain]
    elif domain not in domains:
        result["rules"].append(_entry(domain))
    return result
