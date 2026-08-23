# ALGEBRA-253–256 independent canon review

The pinned `algebra.tex` authority is 1,771,230 bytes / SHA-256
`FA8BB92E58A4F78A2BD01B3B6A4A87DE0A0D279F5DD90641B574DD5FBFFFA4F3`.

- ALGEBRA-253 is a certain typo: `annilator` must be `annihilator`.
- ALGEBRA-254 is a certain imperative-grammar error: `Let $R$ is` must be
  `Let $R$ be`.
- ALGEBRA-255 is a typed mathematical defect. The proof uses
  $\mathfrak p$ as a prime localization index and invokes the image of
  $\operatorname{Spec}(S^{-1}R)$ in $\operatorname{Spec}(R)$, so
  `$\mathfrak p \in R$` is impossible as written. The typed condition is a
  prime $\mathfrak p \in \operatorname{Spec}(R)$ disjoint from $S$.
  The exact same defect recurs independently at line 16291 in the `WeakAss`
  localization proof. That second locus is absent from the current producer
  ledger and receives a separate canon-native pointer so the eventual overlay
  cannot repair one occurrence and miss the other.
- ALGEBRA-256 is an exposed editorial maintenance instruction, not mathematical
  exposition. Its final materialized repair depends on whether the lemma is
  moved; if it stays, the note should be removed.

All four producer rows are novel within the bounded canon evidence. Admit four
separate non-rendering pointers plus one canon-native companion pointer for line
16291. Preserve the frozen authority and all translation targets; materialize
only in the separately replayed English AI derived-fork overlay, with
ALGEBRA-256 held for an explicit placement decision.
