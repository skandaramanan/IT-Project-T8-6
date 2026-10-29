# Third-party licences and notices

Reviewed: 29 October 2026.

This project uses third-party software, fonts, model tooling and external
services. Their respective owners retain their rights, and their original
licences and terms continue to apply. This document does not grant a licence to
or change ownership of the team's original project materials; those arrangements
are governed separately by the applicable project agreements and student deeds.

## Scope and sources

The package tables cover every third-party package entry in [uv.lock](uv.lock)
and [frontend/package-lock.json](frontend/package-lock.json), including indirect,
development and platform-specific optional dependencies. The project itself is
excluded. Versions are the locked versions, not minimum dependency constraints.
An optional package being listed does not mean it is installed on every computer
or shipped in the reviewer frontend.

Python licence identifiers were checked against the installed distributions'
metadata and licence files at the locked versions. Colorama's BSD-3-Clause
licence is recorded by its [upstream project](https://github.com/tartley/colorama).
The pyasn1-modules licence is recorded as BSD-2-Clause from the two conditions in
its installed `LICENSE.txt`, rather than its less specific metadata label `BSD`.
JavaScript identifiers come from the npm lockfile. Package links lead to the
relevant upstream release, which supplies its original notices and licence files.

These tables identify package-level licences; a package's bundled libraries and
notices also apply. Optional GPU/model environments and separately installed
executables are not fully pinned by these lockfiles and are described separately.
This register is an outline, not a replacement for the original licence texts,
copyright notices, source offers or attribution files required when distributing
third-party code, binaries, fonts or built assets.

## What to retain when distributing the project

- Keep each redistributed component's original copyright, permission and
  disclaimer text. Links in this register do not replace notices that must
  accompany a distribution.
- For Apache-2.0 components, include the licence and applicable upstream `NOTICE`
  material and identify modifications as required by the licence.
- For MPL-2.0 components, preserve notices and provide covered source as required
  when distributing executable forms. This concerns the covered component/files;
  it does not automatically put all project source under MPL.
- Keep the Source Sans 3 font licence with distributed font assets. Preserve the
  applicable copyright and any reserved-font-name requirements.
- Preserve wheel/native-binary notices as well as top-level package licences.
  In particular, NumPy and Pillow can contain separately licensed native code.
- A build/test tool's licence applies to that tool and any code actually included
  in an output. Running a tool does not by itself license the entire output under
  the tool's licence. Inspect the actual release contents when packaging.

Licence references: [MIT](https://spdx.org/licenses/MIT.html),
[MIT-0](https://spdx.org/licenses/MIT-0.html),
[MIT-CMU](https://spdx.org/licenses/MIT-CMU.html),
[Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0),
[BSD-2-Clause](https://spdx.org/licenses/BSD-2-Clause.html),
[BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html),
[ISC](https://spdx.org/licenses/ISC.html),
[MPL-2.0](https://www.mozilla.org/en-US/MPL/2.0/),
[OFL-1.1](https://openfontlicense.org/open-font-license-official-text/),
[PSF-2.0](https://spdx.org/licenses/PSF-2.0.html),
[BlueOak-1.0.0](https://spdx.org/licenses/BlueOak-1.0.0.html),
[0BSD](https://spdx.org/licenses/0BSD.html),
[Zlib](https://spdx.org/licenses/Zlib.html) and
[CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/).
`OR` indicates alternative licences; `AND` indicates combined obligations.
A single component's precise upstream terms take precedence over this summary.

## Python application dependencies

Declared directly in [pyproject.toml](pyproject.toml).

| Package / upstream release | Version | Licence |
| --- | --- | --- |
| [fastapi](https://pypi.org/project/fastapi/0.143.0/) | 0.143.0 | `MIT` |
| [google-genai](https://pypi.org/project/google-genai/2.22.0/) | 2.22.0 | `Apache-2.0` |
| [jsonschema](https://pypi.org/project/jsonschema/4.26.0/) | 4.26.0 | `MIT` |
| [numpy](https://pypi.org/project/numpy/2.5.2/) | 2.5.2 | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` |
| [openpyxl](https://pypi.org/project/openpyxl/3.1.5/) | 3.1.5 | `MIT` |
| [pillow](https://pypi.org/project/pillow/12.3.0/) | 12.3.0 | `MIT-CMU` |
| [pypdf](https://pypi.org/project/pypdf/6.18.0/) | 6.18.0 | `BSD-3-Clause` |
| [uvicorn](https://pypi.org/project/uvicorn/0.54.0/) | 0.54.0 | `BSD-3-Clause` |

## Python development dependencies

Declared in the `dev` dependency group; used for testing, HTTP test clients,
coverage and linting.

| Package / upstream release | Version | Licence |
| --- | --- | --- |
| [httpx](https://pypi.org/project/httpx/0.28.1/) | 0.28.1 | `BSD-3-Clause` |
| [pytest](https://pypi.org/project/pytest/9.1.1/) | 9.1.1 | `MIT` |
| [pytest-cov](https://pypi.org/project/pytest-cov/7.1.0/) | 7.1.0 | `MIT` |
| [ruff](https://pypi.org/project/ruff/0.16.2/) | 0.16.2 | `MIT` |

## Python indirect dependencies

Includes packages pulled in by both application and development dependencies;
platform markers determine which are installed on a particular machine.

| Package / upstream release | Version | Licence |
| --- | --- | --- |
| [annotated-doc](https://pypi.org/project/annotated-doc/0.0.5/) | 0.0.5 | `MIT` |
| [annotated-types](https://pypi.org/project/annotated-types/0.8.0/) | 0.8.0 | `MIT` |
| [anyio](https://pypi.org/project/anyio/4.15.1/) | 4.15.1 | `MIT` |
| [attrs](https://pypi.org/project/attrs/26.1.0/) | 26.1.0 | `MIT` |
| [certifi](https://pypi.org/project/certifi/2026.7.22/) | 2026.7.22 | `MPL-2.0` |
| [cffi](https://pypi.org/project/cffi/2.1.1/) | 2.1.1 | `MIT-0` |
| [charset-normalizer](https://pypi.org/project/charset-normalizer/3.5.1/) | 3.5.1 | `MIT` |
| [click](https://pypi.org/project/click/8.5.0/) | 8.5.0 | `BSD-3-Clause` |
| [colorama](https://pypi.org/project/colorama/0.4.6/) | 0.4.6 | `BSD-3-Clause` |
| [coverage](https://pypi.org/project/coverage/7.16.2/) | 7.16.2 | `Apache-2.0` |
| [cryptography](https://pypi.org/project/cryptography/50.0.1/) | 50.0.1 | `Apache-2.0 OR BSD-3-Clause` |
| [distro](https://pypi.org/project/distro/1.9.0/) | 1.9.0 | `Apache-2.0` |
| [et-xmlfile](https://pypi.org/project/et-xmlfile/2.0.0/) | 2.0.0 | `MIT` |
| [google-auth](https://pypi.org/project/google-auth/2.57.1/) | 2.57.1 | `Apache-2.0` |
| [h11](https://pypi.org/project/h11/0.16.0/) | 0.16.0 | `MIT` |
| [httpcore](https://pypi.org/project/httpcore/1.0.9/) | 1.0.9 | `BSD-3-Clause` |
| [idna](https://pypi.org/project/idna/3.19/) | 3.19 | `BSD-3-Clause` |
| [iniconfig](https://pypi.org/project/iniconfig/2.3.0/) | 2.3.0 | `MIT` |
| [jsonschema-specifications](https://pypi.org/project/jsonschema-specifications/2025.9.1/) | 2025.9.1 | `MIT` |
| [opentelemetry-api](https://pypi.org/project/opentelemetry-api/1.45.1/) | 1.45.1 | `Apache-2.0` |
| [packaging](https://pypi.org/project/packaging/26.3/) | 26.3 | `Apache-2.0 OR BSD-2-Clause` |
| [pluggy](https://pypi.org/project/pluggy/1.6.0/) | 1.6.0 | `MIT` |
| [pyasn1](https://pypi.org/project/pyasn1/0.6.4/) | 0.6.4 | `BSD-2-Clause` |
| [pyasn1-modules](https://pypi.org/project/pyasn1-modules/0.4.2/) | 0.4.2 | `BSD-2-Clause` |
| [pycparser](https://pypi.org/project/pycparser/3.0/) | 3.0 | `BSD-3-Clause` |
| [pydantic](https://pypi.org/project/pydantic/2.13.5/) | 2.13.5 | `MIT` |
| [pydantic-core](https://pypi.org/project/pydantic-core/2.46.5/) | 2.46.5 | `MIT` |
| [pygments](https://pypi.org/project/pygments/2.20.0/) | 2.20.0 | `BSD-2-Clause` |
| [referencing](https://pypi.org/project/referencing/0.37.0/) | 0.37.0 | `MIT` |
| [requests](https://pypi.org/project/requests/2.34.2/) | 2.34.2 | `Apache-2.0` |
| [rpds-py](https://pypi.org/project/rpds-py/2026.6.3/) | 2026.6.3 | `MIT` |
| [sniffio](https://pypi.org/project/sniffio/1.3.1/) | 1.3.1 | `MIT OR Apache-2.0` |
| [starlette](https://pypi.org/project/starlette/1.7.0/) | 1.7.0 | `BSD-3-Clause` |
| [tenacity](https://pypi.org/project/tenacity/9.1.4/) | 9.1.4 | `Apache-2.0` |
| [typing-extensions](https://pypi.org/project/typing-extensions/4.16.0/) | 4.16.0 | `PSF-2.0` |
| [typing-inspection](https://pypi.org/project/typing-inspection/0.4.4/) | 0.4.4 | `MIT` |
| [urllib3](https://pypi.org/project/urllib3/2.7.0/) | 2.7.0 | `MIT` |
| [websockets](https://pypi.org/project/websockets/16.1.1/) | 16.1.1 | `BSD-3-Clause` |

### Bundled Python/native notices

- **NumPy:** its package metadata declares
  `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` for its included code.
  The inspected macOS wheel's `numpy-*.dist-info/licenses/LICENSE.txt` additionally
  identifies OpenBLAS (BSD-3-Clause), LAPACK (BSD-3-Clause-Open-MPI), GCC runtime
  libraries (`GPL-3.0-or-later WITH GCC-exception-3.1`) and libquadmath
  (`LGPL-2.1-or-later`). It also supplies individual notices under that licences
  directory for its sorting, FFT, random-number and other included code.
  These native contents vary by wheel/platform: preserve the notices and meet
  source/relinking obligations applicable to the actual binaries redistributed.
  Do not infer that NumPy makes the whole project GPL-licensed.
  See [NumPy's licence](https://github.com/numpy/numpy/blob/main/LICENSE.txt),
  the [GCC runtime exception](https://www.gnu.org/licenses/gcc-exception-3.1.html)
  and [LGPL-2.1](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html).
- **Pillow:** uses MIT-CMU, not the standard MIT text. Its installed
  `pillow-*.dist-info/licenses/LICENSE` also contains notices for included image,
  compression, colour-management and text libraries, including AOM, Brotli,
  HarfBuzz, LCMS2, JPEG-related code, libpng, libwebp, OpenJPEG, Raqm and zlib.
  Preserve the complete licence bundle for the wheel you distribute rather than
  replacing it with one generic MIT licence.
  See [Pillow's licence bundle](https://github.com/python-pillow/Pillow/blob/main/LICENSE).
- **cryptography:** the package offers Apache-2.0 OR BSD-3-Clause. Its binary
  wheels can also contain OpenSSL and other third-party code; retain their
  notices and use the exact wheel's accompanying licensing information.
- **certifi:** its certificate bundle is MPL-2.0. Keep the covered files' notices
  and source availability information when redistributing it. See the
  [certifi source](https://github.com/certifi/python-certifi) and
  [Mozilla MPL guidance](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).

## Frontend application dependencies and font

Declared directly under `dependencies` in
[frontend/package.json](frontend/package.json). React's `scheduler` is listed
with indirect dependencies below.

| Package / upstream release | Version | Licence |
| --- | --- | --- |
| [@fontsource/source-sans-3](https://www.npmjs.com/package/@fontsource/source-sans-3/v/5.3.1) | 5.3.1 | `OFL-1.1` |
| [react](https://www.npmjs.com/package/react/v/19.3.0) | 19.3.0 | `MIT` |
| [react-dom](https://www.npmjs.com/package/react-dom/v/19.3.0) | 19.3.0 | `MIT` |

Source Sans 3 is served locally through `@fontsource/source-sans-3`; its font
files are included in built reviewer assets. Preserve the installed package's
`LICENSE` and the applicable font notices with those assets. The inspected
Fontsource package's notice begins `Google Inc.`; Adobe's upstream Source Sans
licence also identifies Adobe and the reserved font name `Source`. Preserve the
notices belonging to the actual supplied files rather than replacing them with
an invented copyright attribution.
See [Fontsource's package](https://www.npmjs.com/package/@fontsource/source-sans-3)
and [Adobe's Source Sans licence](https://github.com/adobe-fonts/source-sans/blob/release/LICENSE.md).

## Frontend direct development dependencies

Declared under `devDependencies`; these support TypeScript compilation, building,
component tests and browser tests.

| Package / upstream release | Version | Licence |
| --- | --- | --- |
| [@playwright/test](https://www.npmjs.com/package/@playwright/test/v/1.64.1) | 1.64.1 | `Apache-2.0` |
| [@testing-library/jest-dom](https://www.npmjs.com/package/@testing-library/jest-dom/v/7.0.1) | 7.0.1 | `MIT` |
| [@testing-library/react](https://www.npmjs.com/package/@testing-library/react/v/16.3.3) | 16.3.3 | `MIT` |
| [@testing-library/user-event](https://www.npmjs.com/package/@testing-library/user-event/v/14.6.8) | 14.6.8 | `MIT` |
| [@types/node](https://www.npmjs.com/package/@types/node/v/22.20.5) | 22.20.5 | `MIT` |
| [@types/react](https://www.npmjs.com/package/@types/react/v/19.3.0) | 19.3.0 | `MIT` |
| [@types/react-dom](https://www.npmjs.com/package/@types/react-dom/v/19.3.0) | 19.3.0 | `MIT` |
| [@vitejs/plugin-react](https://www.npmjs.com/package/@vitejs/plugin-react/v/6.1.2) | 6.1.2 | `MIT` |
| [jsdom](https://www.npmjs.com/package/jsdom/v/27.4.0) | 27.4.0 | `MIT` |
| [typescript](https://www.npmjs.com/package/typescript/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [vite](https://www.npmjs.com/package/vite/v/8.3.4) | 8.3.4 | `MIT` |
| [vitest](https://www.npmjs.com/package/vitest/v/4.1.11) | 4.1.11 | `MIT` |

## Frontend indirect and platform-specific dependencies

All remaining npm lockfile entries are listed below. Multiple versions of the
same package and operating-system-specific binaries are retained in this
inventory even when only one is installed locally.

| Package / upstream release | Version | Licence |
| --- | --- | --- |
| [@acemir/cssom](https://www.npmjs.com/package/@acemir/cssom/v/0.9.32) | 0.9.32 | `MIT` |
| [@adobe/css-tools](https://www.npmjs.com/package/@adobe/css-tools/v/4.5.0) | 4.5.0 | `MIT` |
| [@asamuzakjp/css-color](https://www.npmjs.com/package/@asamuzakjp/css-color/v/4.1.2) | 4.1.2 | `MIT` |
| [@asamuzakjp/dom-selector](https://www.npmjs.com/package/@asamuzakjp/dom-selector/v/6.8.1) | 6.8.1 | `MIT` |
| [@asamuzakjp/nwsapi](https://www.npmjs.com/package/@asamuzakjp/nwsapi/v/2.3.9) | 2.3.9 | `MIT` |
| [@babel/code-frame](https://www.npmjs.com/package/@babel/code-frame/v/7.29.7) | 7.29.7 | `MIT` |
| [@babel/helper-validator-identifier](https://www.npmjs.com/package/@babel/helper-validator-identifier/v/7.29.7) | 7.29.7 | `MIT` |
| [@babel/runtime](https://www.npmjs.com/package/@babel/runtime/v/7.29.10) | 7.29.10 | `MIT` |
| [@csstools/color-helpers](https://www.npmjs.com/package/@csstools/color-helpers/v/6.1.2) | 6.1.2 | `MIT-0` |
| [@csstools/css-calc](https://www.npmjs.com/package/@csstools/css-calc/v/3.4.3) | 3.4.3 | `MIT` |
| [@csstools/css-color-parser](https://www.npmjs.com/package/@csstools/css-color-parser/v/4.2.6) | 4.2.6 | `MIT` |
| [@csstools/css-parser-algorithms](https://www.npmjs.com/package/@csstools/css-parser-algorithms/v/4.0.2) | 4.0.2 | `MIT` |
| [@csstools/css-syntax-patches-for-csstree](https://www.npmjs.com/package/@csstools/css-syntax-patches-for-csstree/v/1.1.15) | 1.1.15 | `MIT-0` |
| [@csstools/css-tokenizer](https://www.npmjs.com/package/@csstools/css-tokenizer/v/4.0.2) | 4.0.2 | `MIT` |
| [@exodus/bytes](https://www.npmjs.com/package/@exodus/bytes/v/1.16.0) | 1.16.0 | `MIT` |
| [@jridgewell/sourcemap-codec](https://www.npmjs.com/package/@jridgewell/sourcemap-codec/v/1.6.0) | 1.6.0 | `MIT` |
| [@oxc-project/types](https://www.npmjs.com/package/@oxc-project/types/v/0.153.0) | 0.153.0 | `MIT` |
| [@rolldown/binding-android-arm-eabi](https://www.npmjs.com/package/@rolldown/binding-android-arm-eabi/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-android-arm64](https://www.npmjs.com/package/@rolldown/binding-android-arm64/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-darwin-arm64](https://www.npmjs.com/package/@rolldown/binding-darwin-arm64/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-darwin-x64](https://www.npmjs.com/package/@rolldown/binding-darwin-x64/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-freebsd-x64](https://www.npmjs.com/package/@rolldown/binding-freebsd-x64/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-linux-arm-gnueabihf](https://www.npmjs.com/package/@rolldown/binding-linux-arm-gnueabihf/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-linux-arm64-gnu](https://www.npmjs.com/package/@rolldown/binding-linux-arm64-gnu/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-linux-arm64-musl](https://www.npmjs.com/package/@rolldown/binding-linux-arm64-musl/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-linux-ppc64-gnu](https://www.npmjs.com/package/@rolldown/binding-linux-ppc64-gnu/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-linux-s390x-gnu](https://www.npmjs.com/package/@rolldown/binding-linux-s390x-gnu/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-linux-x64-gnu](https://www.npmjs.com/package/@rolldown/binding-linux-x64-gnu/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-linux-x64-musl](https://www.npmjs.com/package/@rolldown/binding-linux-x64-musl/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-openharmony-arm64](https://www.npmjs.com/package/@rolldown/binding-openharmony-arm64/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-win32-arm64-msvc](https://www.npmjs.com/package/@rolldown/binding-win32-arm64-msvc/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/binding-win32-x64-msvc](https://www.npmjs.com/package/@rolldown/binding-win32-x64-msvc/v/1.2.13) | 1.2.13 | `MIT` |
| [@rolldown/pluginutils](https://www.npmjs.com/package/@rolldown/pluginutils/v/1.0.1) | 1.0.1 | `MIT` |
| [@standard-schema/spec](https://www.npmjs.com/package/@standard-schema/spec/v/1.1.0) | 1.1.0 | `MIT` |
| [@testing-library/dom](https://www.npmjs.com/package/@testing-library/dom/v/10.4.2) | 10.4.2 | `MIT` |
| [@types/aria-query](https://www.npmjs.com/package/@types/aria-query/v/5.0.4) | 5.0.4 | `MIT` |
| [@types/chai](https://www.npmjs.com/package/@types/chai/v/5.2.3) | 5.2.3 | `MIT` |
| [@types/deep-eql](https://www.npmjs.com/package/@types/deep-eql/v/4.0.2) | 4.0.2 | `MIT` |
| [@types/estree](https://www.npmjs.com/package/@types/estree/v/1.0.9) | 1.0.9 | `MIT` |
| [@typescript/typescript-aix-ppc64](https://www.npmjs.com/package/@typescript/typescript-aix-ppc64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-darwin-arm64](https://www.npmjs.com/package/@typescript/typescript-darwin-arm64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-darwin-x64](https://www.npmjs.com/package/@typescript/typescript-darwin-x64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-freebsd-arm64](https://www.npmjs.com/package/@typescript/typescript-freebsd-arm64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-freebsd-x64](https://www.npmjs.com/package/@typescript/typescript-freebsd-x64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-linux-arm](https://www.npmjs.com/package/@typescript/typescript-linux-arm/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-linux-arm64](https://www.npmjs.com/package/@typescript/typescript-linux-arm64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-linux-loong64](https://www.npmjs.com/package/@typescript/typescript-linux-loong64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-linux-mips64el](https://www.npmjs.com/package/@typescript/typescript-linux-mips64el/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-linux-ppc64](https://www.npmjs.com/package/@typescript/typescript-linux-ppc64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-linux-riscv64](https://www.npmjs.com/package/@typescript/typescript-linux-riscv64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-linux-s390x](https://www.npmjs.com/package/@typescript/typescript-linux-s390x/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-linux-x64](https://www.npmjs.com/package/@typescript/typescript-linux-x64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-netbsd-arm64](https://www.npmjs.com/package/@typescript/typescript-netbsd-arm64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-netbsd-x64](https://www.npmjs.com/package/@typescript/typescript-netbsd-x64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-openbsd-arm64](https://www.npmjs.com/package/@typescript/typescript-openbsd-arm64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-openbsd-x64](https://www.npmjs.com/package/@typescript/typescript-openbsd-x64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-sunos-x64](https://www.npmjs.com/package/@typescript/typescript-sunos-x64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-win32-arm64](https://www.npmjs.com/package/@typescript/typescript-win32-arm64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@typescript/typescript-win32-x64](https://www.npmjs.com/package/@typescript/typescript-win32-x64/v/7.0.2) | 7.0.2 | `Apache-2.0` |
| [@vitest/expect](https://www.npmjs.com/package/@vitest/expect/v/4.1.11) | 4.1.11 | `MIT` |
| [@vitest/mocker](https://www.npmjs.com/package/@vitest/mocker/v/4.1.11) | 4.1.11 | `MIT` |
| [@vitest/pretty-format](https://www.npmjs.com/package/@vitest/pretty-format/v/4.1.11) | 4.1.11 | `MIT` |
| [@vitest/runner](https://www.npmjs.com/package/@vitest/runner/v/4.1.11) | 4.1.11 | `MIT` |
| [@vitest/snapshot](https://www.npmjs.com/package/@vitest/snapshot/v/4.1.11) | 4.1.11 | `MIT` |
| [@vitest/spy](https://www.npmjs.com/package/@vitest/spy/v/4.1.11) | 4.1.11 | `MIT` |
| [@vitest/utils](https://www.npmjs.com/package/@vitest/utils/v/4.1.11) | 4.1.11 | `MIT` |
| [agent-base](https://www.npmjs.com/package/agent-base/v/7.1.4) | 7.1.4 | `MIT` |
| [ansi-regex](https://www.npmjs.com/package/ansi-regex/v/5.0.1) | 5.0.1 | `MIT` |
| [ansi-styles](https://www.npmjs.com/package/ansi-styles/v/5.2.0) | 5.2.0 | `MIT` |
| [aria-query](https://www.npmjs.com/package/aria-query/v/5.3.0) | 5.3.0 | `Apache-2.0` |
| [assertion-error](https://www.npmjs.com/package/assertion-error/v/2.0.1) | 2.0.1 | `MIT` |
| [bidi-js](https://www.npmjs.com/package/bidi-js/v/1.1.0) | 1.1.0 | `MIT` |
| [chai](https://www.npmjs.com/package/chai/v/6.3.0) | 6.3.0 | `MIT` |
| [convert-source-map](https://www.npmjs.com/package/convert-source-map/v/2.0.0) | 2.0.0 | `MIT` |
| [css-tree](https://www.npmjs.com/package/css-tree/v/3.2.1) | 3.2.1 | `MIT` |
| [css.escape](https://www.npmjs.com/package/css.escape/v/1.5.1) | 1.5.1 | `MIT` |
| [cssstyle](https://www.npmjs.com/package/cssstyle/v/5.3.7) | 5.3.7 | `MIT` |
| [csstype](https://www.npmjs.com/package/csstype/v/3.2.3) | 3.2.3 | `MIT` |
| [data-urls](https://www.npmjs.com/package/data-urls/v/6.0.1) | 6.0.1 | `MIT` |
| [debug](https://www.npmjs.com/package/debug/v/4.4.3) | 4.4.3 | `MIT` |
| [decimal.js](https://www.npmjs.com/package/decimal.js/v/10.6.0) | 10.6.0 | `MIT` |
| [dequal](https://www.npmjs.com/package/dequal/v/2.0.3) | 2.0.3 | `MIT` |
| [detect-libc](https://www.npmjs.com/package/detect-libc/v/2.1.2) | 2.1.2 | `Apache-2.0` |
| [dom-accessibility-api](https://www.npmjs.com/package/dom-accessibility-api/v/0.5.16) | 0.5.16 | `MIT` |
| [dom-accessibility-api](https://www.npmjs.com/package/dom-accessibility-api/v/0.6.3) | 0.6.3 | `MIT` |
| [entities](https://www.npmjs.com/package/entities/v/8.1.0) | 8.1.0 | `BSD-2-Clause` |
| [es-module-lexer](https://www.npmjs.com/package/es-module-lexer/v/2.3.2) | 2.3.2 | `MIT` |
| [estree-walker](https://www.npmjs.com/package/estree-walker/v/3.0.3) | 3.0.3 | `MIT` |
| [expect-type](https://www.npmjs.com/package/expect-type/v/1.4.0) | 1.4.0 | `Apache-2.0` |
| [fdir](https://www.npmjs.com/package/fdir/v/6.5.0) | 6.5.0 | `MIT` |
| [fsevents](https://www.npmjs.com/package/fsevents/v/2.3.3) | 2.3.3 | `MIT` |
| [html-encoding-sniffer](https://www.npmjs.com/package/html-encoding-sniffer/v/6.0.0) | 6.0.0 | `MIT` |
| [http-proxy-agent](https://www.npmjs.com/package/http-proxy-agent/v/7.0.2) | 7.0.2 | `MIT` |
| [https-proxy-agent](https://www.npmjs.com/package/https-proxy-agent/v/7.0.6) | 7.0.6 | `MIT` |
| [indent-string](https://www.npmjs.com/package/indent-string/v/4.0.0) | 4.0.0 | `MIT` |
| [is-potential-custom-element-name](https://www.npmjs.com/package/is-potential-custom-element-name/v/1.0.1) | 1.0.1 | `MIT` |
| [js-tokens](https://www.npmjs.com/package/js-tokens/v/4.0.0) | 4.0.0 | `MIT` |
| [lightningcss](https://www.npmjs.com/package/lightningcss/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-android-arm64](https://www.npmjs.com/package/lightningcss-android-arm64/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-darwin-arm64](https://www.npmjs.com/package/lightningcss-darwin-arm64/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-darwin-x64](https://www.npmjs.com/package/lightningcss-darwin-x64/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-freebsd-x64](https://www.npmjs.com/package/lightningcss-freebsd-x64/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-linux-arm-gnueabihf](https://www.npmjs.com/package/lightningcss-linux-arm-gnueabihf/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-linux-arm64-gnu](https://www.npmjs.com/package/lightningcss-linux-arm64-gnu/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-linux-arm64-musl](https://www.npmjs.com/package/lightningcss-linux-arm64-musl/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-linux-x64-gnu](https://www.npmjs.com/package/lightningcss-linux-x64-gnu/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-linux-x64-musl](https://www.npmjs.com/package/lightningcss-linux-x64-musl/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-win32-arm64-msvc](https://www.npmjs.com/package/lightningcss-win32-arm64-msvc/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lightningcss-win32-x64-msvc](https://www.npmjs.com/package/lightningcss-win32-x64-msvc/v/1.33.0) | 1.33.0 | `MPL-2.0` |
| [lru-cache](https://www.npmjs.com/package/lru-cache/v/11.5.3) | 11.5.3 | `BlueOak-1.0.0` |
| [lz-string](https://www.npmjs.com/package/lz-string/v/1.5.0) | 1.5.0 | `MIT` |
| [magic-string](https://www.npmjs.com/package/magic-string/v/0.30.21) | 0.30.21 | `MIT` |
| [mdn-data](https://www.npmjs.com/package/mdn-data/v/2.27.1) | 2.27.1 | `CC0-1.0` |
| [min-indent](https://www.npmjs.com/package/min-indent/v/1.0.1) | 1.0.1 | `MIT` |
| [ms](https://www.npmjs.com/package/ms/v/2.1.3) | 2.1.3 | `MIT` |
| [nanoid](https://www.npmjs.com/package/nanoid/v/3.3.20) | 3.3.20 | `MIT` |
| [obug](https://www.npmjs.com/package/obug/v/2.2.1) | 2.2.1 | `MIT` |
| [parse5](https://www.npmjs.com/package/parse5/v/8.0.1) | 8.0.1 | `MIT` |
| [pathe](https://www.npmjs.com/package/pathe/v/2.0.3) | 2.0.3 | `MIT` |
| [picocolors](https://www.npmjs.com/package/picocolors/v/1.1.1) | 1.1.1 | `ISC` |
| [picomatch](https://www.npmjs.com/package/picomatch/v/4.0.7) | 4.0.7 | `MIT` |
| [playwright](https://www.npmjs.com/package/playwright/v/1.64.1) | 1.64.1 | `Apache-2.0` |
| [playwright-core](https://www.npmjs.com/package/playwright-core/v/1.64.1) | 1.64.1 | `Apache-2.0` |
| [postcss](https://www.npmjs.com/package/postcss/v/8.5.30) | 8.5.30 | `MIT` |
| [pretty-format](https://www.npmjs.com/package/pretty-format/v/27.5.1) | 27.5.1 | `MIT` |
| [punycode](https://www.npmjs.com/package/punycode/v/2.3.1) | 2.3.1 | `MIT` |
| [react-is](https://www.npmjs.com/package/react-is/v/17.0.2) | 17.0.2 | `MIT` |
| [redent](https://www.npmjs.com/package/redent/v/3.0.0) | 3.0.0 | `MIT` |
| [require-from-string](https://www.npmjs.com/package/require-from-string/v/2.0.2) | 2.0.2 | `MIT` |
| [rolldown](https://www.npmjs.com/package/rolldown/v/1.2.13) | 1.2.13 | `MIT` |
| [saxes](https://www.npmjs.com/package/saxes/v/6.0.0) | 6.0.0 | `ISC` |
| [scheduler](https://www.npmjs.com/package/scheduler/v/0.28.0) | 0.28.0 | `MIT` |
| [siginfo](https://www.npmjs.com/package/siginfo/v/2.0.0) | 2.0.0 | `ISC` |
| [source-map-js](https://www.npmjs.com/package/source-map-js/v/1.2.2) | 1.2.2 | `BSD-3-Clause` |
| [stackback](https://www.npmjs.com/package/stackback/v/0.0.2) | 0.0.2 | `MIT` |
| [std-env](https://www.npmjs.com/package/std-env/v/4.3.0) | 4.3.0 | `MIT` |
| [strip-indent](https://www.npmjs.com/package/strip-indent/v/3.0.0) | 3.0.0 | `MIT` |
| [symbol-tree](https://www.npmjs.com/package/symbol-tree/v/3.2.4) | 3.2.4 | `MIT` |
| [tinybench](https://www.npmjs.com/package/tinybench/v/2.9.0) | 2.9.0 | `MIT` |
| [tinyexec](https://www.npmjs.com/package/tinyexec/v/1.3.1) | 1.3.1 | `MIT` |
| [tinyglobby](https://www.npmjs.com/package/tinyglobby/v/0.2.17) | 0.2.17 | `MIT` |
| [tinyrainbow](https://www.npmjs.com/package/tinyrainbow/v/3.2.0) | 3.2.0 | `MIT` |
| [tldts](https://www.npmjs.com/package/tldts/v/7.4.18) | 7.4.18 | `MIT` |
| [tldts-core](https://www.npmjs.com/package/tldts-core/v/7.4.18) | 7.4.18 | `MIT` |
| [tough-cookie](https://www.npmjs.com/package/tough-cookie/v/6.0.2) | 6.0.2 | `BSD-3-Clause` |
| [tr46](https://www.npmjs.com/package/tr46/v/6.0.0) | 6.0.0 | `MIT` |
| [undici-types](https://www.npmjs.com/package/undici-types/v/6.21.0) | 6.21.0 | `MIT` |
| [w3c-xmlserializer](https://www.npmjs.com/package/w3c-xmlserializer/v/5.0.0) | 5.0.0 | `MIT` |
| [webidl-conversions](https://www.npmjs.com/package/webidl-conversions/v/8.0.1) | 8.0.1 | `BSD-2-Clause` |
| [whatwg-mimetype](https://www.npmjs.com/package/whatwg-mimetype/v/4.0.0) | 4.0.0 | `MIT` |
| [whatwg-mimetype](https://www.npmjs.com/package/whatwg-mimetype/v/5.0.0) | 5.0.0 | `MIT` |
| [whatwg-url](https://www.npmjs.com/package/whatwg-url/v/15.1.0) | 15.1.0 | `MIT` |
| [why-is-node-running](https://www.npmjs.com/package/why-is-node-running/v/2.3.0) | 2.3.0 | `MIT` |
| [ws](https://www.npmjs.com/package/ws/v/8.22.0) | 8.22.0 | `MIT` |
| [xml-name-validator](https://www.npmjs.com/package/xml-name-validator/v/5.0.0) | 5.0.0 | `Apache-2.0` |
| [xmlchars](https://www.npmjs.com/package/xmlchars/v/2.2.0) | 2.2.0 | `MIT` |

Lightning CSS and its platform bindings are MPL-2.0 build dependencies. Keep
covered-source availability and notices if redistributing those tools; the CSS
output is not automatically MPL solely because Lightning CSS processed it.
See [Lightning CSS](https://github.com/parcel-bundler/lightningcss) and the
[Mozilla MPL FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).

## Optional extraction models and local model software

The normal review tool does not need a language-model runtime. The following
components relate to extraction and the optional GPU/second-reading routes.
They are not installed by the project's standard locked Python dependencies.

| Component | Licence / terms | Relevance |
| --- | --- | --- |
| [Qwen2.5-VL-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) | Apache-2.0, as declared by the upstream model | Optional local extraction model named in `backend/survey/extraction/qwen.py`. |
| Qwen Q6_K / other converted weights | Upstream model licence plus the actual distributor's accompanying notices | The committed second-reading configuration records `qwen/qwen2.5-vl-7b`, `Q6_K`; it does not pin a distributor repository/revision. Record that provenance before supplying a model binary. A quantisation label alone is not a licence record. |
| [PyTorch / torch](https://github.com/pytorch/pytorch/blob/main/LICENSE) | BSD-3-Clause, with additional third-party notices | Optional GPU model execution. |
| [Transformers](https://github.com/huggingface/transformers/blob/main/LICENSE) | Apache-2.0 | Optional model/processor loading. |
| [Accelerate](https://github.com/huggingface/accelerate/blob/main/LICENSE) | Apache-2.0 | Optional model placement/loading. |
| [bitsandbytes](https://github.com/bitsandbytes-foundation/bitsandbytes/blob/main/LICENSE) | MIT for the main project; additional notices apply | Optional 4-bit GPU loading; retain its [third-party notices](https://github.com/bitsandbytes-foundation/bitsandbytes/blob/main/NOTICE.md). |
| [qwen-vl-utils](https://pypi.org/project/qwen-vl-utils/) | Apache-2.0 | Optional image/video input preparation in the GPU route. |
| [LM Studio](https://lmstudio.ai/app-terms) | Proprietary application terms | Optional external local model server used for the recorded Qwen run; separately installed. |
| [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE) | MIT, with its dependencies' notices | Alternative OpenAI-compatible local server mentioned in the extraction implementation. |

The optional GPU stack is installed separately by
[benchmark/colab_qwen_arm.ipynb](benchmark/colab_qwen_arm.ipynb). Its package
versions, CUDA libraries and indirect dependencies are not locked here. Retain
that environment's own complete licence inventory if distributing it. NVIDIA
CUDA/cuDNN components, if installed, have their own terms; they are not covered
by PyTorch's BSD licence. Model weights and server executables are not included
in this repository. Consult the actual downloaded model's licence before use or
redistribution; a service/server's software licence does not license its models.

## Runtimes, build tools and CI

These are installed separately or run in CI. Their versions are taken from the
actual installation unless a workflow/configuration pins them. This project does
not include their installers or a Python/Node runtime in its source tree.

| Component | Licence / terms | Use |
| --- | --- | --- |
| [Python / CPython](https://docs.python.org/3/license.html) | PSF licence agreement and included third-party notices | Python 3.12 runtime; the interpreter has its own licence bundle. |
| [Node.js](https://github.com/nodejs/node/blob/main/LICENSE) | MIT for Node.js, with bundled third-party licences | Frontend builds and JavaScript tests. |
| [npm CLI](https://github.com/npm/cli/blob/latest/LICENSE) | Artistic-2.0, with dependency notices | Frontend package installation and scripts. |
| [Git](https://git-scm.com/about/free-and-open-source) | GPL-2.0 | Version control and sharing review decisions; installed as a separate executable. |
| [uv](https://github.com/astral-sh/uv#license) | MIT OR Apache-2.0 for uv, with third-party notices | Python environment and dependency management. |
| [uv_build](https://pypi.org/project/uv-build/) | MIT OR Apache-2.0 for the uv project code, with third-party notices | Build backend constrained to `>=0.12,<0.13` in `pyproject.toml`; separately resolved for builds, absent from `uv.lock`. |
| [Gitleaks](https://github.com/gitleaks/gitleaks/blob/master/LICENSE) | MIT | CI secret scanner; workflow pins 8.30.1. |
| [actions/checkout](https://github.com/actions/checkout/blob/main/LICENSE) | MIT | CI source checkout (`@v4`). |
| [actions/setup-node](https://github.com/actions/setup-node/blob/main/LICENSE) | MIT | CI Node setup (`@v4`). |
| [actions/upload-artifact](https://github.com/actions/upload-artifact/blob/main/LICENSE) | MIT | CI frontend/report artifacts (`@v4`). |
| [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv/blob/main/LICENSE) | MIT | CI uv setup (`@v6`). |
| Chromium and Playwright browser downloads | Chromium BSD-style licence and included third-party notices | Downloaded separately by Playwright for end-to-end tests; preserve the browser distribution's own notices if supplying it. See [Chromium licensing](https://www.chromium.org/chromium-os/licensing/). |

## External services

Service terms are distinct from open-source library licences. Accounts, API keys,
subscriptions and access permissions are provisioned separately.

| Service | Applicable terms | Project use |
| --- | --- | --- |
| Gemini API / Google AI Studio | [Gemini API terms](https://ai.google.dev/gemini-api/terms) and incorporated Google API terms | Hosted extraction. The Apache-2.0 licence of `google-genai` covers the SDK, not Google's hosted models. |
| Google Drive API | [Google APIs terms](https://developers.google.com/terms), applicable Drive terms and file permissions | Optional scan download and source storage. |
| GitHub / GitHub Actions | [GitHub terms](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service) | Code/data hosting, Git sharing and CI. |
| Linear | [Linear terms](https://linear.app/terms) | Project requirements, issues and documentation. |
| Google Colab | [Colab terms](https://research.google.com/colaboratory/tos_v5.html) | Optional notebook execution environment. |

Google's treatment of inputs/outputs differs between paid and unpaid Gemini
services. Check the applicable account terms and permission to process archival
material before a new extraction; a software licence does not supply that
permission. This register does not assign ownership of generated output to a
model vendor or certify that every output is copyright-protected.

## Archival material, data and project documents

Survey scans, historical transcriptions, real scan fixtures, supplied data,
University logos and other client materials keep their existing rights and
access restrictions. Their presence in the repository or an open-source
software dependency does not grant permission to publish or redistribute them.
Synthetic demonstration records are identified by their own documentation.

The students' assignment deeds and the project Letter Agreement govern the
team's original deliverables separately. No signed deed, personal contact
details or signature is reproduced in this public-facing notice file.

## Keeping this register current

When either lockfile changes, update the affected package/version/licence rows.
Recheck installed package and binary notices when changing platform, building a
release or supplying an optional model environment. Keep applicable original
licence, copyright and NOTICE files alongside any redistributed components or
built assets; this register alone is not a complete redistribution notice bundle.
