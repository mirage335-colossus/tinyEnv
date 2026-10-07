# Video production

[`pipeline.py`](pipeline.py) checks inputs and connects the fresh editor and
documentation recordings and verified screenshot comparisons to narration, visual composition, encoding and final
delivery. The complete host prerequisites and commands are in
[`../README-reproduction.md`](../README-reproduction.md).

To use this optional automated production workflow, first supply the ignored local
voice model as described in the reproduction instructions. From the containing
repository, use the prepared video environment:

```sh
tutorial-video/.work/venv/bin/python \
  tutorial-video/production/pipeline.py all \
  --editor /path/to/foundation-editor-fltk \
  --rustc /path/to/rustc \
  --browser /path/to/chromium
```

The stages are `prepare`, `capture`, `render`, `verify` and `all`. `capture`
records native editor demonstrations plus the retained local HTML explorer and
its linked PDF collection. `capture --documentation-only` refreshes just those
two documentation clips. Browser capture needs an installed Chromium or Chrome
with its native PDF viewer. It uses a fresh profile and a private display, and
opens a copied reader bundle from `documentation-tool/published/`. The process
closes the browser and display and removes its temporary profile and reader copy
after capture. The documentation is a dated reference snapshot; its source date
and complete input hashes are recorded.

Before rendering capabilities, [`backend_comparison.py`](backend_comparison.py)
verifies the complete committed `docs/screenshots/` gallery with the repository's
existing verifier, then generates four comparison views: FLTK/Rev, SDL/framebuffer,
hosted browser/Browser Wasm, and FLTK/terminal TUI. Every source image is pasted
at its original pixel dimensions, preserving its complete contents and aspect
ratio, including the terminal status row and border. A fixed diagram explains
the shared application, GUI abstraction and host adapter. The browser comparison
identifies the shared visual renderer and different execution modes.

The resulting silent clip is 1824 by 804 pixels, 20 frames per second and
44 seconds long. Its four preview PNGs and receipt live in `.work/gallery/`.
Preparation records all ten gallery input hashes. The comparison receipt binds
those inputs, its generator, retained fonts, previews and fully decoded clip;
final verification rejects stale comparison identities. No application build
or screenshot refresh is required for this production stage.

`render.py` draws the editorial scenes using `file_visuals.py`, synthesizes
sentence-level narration with the locally supplied voice, times captions and
chapters, composites fresh recorded footage and encodes the final films. Story
content is in `../stories/tutorial.json` and `../stories/capabilities.json`. It
loads the retained fonts and ignored local voice model from `../assets/`; native
footage resolves against the video project's `.work/capture/` and `.work/gallery/`
directories. `render --previews-only` and `render --narration-only` are useful for
reviewing an authored story.

Generated projects, browser profiles, capture receipts, audio, PNGs and stage
logs stay in the video's own `.work/` or `output/` trees, apart from owned neutral
temporary capture directories. Application files and committed documentation
are inputs. The scripts do not refresh documentation or add application/CI hooks.

After full decoding and source/delivery checks, `verify` atomically publishes
`output/software-foundation-tutorial.mp4` and
`output/software-foundation-capabilities.mp4`. Their hashes agree with the
per-film masters; captions, chapters, scripts, timelines and preview images stay
alongside those masters. `output/verification.json` records the named copies.
