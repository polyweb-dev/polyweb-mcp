# Third-party notices

Polyweb's Apache-2.0 license applies to its original application code.
Dependencies and other third-party materials retain their own licenses.
This notice records the dependency versions reviewed on 2026-11-13.

## Static web builds

The UI, landing site, and documentation builds generate `THIRD_PARTY_LICENSES.md`
with the license texts of their bundled JavaScript dependencies. Distribute that
file with the static output.

The UI and landing site also distribute these font licenses in `licenses/`:

- `jetbrains-mono-LICENSE.txt`: JetBrains Mono, supplied by
  `@fontsource-variable/jetbrains-mono` 5.3.0, under SIL OFL-1.1.
- `plus-jakarta-sans-LICENSE.txt`: Plus Jakarta Sans, supplied by
  `@fontsource-variable/plus-jakarta-sans` 5.3.0, under SIL OFL-1.1.

The build copies the full font license texts and copyright notices from the
installed packages. Keep these files with the font binaries.

The UI also includes Lucide icons. Its `licenses/lucide-react-LICENSE.txt` file
preserves the full ISC notice and the MIT notice for Feather-derived icons.
That document includes Cole Bemis's copyright notice.

The documentation site's search assets include Pagefind. The build copies its
separate license directory to `licenses/pagefind/` with the static output.
Preserve that directory with the generated search JavaScript and WebAssembly files.
Pagefind's highlight script also embeds mark.js 8.11.1. Its full MIT notice is in
`licenses/pagefind/mark.js-LICENSE.txt`, from the
[mark.js 8.11.1 package archive](https://registry.npmjs.org/mark.js/-/mark.js-8.11.1.tgz).

## Python dependencies

Keep dependency license files with any Python environment or container that you
distribute. These files normally reside in each dependency's `.dist-info/licenses`
directory or its package directory.

The backend uses `certifi` 2026.7.22 under MPL-2.0. The source for that version is
available in the [certifi 2026.7.22 source archive](https://files.pythonhosted.org/packages/a3/c2/24167ea9858356b47a87a50d39908bfdb72ceeefe0041586e704e5376b3a/certifi-2026.7.22.tar.gz).
Keep its MPL notice and source files with the dependency.

On Windows, `pywin32` 312 includes the separately licensed `adodbapi` component
under LGPL-2.1. Retain its notices and meet the applicable LGPL requirements if
you distribute that component. It is not part of the Linux Docker build.

## Build tools and base images

Some build dependencies use MPL or LGPL terms. For example, Sharp's libvips
binaries require a separate license review if you distribute those binaries.
The documentation build uses them to process images and does not include them
in the static website output.

Docker base images include operating-system packages with additional licenses.
Before you publish a prebuilt image, record its exact base-image digest.
Review the included packages and any source-code distribution requirements.
The application dependency audit does not clear an unspecified base image.

## Bundled skills

Bundled skills and their resources have separate terms. See
[LICENSING.md](LICENSING.md). Their license inventory remains separate from the
application dependency audit.
