# ALGEBRA-250 independent canon review

The pinned `algebra.tex` authority hashes to
`FA8BB92E58A4F78A2BD01B3B6A4A87DE0A0D279F5DD90641B574DD5FBFFFA4F3`.
Lemma `lemma-finite-type-algebra-finite-nr-primes` lists eight items, but item
(8) is literally `add more here.` and is not a mathematical assertion. The
proof explicitly concludes only that items (1)–(7) are equivalent and contains
no argument for an eighth condition.

The smallest complete source repair is to terminate item (7) with a period and
delete placeholder item (8). Adding a genuine eighth condition would require
new mathematics and a corresponding proof, so it is not the bounded repair.

The phrase `add more here` also occurs at source line 4771, already represented
by ALGEBRA-071 / `MC-STK-ERR-0468`. That is a distinct lemma and exact locus;
it does not deduplicate this defect. Admit a new non-rendering pointer bound to
lines 14790–14805. Leave the frozen authority and all translation targets
unchanged pending the separately replayed English AI derived-fork overlay.
