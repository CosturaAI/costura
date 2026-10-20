# Changelog

## [0.3.0](https://github.com/CosturaAI/costura/compare/v0.2.1...v0.3.0) (2026-10-20)


### Features

* **api:** export worker and scheduler releases as costura_processes ([7fc0225](https://github.com/CosturaAI/costura/commit/7fc02258a738472c9b610d38c56b3492ec7a185b))
* **dev:** add a devcontainer that runs just dev with nothing installed ([a783441](https://github.com/CosturaAI/costura/commit/a783441b7f4080f4a46492e6086223e1438b44f9))
* **dev:** add just db::port to move a checkout's postgres ([671f3df](https://github.com/CosturaAI/costura/commit/671f3dfd18566b0e989d0a19b43a4545857ec4f3))
* **dev:** let each checkout run its own development postgres ([82f8e9b](https://github.com/CosturaAI/costura/commit/82f8e9b728751c0ad7668a37a35da5cb8253af7b))
* **prod:** add prod::doctor, prod::upgrade and a docker-only bundle ([500e713](https://github.com/CosturaAI/costura/commit/500e7137dd6a2bfebe616eb074331687f27b1a77))
* **prod:** write the google client from prod::init ([442f91e](https://github.com/CosturaAI/costura/commit/442f91e5969a4b19f201d6af3ec59b7f3b17e84c))
* **web:** pin a github link band above the public demo ([570d437](https://github.com/CosturaAI/costura/commit/570d437f59837cac098c4e0b9bec3f9cdf3e717d))


### Bug Fixes

* **api:** refuse unparsable settings in one line without the values ([0c11e89](https://github.com/CosturaAI/costura/commit/0c11e895adfd4c750e31417888b77929c0c39c44))
* **ci:** keep the reviewed ci.yml ignore lines for earlier commits ([aa016e1](https://github.com/CosturaAI/costura/commit/aa016e13e2645fab6be352e84ee563679dd7d2ec))
* **dev:** run setup once when just dev creates the .env ([15156b2](https://github.com/CosturaAI/costura/commit/15156b27717b924756333540e6e13e2351e62dca))

## [0.2.1](https://github.com/CosturaAI/costura/compare/v0.2.0...v0.2.1) (2026-10-20)


### Bug Fixes

* **web:** end the cookie-less redirect loop of the public demo home ([41ce5d2](https://github.com/CosturaAI/costura/commit/41ce5d2f1c4c2c55dde0fa4fbcbefba7932bcf78))

## [0.2.0](https://github.com/CosturaAI/costura/compare/v0.1.0...v0.2.0) (2026-10-20)


### Features

* **demo:** serve the public sample from memory and open it at the root ([3a5037d](https://github.com/CosturaAI/costura/commit/3a5037df7c737a737eed39a6e2145191a12ff860))


### Bug Fixes

* keep the reviewed config.py ignore line for earlier commits ([befe573](https://github.com/CosturaAI/costura/commit/befe573766810d7f10c34f4b53eebb5a4a2dfe09))

## 0.1.0 (2026-10-19)


### Features

* first release of costura ([3dd9382](https://github.com/CosturaAI/costura/commit/3dd9382c187ea1725e2fdb2e8addb0f0ca8b0d19))


### Bug Fixes

* **api:** give inbox and queue signals separate kind fields ([d94c2be](https://github.com/CosturaAI/costura/commit/d94c2be50bbd03868e6b54eb115eaa32af35779c))
* **ci:** check the standalone build in the sample organization suite ([d3b69ca](https://github.com/CosturaAI/costura/commit/d3b69cafefdb661f449862e714cd3fe1c1ffc7bb))
* start the first release at 0.1.0 ([fe7fe3c](https://github.com/CosturaAI/costura/commit/fe7fe3cac04887a574ca1d17cacb7432d4998a4e))
