# Changelog

## [0.4.0](https://github.com/Vuwar/nl-shell/compare/v0.3.0...v0.4.0) (2026-08-02)


### Features

* **cli:** show the risky command, and let it be edited ([6258d9e](https://github.com/Vuwar/nl-shell/commit/6258d9e323020587e7eec26aba170368de640cd2))
* **fetch:** resume a download instead of starting it again ([c1376d6](https://github.com/Vuwar/nl-shell/commit/c1376d6516abd5fcc4da32bdd356941a7d45edde))
* fit the model to the card, show the download arriving, and answer what has an exact answer ([#5](https://github.com/Vuwar/nl-shell/issues/5)) ([f6aa40f](https://github.com/Vuwar/nl-shell/commit/f6aa40f45126ef9a47e45e6f95dab9088bd68325))
* **gui:** a try-again button on a failed start, and one message not two ([9420bac](https://github.com/Vuwar/nl-shell/commit/9420bac845fd92d27336288fc23dfb0451d2b043))
* **gui:** let a failed model start be tried again ([eb7c7ea](https://github.com/Vuwar/nl-shell/commit/eb7c7eaf67f87e60090192355a5d7f94988e367e))
* **gui:** show the risky command, and let it be edited ([c514cb1](https://github.com/Vuwar/nl-shell/commit/c514cb117d06b6de780e918706112f463778fd95))
* platform hook for a prefilled input line ([2ff04b3](https://github.com/Vuwar/nl-shell/commit/2ff04b38d7379fc86a161e0dbb238157c4499728))
* publish the desktop app for Windows, macOS and Linux ([d58cc28](https://github.com/Vuwar/nl-shell/commit/d58cc288f550bb4f71d1b9cb9f8c3570dcc971b0))
* record commands the user corrects ([7b0ae54](https://github.com/Vuwar/nl-shell/commit/7b0ae54bf41bf1e41e81fa4f5749f9cd8c784836))
* run_last accepts the user's edit of the command ([12064b8](https://github.com/Vuwar/nl-shell/commit/12064b8c1959ca86d43cc88c76490a739f3e9efd))
* **server:** run the model from a file this app downloaded ([bf2f809](https://github.com/Vuwar/nl-shell/commit/bf2f809470adcef54b4b63fa1ae19424500b6e88))
* update an installed copy in place when a new release lands ([84ef14b](https://github.com/Vuwar/nl-shell/commit/84ef14b2cb400b8f8d4715722b81d8c57c200657))
* **weights:** download the model, resuming what an interrupted one left ([b7a8c2e](https://github.com/Vuwar/nl-shell/commit/b7a8c2ea89e992afede7159d956fe13f98889ccc))
* **weights:** resolve a repo:quant reference to real files ([b662f9f](https://github.com/Vuwar/nl-shell/commit/b662f9f03f5a760408721ed6ec972a8cdb7b71c5))


### Fixes

* **gui:** give the window its own port, not one shared with every copy ([5dd43b9](https://github.com/Vuwar/nl-shell/commit/5dd43b9943286acd023b4ac6de15eed6d32658cc))
* **gui:** keep stray console windows off the desktop ([a7c0aae](https://github.com/Vuwar/nl-shell/commit/a7c0aae1ba1914007a4dab642caba70bffd558da))
* stop the release bot corrupting the pip install URL ([d73cafa](https://github.com/Vuwar/nl-shell/commit/d73cafa7ce22a6c92040285229821990d54c0573))
* **tests:** assert the pip target, not the whole script ([b2364aa](https://github.com/Vuwar/nl-shell/commit/b2364aa372fe1c4e39171cd868d2db8729fdb7aa))
* **tests:** don't require a built front end to check the window's port ([2ababb6](https://github.com/Vuwar/nl-shell/commit/2ababb6f1dd1ad7ae9d9a16a64a3f05c8075481b))

## [0.3.0](https://github.com/Vuwar/nl-shell/compare/v0.2.0...v0.3.0) (2026-08-02)


### Features

* fit the model to the card, show the download arriving, and answer what has an exact answer ([#5](https://github.com/Vuwar/nl-shell/issues/5)) ([f6aa40f](https://github.com/Vuwar/nl-shell/commit/f6aa40f45126ef9a47e45e6f95dab9088bd68325))

## [0.2.0](https://github.com/Vuwar/nl-shell/compare/v0.1.0...v0.2.0) (2026-08-01)


### Features

* **cli:** show the risky command, and let it be edited ([6258d9e](https://github.com/Vuwar/nl-shell/commit/6258d9e323020587e7eec26aba170368de640cd2))
* **fetch:** resume a download instead of starting it again ([c1376d6](https://github.com/Vuwar/nl-shell/commit/c1376d6516abd5fcc4da32bdd356941a7d45edde))
* **gui:** a try-again button on a failed start, and one message not two ([9420bac](https://github.com/Vuwar/nl-shell/commit/9420bac845fd92d27336288fc23dfb0451d2b043))
* **gui:** let a failed model start be tried again ([eb7c7ea](https://github.com/Vuwar/nl-shell/commit/eb7c7eaf67f87e60090192355a5d7f94988e367e))
* **gui:** show the risky command, and let it be edited ([c514cb1](https://github.com/Vuwar/nl-shell/commit/c514cb117d06b6de780e918706112f463778fd95))
* platform hook for a prefilled input line ([2ff04b3](https://github.com/Vuwar/nl-shell/commit/2ff04b38d7379fc86a161e0dbb238157c4499728))
* record commands the user corrects ([7b0ae54](https://github.com/Vuwar/nl-shell/commit/7b0ae54bf41bf1e41e81fa4f5749f9cd8c784836))
* run_last accepts the user's edit of the command ([12064b8](https://github.com/Vuwar/nl-shell/commit/12064b8c1959ca86d43cc88c76490a739f3e9efd))
* **server:** run the model from a file this app downloaded ([bf2f809](https://github.com/Vuwar/nl-shell/commit/bf2f809470adcef54b4b63fa1ae19424500b6e88))
* update an installed copy in place when a new release lands ([84ef14b](https://github.com/Vuwar/nl-shell/commit/84ef14b2cb400b8f8d4715722b81d8c57c200657))
* **weights:** download the model, resuming what an interrupted one left ([b7a8c2e](https://github.com/Vuwar/nl-shell/commit/b7a8c2ea89e992afede7159d956fe13f98889ccc))
* **weights:** resolve a repo:quant reference to real files ([b662f9f](https://github.com/Vuwar/nl-shell/commit/b662f9f03f5a760408721ed6ec972a8cdb7b71c5))


### Fixes

* **gui:** give the window its own port, not one shared with every copy ([5dd43b9](https://github.com/Vuwar/nl-shell/commit/5dd43b9943286acd023b4ac6de15eed6d32658cc))
* **gui:** keep stray console windows off the desktop ([a7c0aae](https://github.com/Vuwar/nl-shell/commit/a7c0aae1ba1914007a4dab642caba70bffd558da))
* **tests:** assert the pip target, not the whole script ([b2364aa](https://github.com/Vuwar/nl-shell/commit/b2364aa372fe1c4e39171cd868d2db8729fdb7aa))
* **tests:** don't require a built front end to check the window's port ([2ababb6](https://github.com/Vuwar/nl-shell/commit/2ababb6f1dd1ad7ae9d9a16a64a3f05c8075481b))

## 0.1.0 (2026-07-31)


### Features

* publish the desktop app for Windows, macOS and Linux ([d58cc28](https://github.com/Vuwar/nl-shell/commit/d58cc288f550bb4f71d1b9cb9f8c3570dcc971b0))


### Fixes

* stop the release bot corrupting the pip install URL ([d73cafa](https://github.com/Vuwar/nl-shell/commit/d73cafa7ce22a6c92040285229821990d54c0573))
