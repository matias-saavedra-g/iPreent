# Templates

Ready-made designs (hearts, frames, lists, notes, party cards, labels) that you fill in with your own text and
print. Same collection and same look in all three apps:

- **Android**: Create › **Templates**: category chips, a grid of thumbnails, tap one to fill in its text boxes
  over the exact preview, then Print. *Your own SVG* adds any SVG file to **Mine**.
- **Windows**: **Templates** mode: chips and a strip of thumbnails above the text boxes; the centre shows the
  exact preview. *Add SVG…* (or drop an `.svg` on the window) adds your own; *Folder* opens where they live.
- **Command line**: `ipreent template` lists them; `ipreent template big-heart "Te quiero"` prints one;
  `--set KEY=TEXT` fills a box by name, `--fields` shows a template's boxes, `--preview out.png` saves a picture.
  `\n` in a text is a new line. Any `.svg` path works as the name.
- **HTTP API** (Windows app): `GET /templates`; `POST /template` with
  `{"name": "birthday", "values": {"name": "Sofía"}}`.

What you type is remembered per template (Windows: registry; Android: SharedPreferences `templates`).
*Example text* puts the template's sample text back.

## How it works
A template is an ordinary SVG file. The art is drawn by **resvg** on PCs (`resvg_py`) and **AndroidSVG** on
Android; the text is drawn by iPreent itself, not by the SVG, so it can:
- **shrink to fit**: each box tries font sizes from its `ip:size` down to `ip:min` and uses the largest at which the
  wrapped text fits;
- **grow the design**: if the text still doesn't fit at the smallest size and the box crosses the template's
  `ip:stretch` row, that pixel row is repeated to make the design taller (lists, frames, notes); boxes below it
  move down;
- use the **bundled fonts** (Fredoka for "round", Pacifico for "script"; SIL Open Font License) and fall back to
  the system's emoji and symbol fonts.

Everything prints sharp (threshold, no dithering): line art and text stay crisp on thermal paper.

Code: `ipreent/templates.py` ↔ `android/.../Templates.kt` (layout, same test cases) and `TemplateArt.kt`
(drawing). The built-in SVGs are in `ipreent/templates/` and, identical, in `android/app/src/main/assets/templates/`
(`tests/test_templates.py` checks they match; copy both when you change one).

## Making your own
Draw at **384 units wide** (the 58 mm paper is 384 dots), any height, in black and white. Inkscape keeps the
extra attributes. Then add the iPreent namespace and mark the text boxes with invisible rectangles:

```xml
<svg xmlns="http://www.w3.org/2000/svg" xmlns:ip="urn:ipreent:template"
     viewBox="0 0 384 300" width="384" height="300"
     ip:name="Big heart" ip:category="love" ip:stretch="150">
  <path d="..." fill="none" stroke="#000" stroke-width="6"/>        <!-- the art -->
  <rect ip:field="message" ip:label="Message" ip:default="You make my heart smile"
        ip:font="script" ip:size="42" ip:min="16"
        x="92" y="104" width="200" height="120" fill="none"/>         <!-- a text box -->
</svg>
```

| On the root `<svg>` | |
|---|---|
| `ip:name` | Name in the gallery (default: from the file name). |
| `ip:category` | `love`, `frames`, `lists`, `notes`, `party` or `labels` (your own files always show under Mine). |
| `ip:stretch` | Optional: y of the row to repeat when a box crossing it needs more room. Pick a row where only straight vertical lines cross (sides of a frame), not a curve. |

| On a text box (any element with `x`, `y`, `width`, `height`, usually `<rect fill="none">`) | |
|---|---|
| `ip:field` | Key of the box (required, unique). |
| `ip:label` | What the editor calls it. |
| `ip:default` | Example text shown first (`&#10;` = new line). Make it realistic: people replace it bit by bit. |
| `ip:font` | `round` (default, Fredoka), `script` (Pacifico), `sans`, `bold` (system fonts). |
| `ip:size`, `ip:min` | Largest and smallest font size in SVG units (defaults 32 and 14). Equal values = fixed size (lists). |
| `ip:align` | `center` (default), `left`, `right`. |
| `ip:valign` | `middle` (default) or `top`. |
| `ip:list` | `check` (empty box), `dot` or `heart` before every line typed: one item per line. |
| `ip:lines` | Most lines (0 = any). `1` also gives a one-line text field in the editors. |
| `ip:color` | `white` for text on a black part of the art (the name tag's top band). |

Tips for thermal paper: strokes of 3 units or more; outlines instead of large black areas (big fills use more
heat, print slower and can curl the paper); no grey (it prints as solid black or nothing).

Put the file in the config folder's `templates` (Windows `%APPDATA%\ipreent\templates`, Linux
`~/.config/ipreent/templates`, macOS `~/Library/Application Support/ipreent/templates`), use *Add SVG…* in the
Windows app, or *Your own SVG* on Android. An SVG without text boxes prints as a picture.

## Why it looks like this (research, 2026-11-06)
- **Gallery of previews, one tap to an editable copy filled with realistic sample text, a small curated set
  grouped into categories, a blank option beside it.** The template-gallery pattern
  ([ui-patterns.com](https://ui-patterns.com/patterns/TemplateGallery)) recommends exactly this: preview every
  template, make starting instant with example content to replace piece by piece, start small and add categories,
  and warns that a large undifferentiated gallery turns the blank-page problem into a choice problem. So: 20
  templates in 6 categories, thumbnails rendered with their example text, and the other tools (Text, Checklist)
  stay as the blank option.
- **Filter chips for the categories**, single-select, short nouns, horizontally scrollable
  ([CMS design system: filter chip](https://design.cms.gov/components/filter-chip); Material 3 chips work the same way).
- **What to include**: what people print on pocket thermal printers: to-do lists, journal stickers, notes,
  labels for organising, gift tags and thank-you notes
  ([Phomemo](https://phomemo.com/blogs/inspiration/how-to-create-a-to-do-list-on-a-pocket-sticker-printer),
  [Phomemo ideas](https://eu.phomemo.com/en-tw/blogs/news/what-is-a-thermal-label-printer-and-25-creative-ideas)).
  Other label-printer apps (Niimbot, Phomemo, Stikkr) also pair templates with inline text editing
  ([Stikkr](https://apps.apple.com/app/id6770170821), [Phomymo manual](https://phomymo.pages.dev/docs/manual));
  their reviews complain that the print doesn't match the screen, so here the preview is the exact 1-bit print.
- **Sharp, not dithered**: threshold is the recommended conversion for text, logos and line art on thermal
  printers; dithering is for photos
  ([Label LIVE](https://label-live-web-v2.vercel.app/guides/optimizing-thermal-print-quality),
  [Neodynamic](https://www.neodynamic.com/Products/Help/ThermalLabel14.0/api/Neodynamic.SDK.Printing.DitherMethod.html)).
- **Renderers**: resvg via `resvg_py` 0.5.0 (MIT, wheels for Windows/macOS/Linux, Python 3.10+;
  [PyPI](https://pypi.org/project/resvg-py/)) instead of CairoSVG, which needs the Cairo DLL on Windows
  ([common install problem](https://community.viktor.ai/t/no-library-called-cairo-2/343)), or Qt SVG, which only
  covers static SVG 1.2 Tiny and isn't in the command line's dependencies
  ([Qt docs](https://doc.qt.io/qtforpython-6/overviews/svgrendering.html)). Android has no built-in SVG renderer for
  files at runtime, so **AndroidSVG 1.4** (Apache 2.0; [site](https://bigbadaboom.github.io/androidsvg/download.html)).
  Text isn't left to the SVG renderers, so it looks the same on both and can shrink, wrap and stretch.
- **Art**: all 20 designs were drawn for iPreent (MIT, like the code), so there are no third-party artwork licences.
