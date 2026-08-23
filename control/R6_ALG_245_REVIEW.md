# ALGEBRA-245 canon replay

The pinned `algebra.tex` authority was reopened read-only at commit
`a04446e57ec1fbc252a871afcec7752fb2807b14` and rehashed as
`FA8BB92E58A4F78A2BD01B3B6A4A87DE0A0D279F5DD90641B574DD5FBFFFA4F3`.

At lines 13070–13074 and 13149–13153 the exact sequences are
`0 -> M' -> M -> M'' -> 0`; the immediately preceding rank equations use
`rank(M') + rank(M'')`; and the prose nevertheless prints `M' ⊕ M'`.
A split exact sequence has middle term `M' ⊕ M''`, so the second printed
`M'` is provably the wrong variable in both parallel occurrences. The
smallest derived-fork correction is `M' ⊕ M''` at lines 13073 and 13152.

No upstream authority or French producer bytes were changed. The pointer is
accepted only as a non-rendering canon erratum until a deliberate derived-fork
overlay boundary.
