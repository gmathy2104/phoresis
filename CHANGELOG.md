# Changelog

All notable changes to Phoresis are documented here.

This file is auto-generated from [Conventional Commits](https://www.conventionalcommits.org/)
by [release-please](https://github.com/googleapis/release-please) on every tagged release.

For a human-readable explanation of each phase milestone, see `docs/specs/`.

---

## [1.3.0](https://github.com/gmathy2104/phoresis/compare/v1.2.0...v1.3.0) (2026-11-21)


### Features

* guided tours of every page, with Driver.js ([407d168](https://github.com/gmathy2104/phoresis/commit/407d16866b3ce43591c1bb8246323afa692eb1a2))

## [1.2.0](https://github.com/gmathy2104/phoresis/compare/v1.1.1...v1.2.0) (2026-11-20)


### Features

* **gel_analyzer:** filters, sorting and assay on the gel list pages ([53878fe](https://github.com/gmathy2104/phoresis/commit/53878fe2c03023b8d0f99155df911a0a65f305fa))
* **gel_analyzer:** gel assays, HCP reference lane, calibration range and saturation fields ([a8c83e1](https://github.com/gmathy2104/phoresis/commit/a8c83e199b5fa630b7fed5a85524e5269cb4e5b2))
* **gel_analyzer:** gel dashboard — pick gels and lanes, see them with the gel widgets ([f184ed3](https://github.com/gmathy2104/phoresis/commit/f184ed307eed7b2697e01d9f9c8868b57146fd54))
* **gel_analyzer:** ONNX Runtime Web is vendored — no CDN left in the app ([b370008](https://github.com/gmathy2104/phoresis/commit/b370008e69b91fddcaf0f10f91e06702a5cb1bbd))
* **gel_analyzer:** resync the calculation services with ds-hub-django ([14ef7a9](https://github.com/gmathy2104/phoresis/commit/14ef7a9b27fe02f527cdaf7a75b24b24620050c9))
* **gel_analyzer:** resync the views, API, forms and tasks with ds-hub-django ([b5d5900](https://github.com/gmathy2104/phoresis/commit/b5d5900e9668bec91cb33d444a1bd9ea8efd4b41))
* **gel_analyzer:** resync the Word, Excel and PowerPoint reports with ds-hub-django ([4046441](https://github.com/gmathy2104/phoresis/commit/40464412772e6a9de51e8b09046503b1f176ff04))
* **gel_analyzer:** the workbench front end of ds-hub-django — editor, densitometry, comparison ([f067943](https://github.com/gmathy2104/phoresis/commit/f067943b49583a9363f3918fd4228006aa689212))


### Bug fixes

* **deps:** keep OpenCV, numpy and scipy where the detector is validated ([8a63606](https://github.com/gmathy2104/phoresis/commit/8a63606b24e326c5c16b60b5a2f4b616359916eb))
* **gel_analyzer:** keep Phoresis's calibration fixes through the resync ([9769bcd](https://github.com/gmathy2104/phoresis/commit/9769bcdef4c0b5b0c13f01d6668f45b9ee4bbdb1))
* **gel_analyzer:** ship the ONNX Runtime source map, or the release does not boot ([4096fd9](https://github.com/gmathy2104/phoresis/commit/4096fd9b06c8e9e99037a57c3e18e92aedd9bb87))
* green CI on main — band model tests without LFS, vulnerable indirect dependencies ([ed814ee](https://github.com/gmathy2104/phoresis/commit/ed814ee6a73027bd92ee5a976d302d8021515eb1))

## [1.1.1](https://github.com/gmathy2104/phoresis/compare/v1.1.0...v1.1.1) (2026-05-08)


### Bug fixes

* **docker:** bump Watchtower DOCKER_API_VERSION 1.41 -&gt; 1.44 ([532306a](https://github.com/gmathy2104/phoresis/commit/532306ad088f1b8b7de60f50c9a507818efdc430))

## [1.1.0](https://github.com/gmathy2104/phoresis/compare/v1.0.41...v1.1.0) (2026-05-08)


### Features

* **admin:** register quantification models + add CALIBRATION badge color ([abb3330](https://github.com/gmathy2104/phoresis/commit/abb3330b803558894c0f8be8c8319b2dbd5ce143))
* **analyses:** redirect to annotate view after creating an analysis ([61dd206](https://github.com/gmathy2104/phoresis/commit/61dd206132ce67c4bfb3df2c3cb2a2fb94bf00db))
* **annotate:** drop SampleSelector, redesign Properties panel, auto-save sample_name ([2193e22](https://github.com/gmathy2104/phoresis/commit/2193e222cc6f32576685807b6dba7da93c43f346))
* **api:** extend Band/Lane serializers with quantification fields ([a18ead7](https://github.com/gmathy2104/phoresis/commit/a18ead7fa49b9c5471fa8e285967123884ae737d))
* **api:** lane downgrade 409 + ?force=true purge ([7dc362a](https://github.com/gmathy2104/phoresis/commit/7dc362aa638b2166ceeb9be7a91c368dcd228f22))
* **api:** quantification endpoints (GET/POST/preview/history/PATCH/DELETE) ([5ae8d7f](https://github.com/gmathy2104/phoresis/commit/5ae8d7f15083e8b004ce7c28387dace1723eaa53))
* **autosave:** foundation — shared AutoSave helper + extractApiError + 2 events ([d6e4044](https://github.com/gmathy2104/phoresis/commit/d6e4044564a60561b41523e5304ecffbf80d464b))
* **autosave:** step 2 — migrate _updateBand/_createBand/_deleteBand to AutoSave + apply extractApiError ([8a575ce](https://github.com/gmathy2104/phoresis/commit/8a575ce0618431e10e19705c2dd9f9744ae44bcc))
* **autosave:** step 3 — properties-panel listens to AUTOSAVE_OK/FAILED + universal green flash ([c9fb839](https://github.com/gmathy2104/phoresis/commit/c9fb839fe327b752a75a5a3366fa7cff15bae4ea))
* **autosave:** step 4 — surface real error messages from background data refreshes ([4a1e1e3](https://github.com/gmathy2104/phoresis/commit/4a1e1e3a9946d8d783551a4caeb154c33d0a70eb))
* **autosave:** step 5 — wire AutoSave into the densitometry app + extractApiError ([b938e41](https://github.com/gmathy2104/phoresis/commit/b938e41d75aa0f875f589d0f135a95ad7ad90d9b))
* **autosave:** step 6 — sample-comparison error messages include actual server cause ([38fd5a8](https://github.com/gmathy2104/phoresis/commit/38fd5a873bc142a39516d5ef5dc367729b51d368))
* **autosave:** step 7 — apply extractApiError to hot lane + calibration api-client paths ([25147de](https://github.com/gmathy2104/phoresis/commit/25147deaf09b729d08afefddab94a98d2950d9bd))
* **calibration:** legend on the right, ghost excluded points, run-button spacing ([474b362](https://github.com/gmathy2104/phoresis/commit/474b362b228d1e813d243ae5395af5d25485cb5f))
* **calibration:** per-marker exclusion + roomy 2-col modal with residuals table ([ea39dc5](https://github.com/gmathy2104/phoresis/commit/ea39dc560bc9c9b1da15580b2db3235c439f58cb))
* **compare:** grouped table + quantification cols + tint rows ([7bbd716](https://github.com/gmathy2104/phoresis/commit/7bbd716494e4445e7344eae9c7cdc7dca0dfe286))
* **comparison:** align comparison panels with densitometry shape ([ad86c0d](https://github.com/gmathy2104/phoresis/commit/ad86c0d26543fdf8a137d942d56f7f27c871f5b3))
* **densitometry:** chromatogram panel tabs (POI / Quantification curve) ([8c25f49](https://github.com/gmathy2104/phoresis/commit/8c25f49c095b822dcfa8c01b1d60727aa5f1e340))
* **densitometry:** quantification calibration curve chart ([9f0f1ca](https://github.com/gmathy2104/phoresis/commit/9f0f1ca345585df4f5b7b0bc11a5922eff8588d7))
* **densitometry:** quantification modal — fetch + render ([1a0795d](https://github.com/gmathy2104/phoresis/commit/1a0795dc9bc6fa052c92d79317b2e3cc4473abe6))
* **densitometry:** results table refactor (lane-level + drill-down + presets) ([364a3cd](https://github.com/gmathy2104/phoresis/commit/364a3cd50795c6ef059cc49aa9ccb77f207ebea9))
* **densitometry:** rewrite Quantification curve sub-view as interactive D3 chart ([2def48d](https://github.com/gmathy2104/phoresis/commit/2def48d4b2a50852c067f56e804c28a7e44214e5))
* **densitometry:** scaffold quantification calibration modal ([c10d335](https://github.com/gmathy2104/phoresis/commit/c10d335e06408a13190ffde5e03df2a0b926fc27))
* **densito:** per-band measurement table with full panel sync ([9a2ff32](https://github.com/gmathy2104/phoresis/commit/9a2ff327884f9e10490db771a8e5acf7f8cff135))
* **densito:** per-POI bars grouped by lane on POI purity chart ([f6f4f87](https://github.com/gmathy2104/phoresis/commit/f6f4f87936e1f9b000c3d3099a7db8be2e89951e))
* **densito:** quant curve clicks fully select the band ([1087bda](https://github.com/gmathy2104/phoresis/commit/1087bda4b51fd1ca1aa97da50b26f0116a38a45d))
* **detail:** editable lane spreadsheet, annotated gel preview, two-column layout ([77549b6](https://github.com/gmathy2104/phoresis/commit/77549b69e6005d7ebd7665ef0f1194e6ae6512f9))
* **docker:** unify web+worker into single phoresis-app image, switch to uv per-package torch sources ([76bf695](https://github.com/gmathy2104/phoresis/commit/76bf695bf614bef2055f1f9520a039782bcc1296))
* **gel-viewer:** auto-promote lane to CALIBRATION when a band becomes CALIBRATION + align lane color ([865a292](https://github.com/gmathy2104/phoresis/commit/865a292a294d0a9921a84f1c868c7d08950de749))
* **media:** close GelImage upload leaks (post_delete + orphan purge) ([38edf5e](https://github.com/gmathy2104/phoresis/commit/38edf5ef8ae7189710b00967fe8cb2ea7b3edabf))
* **models:** add CALIBRATION to Band.BandType ([c5a10bd](https://github.com/gmathy2104/phoresis/commit/c5a10bdcbb01e85784dddbbb2df5c9957a62ed72))
* **models:** add CALIBRATION to Lane.LaneType ([ac2bdf1](https://github.com/gmathy2104/phoresis/commit/ac2bdf12c6afe748111f23e8e79b03f88f6bca69))
* **models:** add DensitometryResult.estimated_amount{,_unit} ([674038c](https://github.com/gmathy2104/phoresis/commit/674038c0c110c77d2ec1e00176f77a7ce1c99df2))
* **models:** add Lane.loading_volume_ul ([063be88](https://github.com/gmathy2104/phoresis/commit/063be88bb18109b568767984ac4273b19e952aac))
* **models:** add ProteinQuantCalibration with partial unique constraint ([7ca5c2e](https://github.com/gmathy2104/phoresis/commit/7ca5c2e3525428b25cf2182082a746f799d9ad42))
* **models:** add ProteinQuantCalibrationPoint ([2bb4d16](https://github.com/gmathy2104/phoresis/commit/2bb4d165ae75dbee1c876b01955844e732461bb2))
* **models:** migration for CALIBRATION choices ([e62aad7](https://github.com/gmathy2104/phoresis/commit/e62aad7a232f8a2fda2539c25f519691ad374bcf))
* **palette:** fix click trigger, add entity search, keyboard nav, modal centering ([2ef1d3f](https://github.com/gmathy2104/phoresis/commit/2ef1d3f5c6d36da47cc1c603adf360c366722efc))
* protein quantification + densitometry/comparison overhaul ([4ba8945](https://github.com/gmathy2104/phoresis/commit/4ba8945da4c78314b23c44bc1499e1d8d1200982))
* **quantification:** collect calibration/control/sample points ([10f9fae](https://github.com/gmathy2104/phoresis/commit/10f9fae36a748b6601e5137743f8f00a1bf0b949))
* **quantification:** linear/poly2/4PL fitters + inverse predictors ([5286342](https://github.com/gmathy2104/phoresis/commit/5286342926542fe8e537531e6231a9e46f16fbb5))
* **quantification:** project + apply_to_analysis ([2dbd9df](https://github.com/gmathy2104/phoresis/commit/2dbd9df5ef251ee8622e63904b4e551d75e78774))
* **quantification:** recompute_if_active hook + wire into densitometry task ([d93c808](https://github.com/gmathy2104/phoresis/commit/d93c808153dc5f996c9e1b0026609fdb95236898))
* **quantification:** save_active with supersede ([1212fad](https://github.com/gmathy2104/phoresis/commit/1212fad17d049247dc5fffbb0a759b5f5e776dfe))
* **quantification:** scaffold service package + dataclasses ([a4f7507](https://github.com/gmathy2104/phoresis/commit/a4f75072a59249ecaae34c4d2bfdba6b20da5711))
* **quantification:** server auto-promote lane on band-type=CALIBRATION + auto-save calibration amount with green flash ([ac4b9e3](https://github.com/gmathy2104/phoresis/commit/ac4b9e3087e94fc33958741ebec2997415eac1d7))
* **quantification:** service.fit (linear/poly2/4PL with exclusion) ([f14eb80](https://github.com/gmathy2104/phoresis/commit/f14eb8026e42c5b31c7e6aeec4e1b9f3e2c072a6))
* **report:** calibration curve PNG via matplotlib ([ee236cb](https://github.com/gmathy2104/phoresis/commit/ee236cbb79513b52715fa322d0bd805a91e0b563))
* **report:** collect_quantification_data on data collector ([34a8498](https://github.com/gmathy2104/phoresis/commit/34a8498eb6c7c012ccd7e64196d849bc39adf647))
* **report:** Excel quantification sheets ([8e8c890](https://github.com/gmathy2104/phoresis/commit/8e8c8906652a08d5171df9cf9b2ed886b1c3a2ef))
* **reporting:** add Playwright dep + generic page/component renderer service ([2f4d16a](https://github.com/gmathy2104/phoresis/commit/2f4d16a894888a22e5c3c644247d618c5203f0cf))
* **report:** PowerPoint quantification slide ([de8c683](https://github.com/gmathy2104/phoresis/commit/de8c68346f84da593012e5c19e6a7565ae128af1))
* **reports:** align graph styling with live web densitometry panels ([56cb31b](https://github.com/gmathy2104/phoresis/commit/56cb31bb4524233eca24a421bb2bb866e9f92b38))
* **reports:** rebrand to Phoresis tokens + lane-type aware gel overlay ([deec956](https://github.com/gmathy2104/phoresis/commit/deec956e91e944ac5d0975f5b7dacc1cbe3f1b81))
* **reports:** wire PDF format end-to-end via Playwright ([18ae48a](https://github.com/gmathy2104/phoresis/commit/18ae48a3eb2b05d64b04b4b345e3eb3998753748))
* **report:** Word quantification section ([2929977](https://github.com/gmathy2104/phoresis/commit/29299773cb090fa38d153df68171f92ec89d3cb2))
* **scripts:** add devstack for native-Windows Django dev with optional GPU passthrough ([fca36d2](https://github.com/gmathy2104/phoresis/commit/fca36d2b8f64b3eda80a711d41f5799550cd9f0c))
* **ui:** color tokens for CALIBRATION + CONTROL lane/band types ([e255b16](https://github.com/gmathy2104/phoresis/commit/e255b16b56cd3086fa3925a311aac47f79e2fe7e))
* **ui:** vendor bootstrap-icons font for gel-viewer toolbar icons ([ce3fefa](https://github.com/gmathy2104/phoresis/commit/ce3fefad470cca78e923ebe6df46ee00a92e3c44))
* **viewer:** band CALIBRATION + load_amount UI ([08429f9](https://github.com/gmathy2104/phoresis/commit/08429f92d69b8aa10913353202039d51916455bb))
* **viewer:** context menu CALIBRATION types + Set calibration value ([fdfa229](https://github.com/gmathy2104/phoresis/commit/fdfa2294fa00909f46e6831d4175af536548ac0e))
* **viewer:** document CALIBRATION + CONTROL lane overlay support ([c3a6e74](https://github.com/gmathy2104/phoresis/commit/c3a6e7488565019539120c0e5af08c0b43eea8c8))
* **viewer:** lane CALIBRATION + loading_volume_ul properties UI ([838656a](https://github.com/gmathy2104/phoresis/commit/838656a38acbc7b0cac5f856692ab53a451d31ed))
* **viz:** show real integration zone (bbox) + peak max marker on chromatograms ([9e50863](https://github.com/gmathy2104/phoresis/commit/9e5086368ea3712b80c7c58f1a0c678804510e11))


### Bug fixes

* **admin,docs:** docstrings + safe search_fields + model count ([3f00556](https://github.com/gmathy2104/phoresis/commit/3f00556ab73ecea0339c11f58d707997b191ddc5))
* **annotate:** make band split server-consistent and propagate to all panels ([77a848a](https://github.com/gmathy2104/phoresis/commit/77a848a767983cc7e8aa2013ea2c7e949567ae46))
* **api:** tighten Phase 4 per code review (transaction + 404 + 422 + DRY) ([11f2dc8](https://github.com/gmathy2104/phoresis/commit/11f2dc82129df9077451a779d988dff84233e723))
* **calibration:** always compute Rf in the ladder lane's reference frame ([5098739](https://github.com/gmathy2104/phoresis/commit/5098739480ae18a7ba49593200960de1e24860c4))
* **calibration:** drop stale linregress import + add return type hints ([674284c](https://github.com/gmathy2104/phoresis/commit/674284cbc76b02af25ffc551f8737a18f6e3cb82))
* **calibration:** drop template picker from MW calibration modal ([4c2d034](https://github.com/gmathy2104/phoresis/commit/4c2d034c8046fff75d6f82e658e83c6596ae024f))
* **calibration:** match unmatched-template-bands by mw_kda, not band_order ([aaa54f5](https://github.com/gmathy2104/phoresis/commit/aaa54f52b22862b253afb262a1cc5bf690be0592))
* **calibration:** R²=0 on single ladder + template now optional ([94a1336](https://github.com/gmathy2104/phoresis/commit/94a1336c93da07ed88ee95442128820921e22748))
* **calibration:** unmatched-template only flags markers truly absent from gel ([c580606](https://github.com/gmathy2104/phoresis/commit/c580606b6298069f15d1e11af6cd60bf7a8cc53d))
* **celery:** tolerate string queue names in worker_ready boot trigger ([e6e39c0](https://github.com/gmathy2104/phoresis/commit/e6e39c047043e7ca0f7f55e71aeff73e01b4df78))
* **ci:** pin trivy-action to v0.36.0 commit SHA, not a tag ([0e0a0b9](https://github.com/gmathy2104/phoresis/commit/0e0a0b98ffca3a437f6e9f58649fbac17144e529))
* **densito:** contain quant panel to prevent resize scrollbars ([6a20f57](https://github.com/gmathy2104/phoresis/commit/6a20f57d6953400b0e0fb671a44e1b102c9c9e8d))
* **densitometry:** address review on stale-banner gate + sigma fit bound ([be2f2da](https://github.com/gmathy2104/phoresis/commit/be2f2da2f92ec640df3376664166300edde1c317))
* **densitometry:** bump cache buster + sync bbox to top-level on results load ([76d4688](https://github.com/gmathy2104/phoresis/commit/76d468858563705fb4dfc731eda389a86eec31f2))
* **densitometry:** expose bbox_y + bbox_height on results endpoints ([7520ba6](https://github.com/gmathy2104/phoresis/commit/7520ba60f84761350d8792d7ed590a81e9144802))
* **densitometry:** expose estimated_amount + unit on the FBV densitometry endpoint ([4ca9316](https://github.com/gmathy2104/phoresis/commit/4ca9316b4fbcc654745d475c504aa968ac6d67d5))
* **densitometry:** invalidate lane cache on band edits + truncate Gaussian area to bbox ([784c5c8](https://github.com/gmathy2104/phoresis/commit/784c5c8acaf4c929b57b1a75d36a7787fea7dca1))
* **densitometry:** make quantification modal a real overlay (was rendering inline below the page) ([4660b3f](https://github.com/gmathy2104/phoresis/commit/4660b3fa224a9e73ca5d439055cd38ecd7f23139))
* **densitometry:** merge Quantification curve into the Graphical View toggle ([82278cb](https://github.com/gmathy2104/phoresis/commit/82278cb8bce66db7546bdf8b43ca3e575c600da5))
* **densitometry:** preserve quantification container in _createChart wipe ([fc4f4cc](https://github.com/gmathy2104/phoresis/commit/fc4f4cc819256e17285977b0dd20510ff6c05f5f))
* **densitometry:** recovery % uses CONTROL band's quant_point.load_amount ([b88b9db](https://github.com/gmathy2104/phoresis/commit/b88b9dbc24d597365e4a18f468492374002745c3))
* **densitometry:** teach densito panels about CALIBRATION + lane-type colors ([b2f6a4c](https://github.com/gmathy2104/phoresis/commit/b2f6a4c176cee751f1fe90a92218f364016dc721))
* **densito:** rename remaining chartData ref to lanesData on POI chart ([8d6ad55](https://github.com/gmathy2104/phoresis/commit/8d6ad5571ae83aa8e6dd0508e0ec7458929d49c8))
* **dev:** isolate native runserver from polluted DB_* env vars ([1f76076](https://github.com/gmathy2104/phoresis/commit/1f76076d63dbf0f4fc3f8b8cc7d644a2b230c64c))
* **dev:** make devstack worker survive runtime + serve media via runserver ([040dbee](https://github.com/gmathy2104/phoresis/commit/040dbee6d08be235a4d6fa99ba63e9cab2232868))
* **dev:** pin REDIS_HOST/PORT to devstack on bare metal ([0937aa7](https://github.com/gmathy2104/phoresis/commit/0937aa73823686064f9481aa0dfc76b3d400b7ee))
* **devstack:** point worker/beat at host postgres + shared media ([a906289](https://github.com/gmathy2104/phoresis/commit/a906289997f44def986ea170b137a36319138570))
* **file_handler:** fall back to PIL on any tifffile failure, not just ImportError ([453aa46](https://github.com/gmathy2104/phoresis/commit/453aa467c8f9e0a152fe03b286d9517aa02f4b14))
* **gel-viewer:** keep band visuals + properties panel in sync after right-click "Set as Calibration" ([f247b66](https://github.com/gmathy2104/phoresis/commit/f247b66fe8109bad4e5594a1dab6362ee4bb9389))
* **gel-viewer:** use pink for calibration bands so they don't collide with POI purple ([9368bd0](https://github.com/gmathy2104/phoresis/commit/9368bd0f3cd788be846188a3ad8d5657e6e849ef))
* **mw:** round estimated MW to 1 decimal everywhere + back-fill DB ([cd99e9d](https://github.com/gmathy2104/phoresis/commit/cd99e9d7937bb258ce4114e93abccd10c801ee8a))
* **properties-panel:** don't rebuild the form while the user is editing it ([a068811](https://github.com/gmathy2104/phoresis/commit/a0688118450cebfdf39e19baeba875d4f7d9eb7d))
* **quantification-curve:** plot calibration points at load_amount, not predicted_amount ([2f1d106](https://github.com/gmathy2104/phoresis/commit/2f1d10630507a343a8c022b15689cc767a1a212a))
* **quantification:** add predict_linear forward + QC range constant + safe zero guards ([e5ee5a1](https://github.com/gmathy2104/phoresis/commit/e5ee5a18f7a7ef4ba60cb891cb389a153809c598))
* **quantification:** only project POI bands of SAMPLE lanes (was projecting every non-MW band) ([285ab78](https://github.com/gmathy2104/phoresis/commit/285ab78598426cc9515fbc5d0231ff1bc6ed6e8a))
* **quantification:** tighten Phase 3B per code review ([07a2813](https://github.com/gmathy2104/phoresis/commit/07a28131df77c9ea5124671fae448b4034f7209d))
* **quantification:** tighten Phase 3C per code review ([6304a4c](https://github.com/gmathy2104/phoresis/commit/6304a4c2c842eee69501a5e1d69e0fef3655cf86))
* **reports:** correct band colors + boost lane outlines + surface generator on every PPT slide ([8e16350](https://github.com/gmathy2104/phoresis/commit/8e16350e2670478311051cfabfef82fc12ab8989))
* **reports:** paint lane outlines on a layer above band rectangles ([c21cd8b](https://github.com/gmathy2104/phoresis/commit/c21cd8b458ab672aa78dffb8a8f2eb1252bcdea8))
* **routes:** drop stale /gel-analyzer/ prefix from API calls ([5515f75](https://github.com/gmathy2104/phoresis/commit/5515f754b896247b8cdfcb192560b0df66b60cf4))
* **scripts:** align install + dev-env with new PHORESIS_* dev convention ([9728ba3](https://github.com/gmathy2104/phoresis/commit/9728ba3cd0d3624eb5728b53c707b39c0771b2cd))
* **settings:** add DEFAULT_THROTTLE_RATES so v1 viewset writes stop 500ing ([d4f811b](https://github.com/gmathy2104/phoresis/commit/d4f811ba1c60aac01a3ca16e4e1ed72b889c05a1))
* **tasks:** use f-strings in purge_orphan_gel_images log lines ([c496929](https://github.com/gmathy2104/phoresis/commit/c4969299ee4d1baeec8c186cca4f28908d9caec6))
* **templates:** replace broken URL concat with {% url %} tag ([31b64c6](https://github.com/gmathy2104/phoresis/commit/31b64c699d279d05a71518f3e1813b29b1e2bc7b))
* **ui:** make Back button on the three modules actually visible ([8f9e6cc](https://github.com/gmathy2104/phoresis/commit/8f9e6cc70e8dec01b1cd77bc38d104982fbed2cb))
* **viewer:** surface async calib-PATCH errors + null guard in ContextMenu ([74ab5df](https://github.com/gmathy2104/phoresis/commit/74ab5df2d279260268eb2994380ed50eb21e3bef))


### Refactoring

* **calibration:** drop template-completeness UI from the calibration modal ([6f1e853](https://github.com/gmathy2104/phoresis/commit/6f1e853c45933358dc5a1f25592807458c59577e))
* **calibration:** extract fit helpers to fitters_shared (no behavior change) ([7fedf29](https://github.com/gmathy2104/phoresis/commit/7fedf29fb1eb3584b71f675c35d1a323cfb4cc99))


### Documentation

* **gel_analyzer:** note quantification model addition ([0821b19](https://github.com/gmathy2104/phoresis/commit/0821b196e46b9637fd731c10be3550d61f16c78b))
* **install:** document private-repo + private-GHCR install flow ([3424051](https://github.com/gmathy2104/phoresis/commit/342405162f37d9369bf5472816232991fad2a1a0))
* **plans:** protein quantification implementation plan ([5d7ff00](https://github.com/gmathy2104/phoresis/commit/5d7ff009612a476c148227eb4414cedf7ed63972))
* port plan for quantification → ds-hub-django ([1bc0520](https://github.com/gmathy2104/phoresis/commit/1bc052000d786cda05cd85cc2b53bf1710345dfe))
* **specs:** protein quantification feature design ([d470ae7](https://github.com/gmathy2104/phoresis/commit/d470ae78abd4582fa680a68b0cef818c7823dcd5))
* **specs:** tighten quantification design after consistency review ([207c74e](https://github.com/gmathy2104/phoresis/commit/207c74e7db55182cfc175075a611f7a07b43cfe8))

## [1.0.11] - 2026-05-04

### install.ps1 fresh-install crash + SQL syntax fixes

- **`.Trim() on $null` crash** when no legacy `phoresis_media` Docker volume is present (the common case for fresh installs). `docker volume ls -q --filter "name=..."` returns `$null` rather than an empty string when there's no match, and `.Trim()` on `$null` raises `Impossible d'appeler une méthode dans une expression Null` under `Set-StrictMode`. Pipe through `Out-String` so the result is always a string.
- **SQL syntax error** in the DB-provisioning block: the `\gexec` pattern was using `SELECT 'created' WHERE NOT EXISTS ...` which has psql try to execute the literal string `created` as SQL, producing `erreur de syntaxe sur ou près de « created »` on every fresh install. Replaced with two clean steps: `DO $$ ... $$;` for the role (idempotent), then a separate `psql -tAc` existence check followed by a conditional `CREATE DATABASE`. Fixes both the spurious error message and the latent "double-create" bug when re-running on a host where the role already existed.

## [1.0.10] - 2026-05-04

### install.ps1: support coexisting Postgres versions

- New `-DBPort <int>` parameter on `install.ps1` (default 5432) for hosts that already run another Postgres on 5432 — typical case: an existing PG13/14/15/16 on 5432, freshly-installed PG17 forced to 5433. The script now passes `-p $DBPort` to `psql` for DB provisioning and writes `DB_PORT=$DBPort` to `.env`. Detected during the first real install on a workstation that had PG16 + PG17 cohabiting.

## [1.0.9] - 2026-05-04

### install.ps1 robustness fix

- **`winget` resolution in elevated sessions**: `winget.exe` lives under `%LOCALAPPDATA%\Microsoft\WindowsApps` (USER PATH) but admin/elevated PowerShell sessions sometimes inherit only the SYSTEM PATH, leaving `winget` "not found" even when installed. Added `Resolve-Winget` helper in `_common.ps1` that falls back to the well-known location, plus actionable error messages pointing to the manual install URL when winget is genuinely absent.
- **Postgres 17 detection**: also probes `C:\Program Files\PostgreSQL\17\bin\psql.exe` and prepends to `$env:PATH` for the current session if found. Removes the "install Postgres → restart PowerShell → re-run install.ps1" loop when the installer was just run but the new shell hasn't been opened.

## [1.0.8] - 2026-05-04

### CI frontend cache fix

- **`package-lock.json` now committed.** The `actions/setup-node@v5` step in `ci.yml` uses `cache: "npm"` which requires the lockfile to be present in the repo root to compute its cache key. Phase 3 Task 1 had `.gitignored` the lockfile with a note "commit in Phase 5 (Docker reproducibility)" but Phase 5 never honored it — same oversight pattern as `uv.lock`, which was eventually committed in v1.0.0. Fix: dropped `package-lock.json` from `.gitignore` and committed the 46 KB file pinning Tailwind 4.2.4 + 45 transitive deps. Verified locally with a fresh `rm -rf node_modules && npm ci` which completes cleanly.

## [1.0.7] - 2026-05-04

### CI simplification + dev workflow improvements

- **`release.yml` ships CPU images only** (descope CUDA matrix). CUDA users build locally during `install.ps1` — fast on a real GPU machine, avoids GitHub-runner disk/time ceilings, eliminates matrix complexity. Drops 2 of 4 jobs from the release pipeline; CPU build now reliable in ~10 min.
- **`install.ps1` + `update.ps1`** branch on `PHORESIS_IMAGE_VARIANT`: CPU pulls from GHCR, CUDA does `docker compose build --build-arg TORCH_VARIANT=cuda` locally. One-time ~15-25 min build; subsequent rebuilds cheap thanks to the new cache mounts.
- **Dockerfile cache mounts**: added `--mount=type=cache,target=/root/.cache/uv` and `--mount=type=cache,target=/var/cache/apt` to all 4 deps stages (Dockerfile.web + Dockerfile.worker × CPU + CUDA). Marginal pyproject.toml/uv.lock changes now skip re-downloading the unchanged 90% of wheels — local rebuild ~5 min → ~20 s.
- **`docker/compose.dev.yml`**: new dev override that bind-mounts `./src`, `./manage.py`, `./conftest.py` into web + worker + scheduler containers, swaps gunicorn for `manage.py runserver` (Django auto-reloads), and switches `DJANGO_SETTINGS_MODULE` to `dev`. Pair with `npm run watch:css` on the host. Use: `docker compose -f docker/docker-compose.yml -f docker/compose.dev.yml up`.
- **README.md installation section**: rewrote with clear step-by-step (clone → `install.ps1` → first-boot DB setup → daily use → updates → backups → troubleshooting). Documents the auto-run migrations / `seed_groups` / `seed_ladder_templates` / `create_initial_users` flow.

## [1.0.6] - 2026-05-04

### CUDA build runner disk space fix

- **`release.yml` build-and-push job**: added `jlumbroso/free-disk-space@main` step gated on `if: matrix.variant == 'cuda'`. The CUDA images push the ubuntu-24.04 runner past its ~14 GB free disk (CUDA 12.8 base ~3 GB + 90 wheels including duplicated nvidia-cublas/cudnn ~6-8 GB + uv cache). Verified via run 25309016114 logs: `Free space left: 0 MB` then `failed to copy to ... No space left on device (os error 28)` during `uv sync`. The action frees ~28 GB by removing preinstalled Android SDK / .NET / Haskell toolchains we don't need. Targeted with `tool-cache: true` only — leaves docker-images and swap intact.

## [1.0.5] - 2026-05-04

### CUDA build pipeline fix

- **Dockerfile.{web,worker} CUDA stages**: reordered the install steps. Previously installed `torch torchvision` from cu128 first, then ran `uv sync --frozen` — which exited with code 2 because the manually-installed `torch==X.Y.Z+cu128` doesn't match `uv.lock`'s `torch==X.Y.Z` (no local version tag). New order: `uv sync --frozen` first (gets the full dep tree from lockfile, including CPU torch ~700 MB), then `uv pip install --reinstall-package torch --reinstall-package torchvision --extra-index-url cu128 torch torchvision` to swap them for cu128 builds. Adds ~700 MB of redundant download but keeps the lockfile as single source of truth and the build deterministic.

## [1.0.4] - 2026-05-04

### CI workflow validation fix

- **`ci.yml` codecov step**: GitHub Actions rejected the workflow with `Unrecognized named-value: 'secrets'` because `secrets.CODECOV_TOKEN` was used inside an `if:` expression (forbidden anti-exfiltration measure). Hoisted the secret into a job-level `env.CODECOV_TOKEN`, then changed the conditional to `if: env.CODECOV_TOKEN != ''`. Same behavior, valid syntax.

## [1.0.3] - 2026-05-04

### Blackwell (RTX 50-series) GPU support

- **Dockerfile.{web,worker} CUDA stages**: bumped base image from `nvidia/cuda:12.1.1-runtime-ubuntu24.04` to `nvidia/cuda:12.8.0-runtime-ubuntu24.04`, and PyTorch wheel index from `cu121` to `cu128`. CUDA 12.1 didn't include sm_120 PTX, so torch on RTX 50-series would silently fall back to CPU. Verified locally on an RTX 5090 (compute capability 12.0): `torch.cuda.is_available() == True`, `torch.version.cuda == '12.8'`, GEMM 2048×2048 runs on the GPU, all values finite. Backwards-compatible: cu128 supports sm_70+ (Volta and newer), covering RTX 20/30/40/50-series, GTX 16, and Quadro RTX/Tesla V100.
- **`install.ps1` GPU detection**: now also reads `compute_cap` from `nvidia-smi`. If the lowest compute capability across all detected GPUs is < 7.5 (pre-Volta: Pascal GTX 10-series and older), falls back to the CPU image with a clear warning. Override remains possible via `-Variant cuda`.

## [1.0.2] - 2026-05-04

### Build pipeline fixes

- **Dockerfile uv sync**: COPY `uv.lock` alongside `pyproject.toml` and use `uv sync --no-dev --no-install-project --frozen`. Previously the build tried to install the local `phoresis` package during the deps stage and failed with `OSError: Readme file does not exist: README.md` (only `pyproject.toml` was COPY'd at that point). The local package isn't needed during deps install — source is COPY'd later in the runtime stage. Affects all 4 image variants.
- **CUDA base image**: switched from `nvidia/cuda:12.1.1-runtime-ubuntu22.04` + deadsnakes PPA + `python3.12` apt-install (fragile, recently breaking) to `nvidia/cuda:12.1.1-runtime-ubuntu24.04` which ships Python 3.12 natively. Drops `software-properties-common`, `gnupg`, `add-apt-repository` from the CUDA stage.
- **GitHub Actions versions bumped** to clear Node.js 20 deprecation warnings: `actions/checkout@v4 → v5`, `actions/setup-node@v4 → v5`, `astral-sh/setup-uv@v3 → v6`, `codecov/codecov-action@v4 → v5`, `aquasecurity/trivy-action@0.28.0 → 0.30.0`. Docker actions (`setup-buildx-action`, `build-push-action`, `login-action`) stay on v3/v6 — their maintainers will publish Node 24 versions before the June 2026 cutoff.

## [1.0.1] - 2026-05-04

### Post-v1 hardening pass

- Branded `handler400` (Bad request) and `handler403` (Access denied / CSRF failure) pages wired in `phoresis_core.error_handling.views`. Same chrome and CTAs as the existing 404 / 500.
- `prefers-reduced-motion` media query in `input.css` neutralizes ripple, shimmer, dropzone pulse, and long transitions for users with system "Reduce motion" enabled. App stays fully functional.
- `CELERY_WORKER_MAX_TASKS_PER_CHILD = 50` (env-overridable via `CELERY_WORKER_MAX_TASKS_PER_CHILD`) so prefork children recycle to release memory after the ~100 MB ONNX models loaded by band-detection / SAM / densitometry services.

## [1.0.0] - 2026-05-04

### Phase 7 — Polish + docs + v1.0.0

- Micro-interactions: button ripple, HTMX top progress bar, sidebar icon scale on hover, dropzone pulse, floating labels.
- Branded 404 / 500 pages with `PHOR-YYYYMMDD-XXXXXX` reference IDs surfaced from the `ExceptionContextMiddleware`.
- Full documentation suite: root `README.md`, `docs/{ARCHITECTURE,DESIGN,DEVELOPMENT,DEPLOYMENT,INSTALL}.md`, plus per-app `README.md` files (5 apps).
- Pre-v1 cleanup: switched component badge variants to design tokens, escaped `</script>` breakout in `nav_palette_items_json`, made `{% btn disabled=True href=... %}` produce a11y-correct disabled anchors, replaced hardcoded URLs in sidebar + alpine-init with `{% url %}` reverses, removed legacy `_layout.html` (replaced by `app_base.html` in Phase 3), committed `uv.lock` for reproducible Docker builds.
- Media files moved from a Docker named volume to a host bind-mount at `${PHORESIS_MEDIA_DIR}` (default `%USERPROFILE%\Phoresis-Data\media`), so `docker compose down -v` cannot wipe user data.

## [0.6.0] - 2026-05-04

### Phase 6 — CI/CD + install scripts

- `release-please` config + initial `CHANGELOG.md`.
- `ci.yml` extended with frontend build, e2e (Playwright Chromium), Docker image build smoke, Trivy CVE scan.
- `release.yml` with 4-variant matrix build `(cpu, cuda) × (web, worker)`, GHCR push, GitHub Release with SBOM.
- 7 PowerShell scripts: `install.ps1` (clean-machine), `start.ps1` / `stop.ps1` (daily), `update.ps1` (with `-Rollback`), `backup.ps1` / `restore.ps1` (pg_dump + media tar, 30-day retention), plus `_common.ps1` shared helpers.
- Watchtower credentials story documented (PUBLIC GHCR by default, private fallback in 3 steps).

## [0.5.0] - 2026-05-04

### Phase 5 — Docker + Caddy packaging

- Healthz endpoints (`/healthz/`, `/healthz/celery/`, `/healthz/live/`).
- `seed_groups` management command.
- Multi-stage `Dockerfile.web` and `Dockerfile.worker` (CPU + CUDA variants).
- `Caddyfile` with `tls internal`, HSTS, static/media file serving.
- Six-service `docker-compose.yml` (Caddy / web / worker / scheduler / Redis / Watchtower).
- `compose.gpu.yml` override for NVIDIA Container Toolkit.

## [0.4.0] - 2026-05-03

### Phase 4 — Heavy viewers + DRF API + e2e

- 6 DRF viewsets + ~50 non-DRF JSON endpoints.
- Annotation, densitometry, comparison heavy viewers in Tailwind chrome.
- Report builders (docx / xlsx / pptx).
- Playwright golden-path e2e.

## [0.3.0] - 2026-05-03

### Phase 3 — Frontend foundation

- Tailwind 4 + design tokens + 9 component templatetags.
- Lucide sprite + 8 custom SVG icons.
- Alpine stores (theme / toast / modal / palette) + HTMX config.
- Layout shell (sidebar / topbar / command palette).
- Theme switcher with `UserProfile.theme` persistence.
- Phoresis app icon.
- Refonte of login / profile / dashboard / image and analysis shell pages.

## [0.2.0] - 2026-05-03

### Phase 2 — Models & services extraction

- 14 models cleaned of `process_sample`, FKs to `accounts.User`, +`sample_metadata`.
- All scientific services preserved (band_detection, calibration, densitometry, SAM, file_handler, scn_parser, template_learning, studio).
- 9 Celery tasks.
- ML models bundled (Git LFS).
- Admin ported.
- `seed_ladder_templates` + `create_initial_users` commands.

## [0.1.0] - 2026-05-03

### Phase 1 — Bootstrap & shims

- Django 5.2 project with split settings.
- `phoresis_core` (logging, celery, error handling, navigation registry).
- `accounts` app with custom `User` + `UserProfile` + 3 seeded groups.
- `dashboard` stub + `phoresis_ui` skeleton.
- pytest, ruff, pre-commit, GitHub Actions baseline CI.
