# https://raw.githubusercontent.com/dependabot/fetch-metadata/main/src/dependabot/update_metadata.ts

import re
import yaml
from typing import Callable, List, Optional, Protocol, TypedDict


class DependencyAlert(TypedDict):
    alertState: str
    ghsaId: str
    cvss: float


class UpdatedDependency(DependencyAlert, total=False):
    dependencyName: str
    dependencyType: str
    updateType: str
    directory: str
    packageEcosystem: str
    targetBranch: str
    prevVersion: str
    newVersion: str
    compatScore: float
    maintainerChanges: bool
    dependencyGroup: str


class AlertLookup(Protocol):
    def __call__(
        self, dependencyName: str, dependencyVersion: str, directory: str
    ) -> "Awaitable[DependencyAlert]":
        pass


class ScoreLookup(Protocol):
    def __call__(
        self, dependencyName: str, previousVersion: str, newVersion: str, ecosystem: str
    ) -> "Awaitable[float]":
        pass


async def parse(
    commitMessage: str,
    body: str,
    branchName: str,
    mainBranch: str,
    lookup: Optional[AlertLookup] = None,
    getScore: Optional[ScoreLookup] = None,
) -> List[UpdatedDependency]:
    bump_re = r"^Bumps .* from (?P<from>v?\d[^ ]*) to (?P<to>v?\d[^ ]*)\.$"
    update_re = (
        r"^Update .* requirement from \S*? ?(?P<from>v?\d\S*) to \S*? ?(?P<to>v?\d\S*)$"
    )
    yaml_re = r"-{3}\n(?P<dependencies>[\S|\s]*?)\n\.{3}\n"
    group_re = r"dependency-group:\s(?P<name>\S*)"

    bump_match = re.search(bump_re, commitMessage, re.MULTILINE)
    update_match = re.search(update_re, commitMessage, re.MULTILINE)
    yaml_match = re.search(yaml_re, commitMessage, re.MULTILINE)
    group_match = re.search(group_re, commitMessage, re.MULTILINE)

    new_maintainer = bool(re.search(r"Maintainer changes", body, re.MULTILINE))
    lookup_fn = (
        lookup
        if lookup
        else (lambda *args: {"alertState": "", "ghsaId": "", "cvss": 0})
    )
    score_fn = getScore if getScore else (lambda *args: 0)

    if yaml_match and branchName.startswith("dependabot"):
        data = yaml.safe_load(yaml_match.group("dependencies"))
        delim = branchName[10]
        chunks = branchName.split(delim)
        prev = (
            bump_match.group("from")
            if bump_match
            else (update_match.group("from") if update_match else "")
        )
        next = (
            bump_match.group("to")
            if bump_match
            else (update_match.group("to") if update_match else "")
        )
        dependency_group = group_match.group("name") if group_match else ""

        if "updated-dependencies" in data:

            async def create_dependency(dependency, index):
                dirname = f"/{'/'.join(chunks[2:-1 * (1 + dependency['dependency-name'].count('/'))]) or ''}"
                last_version = prev if index == 0 else ""
                next_version = next if index == 0 else ""
                update_type = dependency.get(
                    "update-type", calculate_update_type(last_version, next_version)
                )
                return UpdatedDependency(
                    dependencyName=dependency["dependency-name"],
                    dependencyType=dependency["dependency-type"],
                    updateType=update_type,
                    directory=dirname,
                    packageEcosystem=chunks[1],
                    targetBranch=mainBranch,
                    prevVersion=last_version,
                    newVersion=next_version,
                    compatScore=await score_fn(
                        dependency["dependency-name"],
                        last_version,
                        next_version,
                        chunks[1],
                    ),
                    maintainerChanges=new_maintainer,
                    dependencyGroup=dependency_group,
                    **await lookup_fn(
                        dependency["dependency-name"], last_version, dirname
                    ),
                )

            return [
                await create_dependency(dependency, index)
                for index, dependency in enumerate(data["updated-dependencies"])
            ]

    return []


def calculate_update_type(last_version: str, next_version: str) -> str:
    if not last_version or not next_version or last_version == next_version:
        return ""

    last_parts = last_version.lstrip("v").split(".")
    next_parts = next_version.lstrip("v").split(".")

    if last_parts[0] != next_parts[0]:
        return "version-update:semver-major"
    if len(last_parts) < 2 or len(next_parts) < 2 or last_parts[1] != next_parts[1]:
        return "version-update:semver-minor"
    return "version-update:semver-patch"
