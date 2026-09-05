# GitHub Overlord

[![Release Notes](https://img.shields.io/github/release/iloveitaly/github-overlord)](https://github.com/iloveitaly/github-overlord/releases) [![Downloads](https://static.pepy.tech/badge/github-overlord/month)](https://pepy.tech/project/github-overlord) [![Python Versions](https://img.shields.io/pypi/pyversions/github-overlord)](https://pypi.org/project/github-overlord) ![GitHub CI Status](https://github.com/iloveitaly/github-overlord/actions/workflows/build_and_publish.yml/badge.svg) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

GitHub Overlord is a Python script that does a couple things to help manage open source projects on GitHub:

* Automatically merges Dependabot PRs in public repositories that have passed CI checks.
* Comment on PRs that are going to automatically be marked as stale
* Removes notifications from bot-authored PRs, Release Please PRs, self-authored PR creations without external activity, and releases on repos you control
* Automatically creates releases for repositories based on LLM analysis of recent commits

This simple project has also given me the chance to iterate on my [nixpacks github actions project](https://github.com/iloveitaly/github-action-nixpacks).

## Installation

```shell
pip install github-overlord
```

## Usage

```shell
Usage: github-overlord [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  generate-releases  Check repositories for release readiness using LLM analysis
  dependabot      Automatically merge dependabot PRs in public repos that...
  keep-alive-prs  Detect when a bot is about to close a PR for no good reason
  notifications   Look at notifications and mark them as read
```

### Automatic Release Creation

The `generate-releases` command uses LLM analysis (via [Pydantic AI](https://ai.pydantic.dev/)) to determine when repositories are ready for a new release. Both `generate-releases` and `keep-alive-prs` share the same unified AI model configuration (defaulting to Google Gemini `gemini-3.8-flash`).

This is particularly useful for template repositories, starter projects, etc that don't have automated release workflows and aren't versioned for whatever reason.

I have a bunch of these and I wanted an easy way to let the world know when I build something interesting in them.

**Usage:**

```shell
# Check all repos with a specific topic
github-overlord generate-releases --topic auto-release

# Check a single repository
github-overlord generate-releases --repo owner/repo-name

# Dry run (see what would happen without creating releases)
github-overlord generate-releases --topic auto-release --dry-run
```

**Requirements & Configuration:**

* `GITHUB_TOKEN` - GitHub token with repo write permissions
* `GITHUB_OVERLORD_AI_KEY` - API key for the AI provider (or provider-specific `GOOGLE_API_KEY`, `OPENAI_API_KEY`, etc.)
* `GITHUB_OVERLORD_MODEL` - (Optional) AI model override (e.g. `gemini-3.8-flash`, `openai:gpt-4o`). Defaults to `gemini-3.8-flash`.
* `--topic` flag or `RELEASE_CHECKER_TOPIC` - Topic to filter repositories (required unless using `--repo`)
* `--repo` flag or `RELEASE_CHECKER_REPO` - Single repository to process (useful for testing)
* `RELEASE_CHECKER_MIN_GAP` - Minimum time between releases for the same repo (defaults to `2w`, e.g. `14d`, `48h`)

**How it works:**

1. Finds repositories matching the specified topic
2. For each repo, gets commits since the last release (or since repo creation if no releases)
3. Analyzes up to the last 50 commits using the configured AI model (defaulting to `gemini-3.8-flash`) to determine if a release is warranted
4. If the LLM recommends a release, automatically creates one with:

    * Auto-incremented semantic version (patch/minor/major based on changes)
    * AI-generated release notes highlighting key changes
    * Link to full changelog

**Scheduling:**
To run this weekly, set the `SCHEDULE` environment variable:

```bash
# Run every Monday at 9 AM
export SCHEDULE="0 9 * * 1"
export RELEASE_CHECKER_TOPIC="template"
# Or, to test a single repo on the schedule:
# export RELEASE_CHECKER_REPO="owner/repo-name"
export GITHUB_TOKEN="your-token"
export GITHUB_OVERLORD_AI_KEY="your-api-key"

# All CLI commands will run on this schedule
python main.py
```

**Troubleshooting:**

* **"No repositories found with topic"**: Make sure your repos have the correct topic tag in GitHub settings
* **"API key environment variable is required"**: Set `GITHUB_OVERLORD_AI_KEY` (or `GOOGLE_API_KEY` for the default Gemini model). Get a free Gemini API key from [ai.google.dev](https://ai.google.dev/)
* **Rate limiting**: The free tier has limits (15-60 requests/minute). Consider adding delays between repos if needed
* **"Failed to create release"**: Ensure `GITHUB_TOKEN` has `repo` scope permissions

### Docker Cron

There's a docker container you can use to run this on a cron. [Fits nicely into a orange pi.](https://mikebian.co/pi-hole-tailscale-and-docker-on-an-orange-pi/)

Check out [docker-compose.yml](./docker-compose.yml) for an example, or `git pull ghcr.io/iloveitaly/github-overlord:latest`.
