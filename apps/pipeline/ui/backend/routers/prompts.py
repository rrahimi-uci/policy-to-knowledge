"""Prompts router — list and view domain prompts."""

from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import Optional

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # policy-to-knowledge/


def _prompts_base() -> Path:
    return PROJECT_ROOT / "domain-prompts"


def _default_prompts() -> Path:
    return PROJECT_ROOT / "prompts"


@router.get("")
def list_domains():
    """List available domains and the default (base) prompts."""
    base = _prompts_base()
    default_dir = _default_prompts()

    domains = []
    if base.exists():
        for d in sorted(base.iterdir()):
            if d.is_dir():
                prompts = [f.stem for f in sorted(d.glob("*.txt"))]
                domains.append({"name": d.name, "prompts": prompts, "count": len(prompts)})

    # Default/base prompts
    default_prompts = []
    if default_dir.exists():
        default_prompts = [f.stem for f in sorted(default_dir.glob("*.txt"))]

    return {
        "domains": domains,
        "default": {"name": "default", "prompts": default_prompts, "count": len(default_prompts)},
    }


@router.get("/{domain}/{prompt_name}")
def get_prompt(domain: str, prompt_name: str):
    """Get the content of a specific prompt."""
    if domain == "default":
        prompt_file = _default_prompts() / f"{prompt_name}.txt"
    else:
        prompt_file = _prompts_base() / domain / f"{prompt_name}.txt"

    if not prompt_file.exists():
        raise HTTPException(404, f"Prompt '{prompt_name}' not found for domain '{domain}'")

    content = prompt_file.read_text(encoding="utf-8")
    return {
        "domain": domain,
        "name": prompt_name,
        "content": content,
        "size": len(content),
        "lines": content.count("\n") + 1,
    }


@router.put("/{domain}/{prompt_name}")
def update_prompt(domain: str, prompt_name: str, body: dict):
    """Update the content of a specific prompt."""
    content = body.get("content")
    if content is None:
        raise HTTPException(400, "Missing 'content' field")

    if domain == "default":
        prompt_file = _default_prompts() / f"{prompt_name}.txt"
    else:
        prompt_file = _prompts_base() / domain / f"{prompt_name}.txt"

    if not prompt_file.exists():
        raise HTTPException(404, f"Prompt '{prompt_name}' not found for domain '{domain}'")

    prompt_file.write_text(content, encoding="utf-8")
    return {"status": "saved", "domain": domain, "name": prompt_name}
