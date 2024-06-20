[![Release Notes](https://img.shields.io/github/release/iloveitaly/github-overlord)](https://github.com/iloveitaly/github-overlord/releases) [![Downloads](https://static.pepy.tech/badge/github-overlord/month)](https://pepy.tech/project/github-overlord) [![Python Versions](https://img.shields.io/pypi/pyversions/github-overlord)](https://pypi.org/project/github-overlord) ![GitHub CI Status](https://github.com/iloveitaly/github-overlord/actions/workflows/build_and_publish.yml/badge.svg) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

# GitHub Overlord

GitHub Overlord is a Python script that does a couple things to help manage open source projects on GitHub:

* Automatically merges Dependabot PRs in public repositories that have passed CI checks.
* Comment on PRs that are going to automatically be marked as stale
* Removes notifications from dependabot and releases on your own projects

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
  dependabot      Automatically merge dependabot PRs in public repos that...
  keep-alive-prs
```

### Docker Cron

There's a docker container you can use to run this on a cron. [Fits nicely into a orange pi.](https://mikebian.co/pi-hole-tailscale-and-docker-on-an-orange-pi/)

Check out [docker-compose.yml](./docker-compose.yml) for an example, or `git pull ghcr.io/iloveitaly/github-overlord:latest`.