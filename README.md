[![Release Notes](https://img.shields.io/github/release/iloveitaly/github-overlord)](https://github.com/iloveitaly/github-overlord/releases) [![Downloads](https://static.pepy.tech/badge/github-overlord/month)](https://pepy.tech/project/github-overlord) [![Python Versions](https://img.shields.io/pypi/pyversions/github-overlord)](https://pypi.org/project/github-overlord) ![GitHub CI Status](https://github.com/iloveitaly/github-overlord/actions/workflows/build_and_publish.yml/badge.svg) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

# GitHub Overlord

GitHub Overlord is a Python script that does a couple things to help manage open source projects on GitHub:

* Automatically merges Dependabot PRs in public repositories that have passed CI checks.
* Comment on PRs that are going to automatically be marked as stale
* Removes notifications from dependabot and releases on your own projects
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
  check-releases  Check repositories for release readiness using LLM analysis
  dependabot      Automatically merge dependabot PRs in public repos that...
  keep-alive-prs  Detect when a bot is about to close a PR for no good reason
  notifications   Look at notifications and mark them as read
```

### Automatic Release Creation

The `check-releases` command uses LLM analysis (via [Pydantic AI](https://ai.pydantic.dev/) with Google Gemini) to determine when repositories are ready for a new release. Pydantic AI makes it easy to swap between different LLM providers if needed. This is particularly useful for:

- Template repositories or starter projects that don't have automated release workflows
- Projects where you want an AI to decide when enough changes have accumulated
- Maintaining regular release cadence across multiple repositories

**Usage:**

```shell
# Check all repos with a specific topic
github-overlord check-releases --topic template

# Check a single repository
github-overlord check-releases --repo owner/repo-name

# Dry run (see what would happen without creating releases)
github-overlord check-releases --topic starter --dry-run
```

**Requirements:**
- `GITHUB_TOKEN` environment variable (with repo write permissions)
- `GOOGLE_API_KEY` environment variable ([Get a free API key](https://ai.google.dev/))
- Optionally: `RELEASE_CHECKER_TOPIC` environment variable for default topic filtering

**How it works:**
1. Finds repositories matching the specified topic (or all your public repos if no topic specified)
2. For each repo, gets commits since the last release (or since repo creation if no releases)
3. Analyzes up to the last 50 commits using Gemini to determine if a release is warranted
4. If the LLM recommends a release, automatically creates one with:
   - Auto-incremented semantic version (patch/minor/major based on changes)
   - AI-generated release notes highlighting key changes
   - Link to full changelog

### Docker Cron

There's a docker container you can use to run this on a cron. [Fits nicely into a orange pi.](https://mikebian.co/pi-hole-tailscale-and-docker-on-an-orange-pi/)

Check out [docker-compose.yml](./docker-compose.yml) for an example, or `git pull ghcr.io/iloveitaly/github-overlord:latest`.