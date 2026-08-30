from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROGRAM_ROOT = ROOT.parent.parent
SRC = ROOT / "src"
MANIFEST_PATH = ROOT / "manifest.json"
SOURCE_RECEIPT = ROOT / "qa" / "source-replay.json"

LABEL_RE = re.compile(r"\\label\{([^{}]+)\}")
REF_RE = re.compile(r"\\ref\{([^{}]+)\}")
TITLE_RE = re.compile(r"^\s*\\title\{(.+)\}\s*$")
TEXT_RE = re.compile(r"\\text\{([^{}]*)\}")
STANDARD_LABEL_PREFIXES = (
    "definition",
    "lemma",
    "proposition",
    "theorem",
    "remark",
    "remarks",
    "example",
    "exercise",
    "situation",
    "equation",
    "section",
    "subsection",
    "subsubsection",
    "item",
)
MANUAL_REFERENCE_FALLBACKS = {
    # This frozen source label exists in more-morphisms.tex but has no entry in
    # the frozen permanent-tag registry.  Until Chapter 37 enters this reader,
    # retain the reference as a commit-pinned source link rather than emitting
    # an unexplained ``??`` or inventing a Stacks tag.
    "more-morphisms-lemma-weighting-specialization": {
        "url": (
            "https://github.com/stacks/stacks-project/blob/"
            "a04446e57ec1fbc252a871afcec7752fb2807b14/"
            "more-morphisms.tex"
        ),
        "text": "英文源码",
    },
    # coding.tex intentionally contains a verbatim cross-file reference as a
    # reader-facing example; it is not an actual target in the frozen tag
    # registry.  Account for the literal token without changing the verbatim
    # example or pretending that a Stacks tag exists.
    "foo-lemma-bar": {
        "url": (
            "https://github.com/stacks/stacks-project/blob/"
            "a04446e57ec1fbc252a871afcec7752fb2807b14/"
            "coding.tex"
        ),
        "text": "源码示例",
    },
}
STANDALONE_LINES = {
    r"\input{preamble}",
    r"\input{zh_preamble}",
    r"\begin{document}",
    r"\maketitle",
    r"\tableofcontents",
    r"\input{chapters}",
    r"\input{zh_chapters}",
    r"\bibliography{my}",
    r"\bibliographystyle{amsalpha}",
    r"\end{document}",
}
READER_EMENDATIONS = {
    # These two frozen locale sources place the text accent command \' inside
    # math mode.  XeLaTeX consequently drops the accented glyph.  The same
    # chapters already use the canonical \etale math macro elsewhere, so the
    # cumulative reader normalizes only these exact loci while the producer
    # targets remain byte-for-byte frozen.
    "topologies": [
        (r"$S_{affine, \'etale}$", r"$S_{affine, \etale}$", 1),
    ],
    "spaces-pushouts": [
        (
            r"$X_{spaces, \'etale} \to \lim X_{i, spaces, \etale}$",
            r"$X_{spaces, \etale} \to \lim X_{i, spaces, \etale}$",
            1,
        ),
    ],
    # The frozen source intentionally leaves the two lifts unnamed in the
    # prose but prints a literal ``??`` on the diagram arrow.  The sentence
    # immediately above identifies the two lifts.  Label only the generated
    # reader; the producer target and authority remain unchanged.
    "categories": [
        (
            r"A' \ar@{-->}[u]^{??} \ar[ru]_{h'} & & \ar@{}[u]^{above} &",
            r"A' \ar@{-->}[u]^{f'_1,\,f'_2} \ar[ru]_{h'} & & \ar@{}[u]^{\text{上图}} &",
            1,
        ),
    ],
    # Complete the Chinese reader text inside formula labels.  These changes
    # are source-keyed presentation emendations only; exact producer bytes are
    # still verified before composition.
    "fields": [
        (r"\{(\beta_1, \ldots, \beta_n)\text{ as below}\}", r"\{(\beta_1, \ldots, \beta_n)\text{ 如下}\}", 1),
        (r"\alpha \longmapsto \text{matrix of multiplication by }\alpha", r"\alpha \longmapsto \text{乘以 }\alpha\text{ 的线性变换矩阵}", 1),
        (r"\{\text{subgroups of }G\}", r"\{G\text{ 的子群}\}", 1),
        (r"\{\text{closed subgroups of }G\}", r"\{G\text{ 的闭子群}\}", 1),
        (r"\{\text{subextensions }L/M/K\}", r"\{\text{中间扩张 }L/M/K\}", 2),
        (
            "f(\\alpha)\\text{ is a root of the minimal polynomial}\\\\\n"
            "\\text{of }\\alpha\\text{ over }F\\text{ for all }\\alpha \\in S",
            "\\text{对所有 }\\alpha \\in S,\\ f(\\alpha)\\text{ 是}\\\\\n"
            "\\alpha\\text{ 在 }F\\text{ 上的极小多项式的根}",
            1,
        ),
        (r"S \subset E\text{ finite}", r"S \subset E\text{ 为有限集}", 1),
    ],
    # The frozen Chapter 75 producer target contains two literal U+0008
    # control characters where the authority has ``{\bf not}``.  They came
    # from interpreting ``\b`` as backspace while producing the Chinese
    # ``{\bf 不}`` emphasis.  Keep the producer bytes frozen, but repair the
    # two source-keyed reader occurrences so XeLaTeX receives valid TeX.
    "spaces-perfect": [
        ("{\x08f 不}", r"{\bf 不}", 2),
    ],
    "chow": [
        (r"\mathfrak m\text{-power torsion}", r"\mathfrak m\text{-幂挠子}", 1),
        (r"\mathfrak q\text{ lying over }\mathfrak p", r"\mathfrak q\text{ 位于 }\mathfrak p\text{ 之上}", 1),
        (r"x \in X \text{ closed}", r"x \in X \text{ 为闭点}", 1),
        (r"Z \subset X\text{ integral closed}", r"Z \subset X\text{ 为闭整子概形}", 1),
        (r"\text{class of }\text{div}_\mathcal{L}(s)", r"\text{div}_\mathcal{L}(s)\text{ 的类}", 1),
        (r"\mathfrak p \subset F[T]\text{ maximal}", r"\mathfrak p \subset F[T]\text{ 为极大理想}", 1),
        (r"i\text{ even}", r"i\text{ 为偶数}", 2),
        (r"i\text{ odd}", r"i\text{ 为奇数}", 2),
        (r"\text{flat pullback}", r"\text{平坦拉回}", 2),
        (r"\kappa\text{-vector space generated by symbols}", r"\text{由符号生成的 }\kappa\text{-向量空间}", 1),
        (r"\kappa\text{-linear combinations of admissible relations}", r"\text{可容许关系的 }\kappa\text{-线性组合}", 1),
        (r"\text{finite length }R\text{-modules}", r"\text{有限长度 }R\text{-模}", 2),
        (r"1\text{-dimensional }\kappa\text{-vector spaces}", r"1\text{-维 }\kappa\text{-向量空间}", 2),
        (r"\text{with isomorphisms}", r"\text{（以同构为态射）}", 4),
        (
            "\\text{restriction of } c_{p_i}(W_i \\to W, Q_i)\n"
            "\\text{ to } W_{i, \\infty}",
            r"c_{p_i}(W_i \to W, Q_i)\text{ 在 } W_{i, \infty}\text{ 上的限制}",
            1,
        ),
    ],
    # The long topology lists clip at the right margin in the cumulative
    # render.  Add legal math line-break opportunities only in the generated
    # reader; the producer target remains byte-for-byte frozen.
    "stacks-sheaves": [
        (
            r"\{Zariski, \etale, smooth, syntomic, fppf\}",
            r"\{Zariski,\linebreak[0] \etale,\linebreak[0] smooth,\linebreak[0] syntomic,\linebreak[0] fppf\}",
            5,
        ),
        (
            "\\{Zariski, \\etale, smooth,\nsyntomic, fppf\\}",
            "\\{Zariski,\\linebreak[0] \\etale,\\linebreak[0] smooth,\n"
            "\\linebreak[0] syntomic,\\linebreak[0] fppf\\}",
            1,
        ),
        (
            r"\{Zar, \etale, smooth, syntomic, fppf\}",
            r"\{Zar,\allowbreak \etale,\allowbreak smooth,\allowbreak syntomic,\allowbreak fppf\}",
            17,
        ),
    ],
    "bootstrap": [
        (r"\item the composition", r"\item 复合", 1),
    ],
    "descent": [
        (r"[First proof]", r"[第一种证明]", 1),
        (r"[Second proof]", r"[第二种证明]", 1),
        (
            r"\mathcal{F}\text{ finite locally free in \'etale topology}",
            r"\mathcal{F}\text{ 在平展拓扑中有限局部自由}",
            1,
        ),
    ],
    "derived": [
        (
            r"H^i(f)\text{ is an isomorphism for all }i \in \mathbf{Z}",
            r"\text{对所有 }i \in \mathbf{Z},\ H^i(f)\text{ 均为同构}",
            2,
        ),
        (
            r"\text{ is an isomorphism for all }n",
            r"\text{ 对所有 }n\text{ 均为同构}",
            2,
        ),
    ],
    "schemes": [
        (r"Locally ringed spaces", r"局部环化空间", 1),
        (r"Ringed spaces", r"环化空间", 1),
    ],
    "sheaves": [
        (r"a final object", r"终对象", 1),
    ],
    "constructions": [
        (r"_{graded rings}", r"_{\text{分次环}}", 1),
    ],
    "etale": [
        (
            r"\text{schemes }X\text{ \'etale over }S",
            r"X\text{ 是在 }S\text{ 上的平展概形}",
            1,
        ),
        (
            r"\text{schemes }X_0\text{ \'etale over }S_0",
            r"X_0\text{ 是在 }S_0\text{ 上的平展概形}",
            1,
        ),
        (
            r"\text{schemes }U\text{ \'etale over }S",
            r"U\text{ 是在 }S\text{ 上的平展概形}",
            1,
        ),
        (
            r"\text{ with }V\text{ \'etale over }X",
            r"\text{ 其中 }V\text{ 在 }X\text{ 上平展}",
            1,
        ),
        (
            r"\text{separated, \'etale over }S",
            r"\text{分离且在 }S\text{ 上平展}",
            1,
        ),
        (
            r"V\text{ quasi-compact, separated, \'etale over }X",
            r"V\text{ 拟紧、分离且在 }X\text{ 上平展}",
            1,
        ),
    ],
    "examples": [
        (
            r"\text{support proper over } A",
            r"\text{支撑在 }A\text{ 上为固有}",
            1,
        ),
    ],
    "stacks-cohomology": [
        (
            r"\text{ injective for all }i, j",
            r"\text{ 对所有 }i,j\text{ 均为单射}",
            1,
        ),
        (
            r"\text{ injective for all }i",
            r"\text{ 对所有 }i\text{ 均为单射}",
            1,
        ),
    ],
}

# Exact English prose inside TeX ``\text{...}`` is a locale defect, not a
# mathematical operator.  Translate a deliberately bounded vocabulary while
# leaving stable operators and category abbreviations (Spec, Hom, Aut, Gal,
# PSh, and so on) unchanged.  Leading/trailing spaces are preserved by the
# replacement routine so formula spacing remains stable.
READER_TEXT_TRANSLATIONS = {
    "and": "且",
    "and a morphism": "以及一个态射",
    "and correspondingly": "并相应地",
    "or": "或",
    "if": "若",
    "for": "对",
    "for all": "对所有",
    "for some": "对某个",
    "in": "于",
    "with": "其中",
    "such that": "使得",
    "has": "具有",
    "each": "每个",
    "where": "其中",
    "resp.": "分别",
    "(resp.": "（分别",
    "respectively": "分别",
    "as above": "如上",
    "as in": "如",
    "as an": "作为一个",
    "at": "在",
    "relative to": "相对于",
    "by definition": "由定义",
    "by formula above": "由上式",
    "by induction hypothesis": "由归纳假设",
    "by base case": "由基础情形",
    "by the lemma": "由该引理",
    "surjective": "满射",
    "injective": "单射",
    "closed": "闭",
    "finite": "有限",
    "finite separable": "有限可分",
    "finite locally free in \'etale topology": "在 \'etale 拓扑中有限局部自由",
    "even": "为偶数",
    "odd": "为奇数",
    "open": "开",
    "quasi-compact open": "拟紧开",
    "locally constant": "局部常值",
    "maximal": "为极大理想",
    "integral closed": "闭整",
    "is an isomorphism": "为同构",
    "is surjective": "为满射",
    "is continuous": "连续",
    "is flat": "平坦",
    "is open": "开",
    "is regular": "正则",
    "is representable": "可表",
    "is contained in": "包含于",
    "is abelian": "为 Abel 范畴",
    "is Cohen-Macaulay": "为 Cohen--Macaulay",
    "is sheaf theoretically empty": "在层论意义下为空",
    "is unramified at": "在下列点非分歧：",
    "is zero on": "在下列对象上为零：",
    "is an object of": "是下列范畴的对象：",
    "is isomorphic to an object of": "同构于下列范畴中的对象：",
    "isomorphic to an object of": "同构于下列范畴中的对象：",
    "is a right inverse to": "是下列映射的右逆：",
    "is compatible with": "与下列映射相容：",
    "comes from": "来自",
    "composes to": "复合为",
    "compositions": "复合",
    "consisting": "由下列对象组成：",
    "collections": "族",
    "continuous": "连续",
    "exact": "正合",
    "equivalently": "等价地",
    "factors": "可分解",
    "factors)": "可分解）",
    "free": "自由",
    "fully faithful": "全忠实",
    "generated by": "由下列对象生成：",
    "generator": "生成元",
    "gives": "给出",
    "homogeneous": "齐次",
    "height": "高度",
    "induced by": "由下列对象诱导：",
    "inducing the": "诱导出",
    "infinite set": "无限集",
    "preserves kernels": "保持核",
    "canonical map": "典范映射",
    "cartesian over": "在下列对象上 Cartesian：",
    "cartesian square": "Cartesian 方块",
    "cartesian, then we have": "为 Cartesian，此时有",
    "category of descent data": "下降数据范畴",
    "category of groupoid schemes": "群胚概形范畴",
    "descent data": "下降数据",
    "descent data relative to": "相对下降数据",
    "fibred in sets over": "在下列对象之上以集合为纤维：",
    "fibred in setoids over": "在下列对象之上以集合胚为纤维：",
    "the category of categories": "范畴的范畴",
    "the 2-category of categories": "范畴的 2-范畴",
    "the category of presheaves": "预层范畴",
    "all diagonals": "所有对角线",
    "finite locally free in fppf topology": "在 fppf 拓扑中有限局部自由",
    "finite locally free in \'etale topology": "在 \'etale 拓扑中有限局部自由",
    "finite locally free in Zariski topology": "在 Zariski 拓扑中有限局部自由",
    "finite locally free on": "在下列对象上有限局部自由：",
    "flat pullback": "平坦拉回",
    "standard covering": "标准覆盖",
    "open covering": "开覆盖",
    "scheme theoretic intersection": "概形论交",
    "induced topology": "诱导拓扑",
    "quotient topology": "商拓扑",
    "relative cup product": "相对杯积",
    "relative to the family": "相对于该族",
    "lower order terms": "低阶项",
    "interior of": "下列对象的内部：",
    "interior in": "在下列对象中的内部：",
    "lengths of chains of irreducible closed subsets": "不可约闭子集链的长度",
    "boundary of": "下列对象的边界：",
    "tangent to": "相切于",
    "class of": "下列对象的类：",
    "coeff of": "下列对象的系数：",
    "composition in": "下列范畴中的复合：",
    "connected components": "连通分支",
    "constructible subsets of": "下列对象的可构造子集：",
    "counit": "余单位",
    "else": "否则",
    "equals": "等于",
    "unit": "单位",
    "units of adjunction": "伴随单位",
    "flat pullback": "平坦拉回",
    "forget": "遗忘",
    "forget ": "遗忘 ",
    "from derived to usual": "从导出函子到通常函子",
    "image": "像",
    "Koszul complex on": "关于下列元素的 Koszul 复形：",
    "Lemma": "引理",
    "lying over": "位于下列对象之上：",
    "scalar": "标量",
    "section of": "下列对象的截面：",
    "sections of": "下列对象的截面：",
    "restriction of": "下列对象的限制：",
    "restriction for": "下列对象的限制：",
    "sheaf associated to": "下列对象的伴随层：",
    "sign": "符号",
    "strict equivalence classes of": "下列对象的严格等价类：",
    "strict equivalence classes of triples": "三元组的严格等价类：",
    "the element": "元素",
    "the graded object of": "下列对象的分次对象：",
    "the induced map": "诱导映射",
    "the local ring": "局部环",
    "the map": "映射",
    "the support of": "下列对象的支集：",
    "there exists": "存在",
    "there exist": "存在",
    "there exists a representative": "存在一个代表元",
    "up to homotopy": "在同伦意义下",
    "a homotopy between": "下列二者之间的同伦：",
    "via": "经由",
    "versus": "与",
    "we have": "有",
    "which has": "其具有",
    "whose": "其",
    "of": "属于",
    "over": "相对于",
    "on": "定义于",
    "of a stack": "叠",
    "of sets over": "集合范畴，位于",
    "of stacks over": "叠范畴，位于",
    "of the fibre has dimension": "的纤维维数为",
    "open and normal": "开且正规",
    "pairs": "对",
    "schemes": "概形",
    "schemes quasi-compact,": "拟紧概形，",
    "sheaves": "层",
    "stacks over": "下列对象上的叠：",
    "triangle": "特异三角",
    "with points": "带标记点",
    "for presheaves and": "对预层以及",
    "finite unions loc. closed subsets of": "局部闭子集的有限并，位于",
    "-anti-invariant elements of": "-反不变元，属于",
    "such that there exists a": "使得存在一个",
    "such that there exists a distinguished": "使得存在一个特异",
    "such that there exists a distinguished triangle": "使得存在一个特异三角",
    "quasi-compact, separated, \'etale over": "拟紧、分离且在下列对象上 \'etale：",
    "separated, \'etale over": "分离且在下列对象上 \'etale：",
    "\'etale over": "在下列对象上 \'etale：",
    "-category of": "-范畴，其对象为",
    "-category of pairs": "-二元组范畴",
    "-dimensional": "-维",
    "-dimensional algebras": "-维代数",
    "-graded primes of": "-分次素理想，位于",
    "-isomorphism": "-同构",
    "-module": "-模",
    "-modules": "-模",
    "-perfect": "-完美",
    "-power torsion": "-幂挠子",
    "-submodule of": "-子模，属于",
    "-vector spaces": "-向量空间",
    "th cohomology of": "次上同调，属于",
    "th component": "次分量",
    "th graded piece is": "次分次部分为",
    "th spot": "次位置",
    "ses": "短正合列",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def file_identity(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def verify_bound_file(binding: dict[str, object]) -> Path:
    path = PROGRAM_ROOT / str(binding["path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    identity = file_identity(path)
    if identity["bytes"] != int(binding["bytes"]):
        raise RuntimeError(
            f"byte-count drift for {path}: {identity['bytes']} != {binding['bytes']}"
        )
    if identity["sha256"] != str(binding["sha256"]).upper():
        raise RuntimeError(
            f"SHA-256 drift for {path}: {identity['sha256']} != {binding['sha256']}"
        )
    return path


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def write_text(path: Path, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


def should_prefix_reference(target: str, local_labels: set[str]) -> bool:
    if target in local_labels:
        return True
    return any(target.startswith(prefix + "-") for prefix in STANDARD_LABEL_PREFIXES)


def translate_reader_text(output: str) -> tuple[str, list[dict[str, object]]]:
    counts: Counter[str] = Counter()

    def replace(match: re.Match[str]) -> str:
        content = match.group(1)
        key = content.strip()
        translated = READER_TEXT_TRANSLATIONS.get(key)
        if translated is None:
            return match.group(0)
        leading = content[: len(content) - len(content.lstrip())]
        trailing = content[len(content.rstrip()) :]
        counts[key] += 1
        return rf"\text{{{leading}{translated}{trailing}}}"

    translated_output = TEXT_RE.sub(replace, output)
    report = [
        {
            "old_text": key,
            "new_text": READER_TEXT_TRANSLATIONS[key],
            "count": count,
        }
        for key, count in sorted(counts.items())
    ]
    return translated_output, report


def transform_standalone(
    source_text: str,
    *,
    stem: str,
    chapter: int | None,
    expected_title: str,
) -> tuple[str, dict[str, object]]:
    source_labels = LABEL_RE.findall(source_text)
    source_refs = REF_RE.findall(source_text)
    local_labels = set(source_labels)
    output_lines: list[str] = [
        f"% Generated mechanically from the frozen {stem}.tex target.",
        "% Do not edit this generated file; edit the bound locale source instead.",
    ]
    title_seen = False

    for line in source_text.splitlines():
        stripped = line.strip()
        if stripped in STANDALONE_LINES:
            continue
        title_match = TITLE_RE.match(line)
        # A few frozen chapters contain literal LaTeX examples such as
        # ``\\title{Title}`` after their real chapter title.  Only the first
        # title command is the chapter heading; later title commands are code
        # content and must remain byte-faithful in the generated reader.
        if title_match and not title_seen:
            title = title_match.group(1)
            if title != expected_title:
                raise RuntimeError(
                    f"title drift in {stem}: {title!r} != {expected_title!r}"
                )
            if chapter is not None:
                output_lines.append(f"\\setcounter{{chapter}}{{{chapter - 1}}}")
            output_lines.append(f"\\chapter{{{title}}}")
            title_seen = True
            continue
        if title_match and title_seen:
            output_lines.append(line)
            continue
        output_lines.append(line)

    if not title_seen:
        raise RuntimeError(f"no title found in {stem}")

    output = "\n".join(output_lines).rstrip() + "\n"
    reader_emendations: list[dict[str, object]] = []
    for old, new, expected_count in READER_EMENDATIONS.get(stem, []):
        count = output.count(old)
        if count != expected_count:
            raise RuntimeError(
                f"reader emendation locus drift in {stem}: {old!r} found "
                f"{count} times, expected {expected_count}"
            )
        output = output.replace(old, new)
        reader_emendations.append({"old": old, "new": new, "count": count})
    output, text_translations = translate_reader_text(output)
    output = LABEL_RE.sub(
        lambda match: rf"\label{{{stem}-{match.group(1)}}}", output
    )

    local_ref_rewrites = 0

    def rewrite_reference(match: re.Match[str]) -> str:
        nonlocal local_ref_rewrites
        target = match.group(1)
        if should_prefix_reference(target, local_labels):
            local_ref_rewrites += 1
            return rf"\ref{{{stem}-{target}}}"
        return match.group(0)

    output = REF_RE.sub(rewrite_reference, output)
    output_labels = LABEL_RE.findall(output)
    output_refs = REF_RE.findall(output)

    if len(output_labels) != len(source_labels):
        raise RuntimeError(f"label-count drift in generated {stem}")
    if len(output_refs) != len(source_refs):
        raise RuntimeError(f"reference-count drift in generated {stem}")
    if any(not label.startswith(stem + "-") for label in output_labels):
        raise RuntimeError(f"unprefixed generated label in {stem}")
    active_output_lines = {line.strip() for line in output.splitlines() if not line.lstrip().startswith("%")}
    for forbidden in STANDALONE_LINES:
        if forbidden in active_output_lines:
            raise RuntimeError(f"standalone control survived in {stem}: {forbidden}")

    report = {
        "stem": stem,
        "chapter": chapter,
        "title": expected_title,
        "source_labels": len(source_labels),
        "generated_labels": len(output_labels),
        "source_references": len(source_refs),
        "generated_references": len(output_refs),
        "local_reference_rewrites": local_ref_rewrites,
        "reader_emendations": reader_emendations,
        "reader_text_translations": text_translations,
    }
    return output, report


def make_preamble(
    macro_witness: str,
    delta_witness: str,
    graphicx_witness: str,
) -> str:
    marker = "% Theorem environments."
    marker_index = macro_witness.find(marker)
    if marker_index < 0:
        raise RuntimeError("the zh macro witness lacks the theorem-environment marker")
    macro_tail = macro_witness[marker_index:].lstrip()
    delta_lines = (
        r"\newfontfamily\stackszhgreek{Noto Serif CJK SC}",
        r"\DeclareRobustCommand{\zhdelta}{{\stackszhgreek δ}}",
    )
    for line in delta_lines:
        if line not in delta_witness:
            raise RuntimeError(f"the zh delta witness lacks required line: {line}")
    if r"\usepackage{graphicx}" not in graphicx_witness:
        raise RuntimeError("the Chapter 18 preamble witness lacks graphicx")
    header = r"""\documentclass[11pt,a4paper,oneside,openany]{stacks-project-book}

% Non-rendering source-note environments retained from the Stacks sources.
\usepackage{verbatim}
\newenvironment{reference}{\comment}{\endcomment}
\newenvironment{slogan}{\comment}{\endcomment}
\newenvironment{history}{\comment}{\endcomment}

% Diagrams and chapter-support packages.
\usepackage[all]{xy}
\xyoption{2cell}
\UseAllTwocells
\usepackage{multicol}
\usepackage{graphicx}

% Mainland Simplified-Chinese scientific typography.
\usepackage{fontspec}
\usepackage{xeCJK}
\defaultfontfeatures{Ligatures=TeX}
\setmainfont{Latin Modern Roman}
\setsansfont{Latin Modern Sans}
\setmonofont{Latin Modern Mono}
\setCJKmainfont[AutoFakeSlant=0.2]{Noto Serif CJK SC}
\setCJKsansfont{Noto Sans CJK SC}
\setCJKmonofont{Noto Sans CJK SC}
\newfontfamily\stackszhgreek{Noto Serif CJK SC}
\DeclareRobustCommand{\zhdelta}{{\stackszhgreek δ}}
\xeCJKsetup{PunctStyle=kaiming}
\XeTeXlinebreaklocale "zh"
\usepackage[a4paper,left=22mm,right=22mm,top=24mm,bottom=26mm,headheight=14pt,headsep=7mm,footskip=14mm]{geometry}
\linespread{1.18}
\setlength{\parindent}{2em}
\setlength{\parskip}{0pt}
\setlength{\emergencystretch}{1em}

% Localized structural names.
\renewcommand{\contentsname}{目录}
\renewcommand{\bibname}{参考文献}
\renewcommand{\proofname}{证明}
\renewcommand{\figurename}{图}
\renewcommand{\tablename}{表}
\renewcommand{\appendixname}{附录}

% Chinese numbered chapter heads while keeping numerical identifiers stable.
\makeatletter
\def\@makechapterhead#1{\global\topskip 7.5pc\relax
  \begingroup
  \fontsize{17}{22}\bfseries\centering
    \ifnum\c@secnumdepth>\m@ne
      \leavevmode \hskip-\leftskip
      \rlap{\vbox to\z@{\vss
          \ifx\chaptername\appendixname
            \centerline{\normalsize\mdseries 附录\enspace\thechapter}
          \else
            \centerline{\normalsize\mdseries 第\thechapter 章}
          \fi
          \vskip 3pc}}\hskip\leftskip\fi
     #1\par \endgroup
  \skip@34\p@ \advance\skip@-\normalbaselineskip
  \vskip\skip@ }
\makeatother

% Hyperlinks: current-volume labels resolve locally; absent chapters use tags.
\usepackage{hyperref}
\hypersetup{
  unicode=true,
  hidelinks,
  pdfborder={0 0 0},
  pdftitle={Stacks Project 简体中文版 - 阶段性累积版},
  pdfauthor={The Stacks Project contributors; zh-Hans-CN translation production},
  pdfsubject={Mainland Simplified Chinese cumulative edition of selected Stacks Project chapters}
}
\urlstyle{same}
\input{tagrefs}

"""
    return header + macro_tail.rstrip() + "\n"


def parse_tags(tags_text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in tags_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tag, label = stripped.split(",", 1)
        result[label] = tag
    return result


def make_tagrefs(
    reference_targets: set[str],
    tag_map: dict[str, str],
) -> tuple[str, list[str], list[str]]:
    mapped = sorted(target for target in reference_targets if target in tag_map)
    manual = sorted(
        target for target in reference_targets if target in MANUAL_REFERENCE_FALLBACKS
    )
    missing = sorted(
        target
        for target in reference_targets
        if target not in tag_map and target not in MANUAL_REFERENCE_FALLBACKS
    )
    lines = [
        "% Generated from the frozen Stacks permanent-tag registry.",
        "% Existing labels resolve inside this PDF; only absent labels fall back to tags.",
    ]
    for target in mapped:
        lines.append(
            rf"\expandafter\def\csname stacksTag@{target}\endcsname{{{tag_map[target]}}}"
        )
    for target in manual:
        fallback = MANUAL_REFERENCE_FALLBACKS[target]
        macro_url = str(fallback["url"]).replace("#", "##")
        lines.append(
            rf"\expandafter\def\csname stacksManual@{target}\endcsname"
            rf"{{\href{{{macro_url}}}{{\texttt{{{fallback['text']}}}}}}}"
        )
    lines.extend(
        [
            r"\DeclareRobustCommand{\StacksResolvedRef}[1]{%",
            r"  \ifcsname r@#1\endcsname",
            r"    \StacksOriginalRef{#1}%",
            r"  \else",
            r"    \ifcsname stacksTag@#1\endcsname",
            r"      \href{https://stacks.math.columbia.edu/tag/\csname stacksTag@#1\endcsname}{\texttt{\csname stacksTag@#1\endcsname}}%",
            r"    \else",
            r"      \ifcsname stacksManual@#1\endcsname",
            r"        \csname stacksManual@#1\endcsname%",
            r"      \else",
            r"        \StacksOriginalRef{#1}%",
            r"      \fi",
            r"    \fi",
            r"  \fi",
            r"}",
            r"\AtBeginDocument{%",
            r"  \let\StacksOriginalRef\ref",
            r"  \let\ref\StacksResolvedRef",
            r"}",
            "",
        ]
    )
    return "\n".join(lines), missing, manual


def make_reader(manifest: dict[str, object]) -> str:
    chapters = list(manifest["chapters"])
    chapter_count = len(chapters)
    generated_material = manifest.get("generated_material", {})
    index_input = ""
    if generated_material:
        if set(generated_material) != {"index"}:
            raise RuntimeError(
                "unsupported generated material: "
                + ", ".join(sorted(generated_material))
            )
        index_input = "\\input{index}\n"
    coverage_items = "\n".join(
        rf"\item 第 {chapter['chapter']} 章：{chapter['title']}"
        for chapter in chapters
    )
    chapter_inputs = "\n".join(
        rf"\input{{{chapter['stem']}}}" for chapter in chapters
    )
    commit = manifest["authority"]["commit"]
    year, month, day = (int(part) for part in manifest["snapshot_at"][:10].split("-"))
    return rf"""\input{{preamble}}
\begin{{document}}
\frontmatter
\begin{{titlepage}}
\thispagestyle{{empty}}
\centering
\vspace*{{25mm}}
{{\fontsize{{30}}{{38}}\selectfont\bfseries Stacks Project\par}}
\vspace{{11mm}}
{{\fontsize{{27}}{{34}}\selectfont\bfseries 简体中文版\par}}
\vspace{{8mm}}
{{\Large 阶段性累积版\par}}
\vspace{{5mm}}
{{\large Mainland Simplified Chinese Cumulative Edition\par}}
\vfill
{{\large 当前收入 {chapter_count} 章\par}}
\vspace{{4mm}}
{{\normalsize 冻结英语 authority：\texttt{{{commit[:12]}}}\par}}
\vspace{{3mm}}
{{\normalsize {year} 年 {month} 月 {day} 日\par}}
\vfill
{{\small 生产者累积版；尚待独立中文审校与全书认证。\par}}
\end{{titlepage}}

\chapter*{{版本说明}}
\addcontentsline{{toc}}{{chapter}}{{版本说明}}
本卷是完整 Stacks Project 简体中文翻译的阶段性累积版，不是试译，也不冒充已经完成或认证的全书。当前只收入已经完成生产者检查并经 canon 机械重放的 {chapter_count} 章；其余章节会在完成后加入同一累积版本线。

中文 locale 明确为中国大陆规范的简体中文（\texttt{{zh-Hans-CN}}），不代表新加坡简体中文，也不代表台湾、香港或澳门的繁体中文本地化。正文采用 A4、11pt 正文字号、Noto Serif CJK SC、对称页边距和中文科技文献常用的首行缩进及行距。

英语 authority 固定为 Stacks Project 提交
\texttt{{{commit}}}。本卷保持该 authority 的正文与公式；疑似上游勘误只在非渲染 sidecar 中记录，未经证明不会悄悄改入中文正文。当前卷已收入章节之间的引用在本 PDF 内解析；尚未收入章节的引用链接到 Stacks Project 永久标签。

\begin{{multicols}}{{2}}
\begin{{itemize}}
{coverage_items}
\end{{itemize}}
\end{{multicols}}

原作版权：Copyright \copyright\ 2005--2025 Johan de Jong。原作与本衍生版依 GNU Free Documentation License 1.2 或其后版本发布，无不变章节、封面文字或封底文字。完整许可证见附录。原作者与贡献者、项目历史以及最新英语原文见 \url{{https://stacks.math.columbia.edu/}}。

\tableofcontents
\mainmatter
{chapter_inputs}

\appendix
{index_input}
\input{{fdl-body}}

\backmatter
\bibliography{{my}}
\bibliographystyle{{amsalpha}}
\end{{document}}
"""


def main() -> None:
    manifest_data = MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_data.decode("utf-8"))
    if manifest["authority"]["commit"] != "a04446e57ec1fbc252a871afcec7752fb2807b14":
        raise RuntimeError("unexpected authority commit")

    verified_inputs: list[dict[str, object]] = []
    dependency_paths: dict[str, Path] = {}
    for dependency in manifest["dependencies"]:
        path = verify_bound_file(dependency)
        dependency_paths[dependency["role"]] = path
        verified_inputs.append(file_identity(path))

    chapter_reports: list[dict[str, object]] = []
    generated_material_reports: dict[str, dict[str, object]] = {}
    generated_paths: list[Path] = []
    all_labels: set[str] = set()
    all_label_counts: Counter[str] = Counter()
    all_references: set[str] = set()

    for chapter in manifest["chapters"]:
        authority_path = verify_bound_file(chapter["authority"])
        target_binding = chapter.get("replay_target", chapter["target"])
        target_path = verify_bound_file(target_binding)
        intake_path = verify_bound_file(chapter["intake"])
        chapter_inputs = [
            file_identity(authority_path),
            file_identity(target_path),
            file_identity(intake_path),
        ]
        replay_receipt_identity: dict[str, object] | None = None
        if "replay_target" in chapter:
            replay_receipt_path = verify_bound_file(chapter["replay_receipt"])
            replay_receipt_identity = file_identity(replay_receipt_path)
            chapter_inputs.append(replay_receipt_identity)
        verified_inputs.extend(chapter_inputs)
        source_text = target_path.read_text(encoding="utf-8")
        target_stage = str(chapter.get("target_stage", "locale_source"))
        if target_stage == "locale_source":
            transformed, report = transform_standalone(
                source_text,
                stem=chapter["stem"],
                chapter=int(chapter["chapter"]),
                expected_title=chapter["title"],
            )
        elif target_stage == "generated_standalone_chapter":
            expected_prefix = (
                f"% Generated mechanically from the frozen {chapter['stem']}.tex target.\n"
                "% Do not edit this generated file; edit the bound locale source instead.\n"
            )
            if not source_text.startswith(expected_prefix):
                raise RuntimeError(
                    f"generated-stage freeze header drift in {chapter['stem']}"
                )
            counter_header = f"\\setcounter{{chapter}}{{{int(chapter['chapter']) - 1}}}"
            chapter_header = f"\\chapter{{{chapter['title']}}}"
            counter_offset = source_text.find(counter_header, len(expected_prefix), 1024)
            chapter_offset = source_text.find(chapter_header, len(expected_prefix), 1024)
            if counter_offset < 0 or chapter_offset <= counter_offset:
                raise RuntimeError(
                    f"generated-stage chapter counter/title drift in {chapter['stem']}"
                )
            transformed = source_text
            transformed_labels = LABEL_RE.findall(transformed)
            transformed_refs = REF_RE.findall(transformed)
            if any(
                not label.startswith(str(chapter["stem"]) + "-")
                for label in transformed_labels
            ):
                raise RuntimeError(
                    f"unprefixed label in generated-stage freeze {chapter['stem']}"
                )
            report = dict(chapter["historical_transform_report"])
            if len(transformed_labels) != int(report["generated_labels"]):
                raise RuntimeError(
                    f"generated-stage label-count drift in {chapter['stem']}"
                )
            if len(transformed_refs) != int(report["generated_references"]):
                raise RuntimeError(
                    f"generated-stage reference-count drift in {chapter['stem']}"
                )
            report.update(
                {
                    "stem": chapter["stem"],
                    "chapter": int(chapter["chapter"]),
                    "title": chapter["title"],
                }
            )
        else:
            raise RuntimeError(
                f"unsupported target stage in {chapter['stem']}: {target_stage}"
            )
        destination = SRC / f"{chapter['stem']}.tex"
        write_text(destination, transformed)
        generated_paths.append(destination)
        transformed_labels = LABEL_RE.findall(transformed)
        all_labels.update(transformed_labels)
        all_label_counts.update(transformed_labels)
        all_references.update(REF_RE.findall(transformed))
        report["output"] = file_identity(destination)
        report["logical_target"] = chapter.get(
            "historical_logical_target", chapter["target"]
        )
        report["target_stage"] = target_stage
        if "replay_target" in chapter:
            report["replay_target"] = file_identity(target_path)
            report["replay_receipt"] = replay_receipt_identity
        chapter_reports.append(report)

    generated_material = manifest.get("generated_material", {})
    if generated_material:
        if set(generated_material) != {"index"}:
            raise RuntimeError(
                "unsupported generated material: "
                + ", ".join(sorted(generated_material))
            )
        index = generated_material["index"]
        if index.get("stem") != "index":
            raise RuntimeError("the generated index must use reserved stem 'index'")
        reserved_stems = {
            "index",
            "fdl",
            "fdl-body",
            "preamble",
            "tagrefs",
            "reader",
        }
        chapter_stems = {str(chapter["stem"]) for chapter in manifest["chapters"]}
        collisions = sorted(reserved_stems & chapter_stems)
        if collisions:
            raise RuntimeError(f"reserved generated stem collision: {collisions}")
        index_target = verify_bound_file(index["target"])
        index_intake = verify_bound_file(index["intake"])
        verified_inputs.extend(
            [file_identity(index_target), file_identity(index_intake)]
        )
        index_text, index_report = transform_standalone(
            index_target.read_text(encoding="utf-8"),
            stem="index",
            chapter=None,
            expected_title=str(index["title"]),
        )
        index_destination = SRC / "index.tex"
        write_text(index_destination, index_text)
        generated_paths.append(index_destination)
        transformed_index_labels = LABEL_RE.findall(index_text)
        if "index-section-phantom" not in transformed_index_labels:
            raise RuntimeError(
                "generated index lacks required index-section-phantom label"
            )
        all_labels.update(transformed_index_labels)
        all_label_counts.update(transformed_index_labels)
        all_references.update(REF_RE.findall(index_text))
        index_report["required_self_link_label"] = {
            "label": "index-section-phantom",
            "present": True,
        }
        index_report["target"] = file_identity(index_target)
        index_report["intake"] = file_identity(index_intake)
        index_report["output"] = file_identity(index_destination)
        generated_material_reports["index"] = index_report

    fdl_path = dependency_paths["license_text"]
    fdl_text, fdl_report = transform_standalone(
        fdl_path.read_text(encoding="utf-8"),
        stem="fdl",
        chapter=None,
        expected_title="GNU Free Documentation License",
    )
    fdl_destination = SRC / "fdl-body.tex"
    write_text(fdl_destination, fdl_text)
    generated_paths.append(fdl_destination)
    transformed_fdl_labels = LABEL_RE.findall(fdl_text)
    all_labels.update(transformed_fdl_labels)
    all_label_counts.update(transformed_fdl_labels)
    all_references.update(REF_RE.findall(fdl_text))
    fdl_report["output"] = file_identity(fdl_destination)

    macro_witness = dependency_paths["zh_macro_witness"].read_text(encoding="utf-8")
    delta_witness = dependency_paths["zh_delta_witness"].read_text(encoding="utf-8")
    graphicx_witness = dependency_paths["zh_graphicx_witness"].read_text(encoding="utf-8")
    preamble_destination = SRC / "preamble.tex"
    write_text(
        preamble_destination,
        make_preamble(macro_witness, delta_witness, graphicx_witness),
    )
    generated_paths.append(preamble_destination)

    tag_map = parse_tags(dependency_paths["permanent_tags"].read_text(encoding="utf-8"))
    # Only references absent from the cumulative reader need a permanent-tag
    # fallback.  Current-volume labels resolve through the normal AUX table and
    # need not exist in the upstream tag registry.
    tagrefs, missing_tags, manual_tags = make_tagrefs(
        all_references - all_labels, tag_map
    )
    tagrefs_destination = SRC / "tagrefs.tex"
    write_text(tagrefs_destination, tagrefs)
    generated_paths.append(tagrefs_destination)

    class_destination = SRC / "stacks-project-book.cls"
    bibliography_destination = SRC / "my.bib"
    shutil.copyfile(dependency_paths["book_class"], class_destination)
    shutil.copyfile(dependency_paths["bibliography"], bibliography_destination)
    generated_paths.extend([class_destination, bibliography_destination])

    reader_destination = SRC / "reader.tex"
    write_text(reader_destination, make_reader(manifest))
    generated_paths.append(reader_destination)

    duplicate_labels = sorted(label for label, count in all_label_counts.items() if count > 1)
    if duplicate_labels:
        raise RuntimeError(f"duplicate generated labels: {duplicate_labels[:10]}")

    internal_reference_targets = sorted(all_references & all_labels)
    tagged_reference_targets = sorted(
        target for target in all_references - all_labels if target in tag_map
    )
    unresolved_reference_targets = sorted(
        target
        for target in all_references - all_labels
        if target not in tag_map and target not in MANUAL_REFERENCE_FALLBACKS
    )
    if unresolved_reference_targets != missing_tags:
        missing_only = sorted(set(missing_tags) - set(unresolved_reference_targets))
        unresolved_only = sorted(set(unresolved_reference_targets) - set(missing_tags))
        raise RuntimeError(
            "tag fallback accounting mismatch; "
            f"missing-only={missing_only[:20]} unresolved-only={unresolved_only[:20]}"
        )

    receipt = {
        "schema": "stacks-zh-hans-cn-source-replay/v1",
        "snapshot_at": manifest["snapshot_at"],
        "manifest": {
            "path": str(MANIFEST_PATH),
            "bytes": len(manifest_data),
            "sha256": sha256_bytes(manifest_data),
        },
        "authority_commit": manifest["authority"]["commit"],
        "locale": manifest["locale"],
        "chapter_count": len(manifest["chapters"]),
        "chapters": chapter_reports,
        "generated_material": generated_material_reports,
        "appendix_order": ["index", "fdl-body"]
        if generated_material_reports
        else ["fdl-body"],
        "license": fdl_report,
        "reference_resolution": {
            "unique_targets": len(all_references),
            "internal_targets": len(internal_reference_targets),
            "permanent_tag_targets": len(tagged_reference_targets),
            "manual_commit_pinned_targets": manual_tags,
            "unresolved_targets": unresolved_reference_targets,
        },
        "verified_inputs": verified_inputs,
        "generated_outputs": [file_identity(path) for path in sorted(generated_paths)],
        "passed": not unresolved_reference_targets,
    }
    write_text(
        SOURCE_RECEIPT,
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
    )
    if unresolved_reference_targets:
        raise RuntimeError(
            "unresolved nonlocal reference targets: "
            + ", ".join(unresolved_reference_targets[:20])
        )
    print(json.dumps(receipt, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
