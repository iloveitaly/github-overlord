# GitHub Overlord

GitHub Overlord is a Python script that automatically merges Dependabot PRs in public repositories that have passed CI checks.


## Installation

```shell
pip install github-overlord
```

## Usage

```shell
Usage: github-overlord [OPTIONS]

  Automatically merge dependabot PRs in public repos that have passed CI
  checks

Options:
  --token TEXT  GitHub token, can also be set via GITHUB_TOKEN
  --dry-run     Run script without merging PRs
  --repo TEXT   Only process a single repository
  --help        Show this message and exit.
```

### Docker Cron