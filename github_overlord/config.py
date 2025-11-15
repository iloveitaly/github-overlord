"""Configuration for github-overlord."""
from pathlib import Path

import jinja2

# Set up paths
ROOT_DIRECTORY = Path(__file__).parent.parent.resolve()
DATA_DIRECTORY = ROOT_DIRECTORY / "data"
RELEASE_ANALYSIS_PROMPT_TEMPLATE = DATA_DIRECTORY / "release_analysis_prompt.j2"

# Jinja2 environment for templates
JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(searchpath=str(DATA_DIRECTORY)),
    autoescape=False,  # No HTML escaping needed for prompts
    trim_blocks=True,
    lstrip_blocks=True
)
