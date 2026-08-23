# 72-chapter cumulative PDF visual QA

Inspected object: `build/stacks-zh-hans-cn-partial.pdf`, 15,538,935 bytes,
SHA-256 `A708A50A6BA332CA91D5F7F62496C6B38EB1281D2AB6801B8EF07F26AB9BA2B4`,
2,630 A4 pages.

Poppler 24.04.0 rendered every page at 100 dpi. The page manifest
`visual/RENDER_MANIFEST_A708A50A.csv` contains 2,630 ordered PNG hashes;
the ordered binding is `03CF48731EF9A1B142688270FBD6E9EE5DF78E8B36909EAC591AF7F32405C71C`.
Contact sheets 1–132 cover pages 1–2,630 without gaps and were all directly
inspected. Full-resolution checks covered representative opening and ending
pages 2,008, 2,025, 2,026, 2,089, 2,292, and 2,334. These bind the newly
admitted Chapter 86 (pages 2,008–2,025), Chapter 87 (2,026–2,089), and Chapter
99 (2,292–2,334).

Result: titles and body text are centered and page-filling, with readable
mainland Simplified-Chinese scientific typography. No clipping, overlap,
unintended blank or duplicate page, missing-glyph box, malformed diagram, or
scale/centering defect was observed. Sparse chapter endings are intentional.

Mechanical cross-check: 20,757 named destinations and 26,812 link annotations;
no malformed, zero-area, or out-of-page rectangles. All 51 fonts are embedded;
38 have ToUnicode. Text extraction produced 4,126,110 characters, including
1,402,569 CJK unified ideographs, with no replacement characters or extraction
errors.

Adverse evidence is retained. The PDF is untagged and 13 embedded legacy
math/Xy-pic subsets lack ToUnicode. The 102 extracted literal `??` pairs are
unchanged from the preceding cumulative head and are preserved source/editorial
placeholders, not new cumulative-reference failures. The build log retains 39
overfull hbox, 5 underfull hbox, and 36 underfull vbox warnings; every affected
page lies within the direct all-page review, and none produced clipping or
unreadable reflow. This remains a producer/canon checkpoint, not independent
Chinese-language certification.

Conclusion: visual QA passed for the 72-chapter cumulative build.
