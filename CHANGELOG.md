# [0.8.0](https://github.com/iloveitaly/github-overlord/compare/v0.7.2...v0.8.0) (2025-11-15)


### Features

* plan automated release detection using GitHub API ([#158](https://github.com/iloveitaly/github-overlord/issues/158)) ([aefbccc](https://github.com/iloveitaly/github-overlord/commit/aefbccc9c3bcc1a2fa4263161ab8f78610d5b6f3))



## [0.9.0](https://github.com/iloveitaly/github-overlord/compare/v0.8.0...v0.9.0) (2026-09-12)


### Features

* add AI model configuration and agent utilities ([5015f30](https://github.com/iloveitaly/github-overlord/commit/5015f30f91b685f897294d4b20d7d5fe7bc96554))
* clean self-authored PR notifications without activity ([643e22d](https://github.com/iloveitaly/github-overlord/commit/643e22d2604e9f9081cf10891b723f539981ac92))
* **dependabot:** track and report merge results summary ([59aa2bd](https://github.com/iloveitaly/github-overlord/commit/59aa2bdd67eb2fc7e4d366615dd9816390556479))
* limit max releases created per run in release checker ([86caa49](https://github.com/iloveitaly/github-overlord/commit/86caa495e488c747adc311c4e79d41ee05a0c598))
* **notifications:** add cleanup rules for handled pull requests ([c09eb4c](https://github.com/iloveitaly/github-overlord/commit/c09eb4c5f5501f593f0a61b6c0743e86d29d1f32))
* **notifications:** add notification cleanup command ([2e33381](https://github.com/iloveitaly/github-overlord/commit/2e3338119d55f85765705bee996a77baaf6e24b3))
* **release:** add configurable minimum gap between releases ([414b34a](https://github.com/iloveitaly/github-overlord/commit/414b34a4b160aafbec78416c12a3bb6e6f778bbe))
* use URL-keyed caching in PyGithub patches ([8647ad6](https://github.com/iloveitaly/github-overlord/commit/8647ad6c77558df65e3a8e3580a23ad993572e78))


### Bug Fixes

* **stale:** skip already-replied PRs and exclude drafts ([d08d0b7](https://github.com/iloveitaly/github-overlord/commit/d08d0b74a70df6f01c0e1975ae859957a189c5ab))
* validate AI key configuration and improve CLI errors ([bb5b4d9](https://github.com/iloveitaly/github-overlord/commit/bb5b4d966ec5df7a69346acdc1455b9a70d91572))


### Documentation

* clarify and reorder release analysis instructions in prompt ([1fde9aa](https://github.com/iloveitaly/github-overlord/commit/1fde9aaeb0ae0ba0e436adf9d1d99ca75849c138))
* clarify changelog guidelines to exclude more changes ([188f4bd](https://github.com/iloveitaly/github-overlord/commit/188f4bdeba279fa9378ca4ecc9e93d62e7a66a65))
* describe release checking logic in release_checker.py ([11208d0](https://github.com/iloveitaly/github-overlord/commit/11208d06e13129a127255e4d0068c26e6074543d))
* rename check-releases to generate-releases in docs and config ([c6c84ef](https://github.com/iloveitaly/github-overlord/commit/c6c84ef4101793037e0ac73ff9d9b25b4ad6717e))
* update AI model configuration and notification features in README ([313b77a](https://github.com/iloveitaly/github-overlord/commit/313b77aa5a6293d4d2c28e978565a3dd4fcfa3c1))
* update developer workflow and python instructions ([c346eb3](https://github.com/iloveitaly/github-overlord/commit/c346eb3cb21dade401db556482746fa73b1ff90d))
* update list of auto-dismissed notifications in README ([29d098a](https://github.com/iloveitaly/github-overlord/commit/29d098ace29cf7d9f3d3c6d442146618783777f1))
* update notification handling description in README ([5e67f2c](https://github.com/iloveitaly/github-overlord/commit/5e67f2ccfeb2d62982db53f62e7d389449917aad))
* update README layout and attribution link ([11fec4d](https://github.com/iloveitaly/github-overlord/commit/11fec4dbf6f354735df213a4ddc316c1d9cf0b0d))

## [0.7.2](https://github.com/iloveitaly/github-overlord/compare/v0.7.1...v0.7.2) (2024-10-27)


### Bug Fixes

* typo ([a6f3175](https://github.com/iloveitaly/github-overlord/commit/a6f3175e60bbff0a6cc4e20733267df792c3e5e0))



## [0.7.1](https://github.com/iloveitaly/github-overlord/compare/v0.7.0...v0.7.1) (2024-08-20)


### Bug Fixes

* better overlord logging ([28f7953](https://github.com/iloveitaly/github-overlord/commit/28f79539b182d25aae2d31338eb15387fe0fdca2))



# [0.7.0](https://github.com/iloveitaly/github-overlord/compare/v0.6.9...v0.7.0) (2024-08-15)


### Bug Fixes

* clear notificaitons for merged pull requests that you authored ([4b0de04](https://github.com/iloveitaly/github-overlord/commit/4b0de046da93b0fc7356947477d3bfb1ca75c823))
* log command that is being run ([0a20df5](https://github.com/iloveitaly/github-overlord/commit/0a20df5a22ebb1f372f6ca516b0c6aad1670392c))


### Features

* add notifications command click integration ([399cd28](https://github.com/iloveitaly/github-overlord/commit/399cd28befe5f84842645cb0c8d11982cd9d71a7))
* initial notification cleanup logic is working ([654a8c2](https://github.com/iloveitaly/github-overlord/commit/654a8c23e69d74e054132d5f7601c9d299edfc37))



## [0.6.9](https://github.com/iloveitaly/github-overlord/compare/v0.6.8...v0.6.9) (2024-07-26)


### Bug Fixes

* try catching system exit instead ([649ae27](https://github.com/iloveitaly/github-overlord/commit/649ae274f4f3c8fbd8e957449534d28315d30011))
