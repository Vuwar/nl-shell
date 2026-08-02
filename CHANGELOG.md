# Changelog

## [0.3.0](https://github.com/Vuwar/nl-shell/compare/v0.2.0...v0.3.0) (2026-08-02)


### Features

* **fit:** work out how much of the card a model may have ([b80cb0b](https://github.com/Vuwar/nl-shell/commit/b80cb0b675b482e09dc4ca2c9e9c66221b53b917))
* **hardware:** read how much graphics memory is free right now ([bd102f0](https://github.com/Vuwar/nl-shell/commit/bd102f0ea2765d5dc2230e17089d5e18a2b4758a))
* **config:** notice an oversized model, and allow changing it ([57b5ef8](https://github.com/Vuwar/nl-shell/commit/57b5ef85747057df9879fa919474ba4d9048e0f2))
* **server:** say at startup when the card is too full to be quick ([95adb37](https://github.com/Vuwar/nl-shell/commit/95adb37ddf70e12b765702b4b5b438c821620352))
* **session:** explain a slow answer when the card is full ([3e8c60a](https://github.com/Vuwar/nl-shell/commit/3e8c60a8cc657abd6b598e7f1e00d1add12793ed))
* **gui:** expose the model list and the switch to the window ([43a1faf](https://github.com/Vuwar/nl-shell/commit/43a1fafb7724ef8ff0a674a8cd58c7bfefdf713a))
* **cli:** a model command, and a word when the card is full ([e707f39](https://github.com/Vuwar/nl-shell/commit/e707f39f257b19b49def1ba1bab3daf48ebc32d6))
* **gui:** a model picker in settings, and a word when the card is full ([1d210f7](https://github.com/Vuwar/nl-shell/commit/1d210f750e86391c58b08cafe89c70e280038827))
* notice when the graphics card is too full to run the model quickly ([4e09462](https://github.com/Vuwar/nl-shell/commit/4e09462ca9d8fc5c60cc01e9598890b0812fce9f))
* **gui:** let people set how see-through the window is ([bf54108](https://github.com/Vuwar/nl-shell/commit/bf541081ac39534a2dd8af80d3daf2eeafc7e969))
* **progress:** smooth a download's rate and eta ([2dc30b6](https://github.com/Vuwar/nl-shell/commit/2dc30b61187546b55a53b126d7f1223d58d06fdc))
* **weights:** report a download as data, not only prose ([97da543](https://github.com/Vuwar/nl-shell/commit/97da54327846a08f51199d11220eb1b231171cad))
* **server:** add layers and card fit to progress ([3125186](https://github.com/Vuwar/nl-shell/commit/3125186facf2c54f7334eed56689534e8913c6da))
* **gui:** expose the download as data to the panel ([b61009f](https://github.com/Vuwar/nl-shell/commit/b61009fbf9516d45f89dcf6cd8c6457150ef7c88))
* **install:** read the download payload in the panel ([57a731b](https://github.com/Vuwar/nl-shell/commit/57a731b6ac1663e865e4a6c380394dbe3997c4a0))
* **install:** draw the model as a grid of layers ([10f8b27](https://github.com/Vuwar/nl-shell/commit/10f8b271e01dbf4bea3bcaa602483bad72a02fe0))
* **install:** show the model arriving instead of a line of text ([642f570](https://github.com/Vuwar/nl-shell/commit/642f5703ae78a3c70c605706c01cf62dbb7b1997))
* **install:** give the folded tile a beat per layer ([ed61c1b](https://github.com/Vuwar/nl-shell/commit/ed61c1bf328ef9fb40ac463aabb9a42f4dbb92b3))
* **install:** breathe as one block, on a diagonal ([669521e](https://github.com/Vuwar/nl-shell/commit/669521ec82a984dca3a035967c0c1c66f9b8c256))
* **policy:** stop a mislabelled command running unasked ([64f93a2](https://github.com/Vuwar/nl-shell/commit/64f93a2dd56a0ae4f18e9b6eb571fc4414e23025))
* **rules:** answer what has an exact answer, before asking the model ([77ceffd](https://github.com/Vuwar/nl-shell/commit/77ceffd463fdb72f8ea1a8fee83c661716581b46))


### Fixes

* **models:** leave the desktop its share of the graphics card ([1f6884f](https://github.com/Vuwar/nl-shell/commit/1f6884f6eda22ec3978b872e80644b617853aaec))
* **weights:** notice weights an older build downloaded ([3c02665](https://github.com/Vuwar/nl-shell/commit/3c0266540420574faf022ec28dd47dfe6147abcd))
* **server:** fit the model to the card instead of all-or-nothing ([853630d](https://github.com/Vuwar/nl-shell/commit/853630d95707b61a9137a6d5fa549961a1172517))
* **weights:** say nothing when the weights are already here ([b508f0f](https://github.com/Vuwar/nl-shell/commit/b508f0ff1126067893e92d5a3b172dfd1e3d153a))
* **server:** report loading only when something was downloaded ([a72f602](https://github.com/Vuwar/nl-shell/commit/a72f602c3278dbac198b22969d6bd0451f250b03))
* **install:** trace the tile's own edge, not a circle inside it ([7abbc0c](https://github.com/Vuwar/nl-shell/commit/7abbc0c61cf4e986a0ffe5b7049167eeed879bcf))
* **install:** put the ring back on the tile's edge ([9c4b671](https://github.com/Vuwar/nl-shell/commit/9c4b6716a805b1e85b1a5b654658e86e2563c021))
* **install:** say how many layers, not llama.cpp's argument ([ab39baf](https://github.com/Vuwar/nl-shell/commit/ab39baf216de67b171d5572df65fc3813fe21f1c))
* **install:** stop a resting brick reading as an unfilled one ([62c6e95](https://github.com/Vuwar/nl-shell/commit/62c6e95214b9de22ad67056ea64a9a52029a46c9))
* **install:** put every brick on the same clock ([5fce809](https://github.com/Vuwar/nl-shell/commit/5fce8091c4882606493fcd345410ea493d7283c6))
* **policy:** stop treating /dev/null as a file worth protecting ([c782f07](https://github.com/Vuwar/nl-shell/commit/c782f07081ff34554a1cbda5d8ebf74c3a7cd015))


### Performance

* **fit:** fill the card to the measured edge, and stop overstating the cost ([b9868c8](https://github.com/Vuwar/nl-shell/commit/b9868c8aa013e5d03c8580957093ebf3d159846d))

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
