# Attribution and licensing review

## Research code in this repository

The maintainer approved **GPL-2.0-only** for the project's research source code on 19 October 2026. The full GNU GPL version 2 text is supplied in `LICENSE`; `docs/LICENSING.md` lists the exact files and distinguishes project code from external dependencies and non-code material.

The maintainer states that development, including Phase A, was performed with ChatGPT/OpenAI Codex assistance under their direction, with no intentional external-code copying and no known additional human contributors or university/employer ownership restrictions. This is a provenance statement, not a guarantee that generated text cannot resemble third-party material.

No explicit third-party copyright/SPDX notice was found in the copied research source. A limited comparison against 2,001 installed upstream C++ files found no exact whitespace-normalized blocks of six significant lines totaling at least 180 characters. Edited, renamed, shorter, or unexamined material may be missed. This is not a comprehensive legal audit.

Copied research files remain byte-identical to the source-manifest entries; licensing is declared here and in the scope document without inventing copyright owners or replacing upstream notices. No rights in upstream code are claimed by the maintainer.

## External software (not bundled)

- **ns-3**: https://www.nsnam.org/ — the inspected upstream root LICENSE describes predominantly GPLv2-only contributions with some differently licensed code. The research simulation uses ns-3 APIs. Review the applicable upstream notices and distribution requirements before publishing a combined distribution.
- **5G-LENA / NR**: https://5g-lena.cttc.es/ — the inspected NR LICENSE contains the GNU GPL version 2 text. NR source and binaries are not bundled here.
- **Matplotlib**: https://matplotlib.org/ — installed separately in the local analysis environment; no dependency package is redistributed here. Matplotlib and its dependencies retain their own licensing and notices.
- Python, CMake/Ninja, and the compiler are external tools, not repository content.

No upstream source file was copied wholesale into this repository. This does not prove that every research code fragment has independent provenance; preserve applicable third-party terms if reused material is subsequently identified. Existing notices in copied research files have not been removed.

## Original paper

Lal Verda Cakir, Mehmet Ali Erturk, Mehmet Ozdem, and Berk Canberk,
“Digital Twin-Assisted Handover Scheme for Mobile Networks Using Generative AI,”
IEEE Transactions on Network and Service Management 23 (2026), 4562–4571.
DOI: https://doi.org/10.1109/TNSM.2026.3690572

Metadata verified via the authors' institutional publication records, linked in README and `docs/references.bib`. The paper, its figures, and publisher material are not bundled. The sample figures in `figures/` come from this project's own recorded experiments.

## Upstream API references consulted

The installed NR examples/tests consulted during development include `contrib/nr/examples/cttc-nr-demo.cc` (Copyright 2019 CTTC; GPL-2.0-only) and `contrib/nr/test/nr-test-x2-handover-measures.cc` (Copyright 2013 CTTC; GPL-2.0-only; named authors Nicola Baldo and Manuel Requena). This credits reference material; it does not assert that entire files were copied. Applicable notices must accompany any actual upstream-derived portions. The original upstream files and their headers are not modified by this repository.
