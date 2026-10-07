# Optional local narration voice

`en_US-ljspeech-medium.onnx` is a local production dependency excluded from Git.
Its adjacent JSON configuration, model card, notices and expected checksum are
retained. To use the existing automated narration pipeline, obtain the model from
the source below and place it in this directory. A normal checkout does not
contain the model, and the pipeline does not download it automatically.

The dialogue and scene instructions in `../../stories/` are retained for future
retakes, including recordings without AI; using this particular voice is optional.

The upstream [Piper voice repository](https://huggingface.co/rhasspy/piper-voices)
identifies its repository license as MIT. This voice's
[model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD)
identifies the LJ Speech training dataset as public domain. The
[dataset publisher](https://keithito.com/LJ-Speech-Dataset/) confirms that status.
The original model card is retained here. Piper runtime dependencies are installed
separately under their own terms; their licenses are not the voice license.
`LICENSE-MIT.txt` retains the original
[Piper MIT notice](https://github.com/rhasspy/piper/blob/master/LICENSE.md)
associated with the publisher. The installed Piper 1.8 runtime has its own
package license; this notice does not override that package's terms.

Sources reviewed October 6, 2026. Upstream model file:
[en_US-ljspeech-medium.onnx](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/en_US-ljspeech-medium.onnx).
The SHA-256 of the model used for the original production is:
`6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22`.
The adjacent JSON SHA-256 is
`141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860`.
The production asset inventory, including the locally supplied model, is checked
by `production/pipeline.py prepare`.
