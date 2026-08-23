# 69-chapter cumulative PDF visual QA

Inspected object: `build/stacks-zh-hans-cn-partial.pdf`, 14,794,606 bytes,
SHA-256 `DD46A430B07A3759B2EF4DFA2C174ACB0C76FD1583DB59A13E0B4FDC66610D47`,
2,502 A4 pages.

Poppler 24.04.0 rendered every page at 100 dpi. The page manifest
`visual/RENDER_MANIFEST_DD46A430.csv` contains 2,502 ordered PNG hashes;
the ordered binding is `A2759095C07CA6B73646A9A87B26DB11376F340055679FB79665BDCCB9175516`.
Contact sheets 1–126 cover pages 1–2,502 without gaps. The full-resolution
checks covered pages 2,441–2,445, 2,481–2,487, and 2,502, including the new
Chapters 113–114 and the final bibliography.

Result: titles and body text are centered and page-filling, with readable
mainland Simplified-Chinese scientific typography. No clipping, overlap,
blank/duplicate page, missing-glyph box, malformed diagram, or scale/centering
defect was observed. Sparse chapter endings are intentional whitespace.

Mechanical cross-check: 19,832 named destinations and 25,010 link annotations;
no malformed, zero-area, or out-of-page rectangles. All 51 fonts are embedded;
38 have ToUnicode. The PDF remains untagged and 13 legacy math/Xy-pic subsets
lack ToUnicode. This is a producer/canon checkpoint, not independent Chinese
language certification.

Conclusion: visual QA passed for the 69-chapter cumulative build.
