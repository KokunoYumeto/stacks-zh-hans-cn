# Stacks Project 简体中文版

本目录维护面向中国大陆读者的 `zh-Hans-CN` 累积版。当前卷收入 63 个已经通过生产者检查和 canon 机械重放的完整章节；所有仍在生产中的部分章节均被排除。它不是试译，但在全书完成和独立中文审校之前明确标记为阶段性、未认证版本。

本卷严格以 Stacks Project 提交 `a04446e57ec1fbc252a871afcec7752fb2807b14` 为英语 authority。正文不悄悄改写上游数学内容；疑似勘误保存在非渲染 sidecar 中，经证明后才进入另行维护的 English AI edition。永久标签链接只用于当前卷尚未收入的外部章节；已经收入的交叉引用优先解析到本卷内部。

版式采用 A4、11pt 正文字号、Noto Serif CJK SC、对称 22 mm 页边距和适合中文科技文献的行距。目标是正文居中、充分利用页面且保持长公式可读。

## 重放

1. `python compose.py` 验证全部输入的字节数与 SHA-256，并生成 `src/`。
2. `powershell -ExecutionPolicy Bypass -File build.ps1` 重新组合并运行 XeLaTeX/BibTeX/XeLaTeX/XeLaTeX。
3. 最终 PDF、日志、字体/链接检查和逐页渲染检查存入 `build/` 与 `qa/`。

## 发布边界

简体中文版使用一个且只有一个 Zenodo concept DOI；后续章节作为同一 concept 下的新累积版本发布，不创建重复概念。日本语版和韩语版使用各自独立的 locale、仓库和 DOI lineage。GitHub 已于 2026-08-22 恢复；GitHub 发布保持为独立、窄范围的中文镜像，不与 English AI edition 或其他 locale 混合。

- 稳定中文概念 DOI：<https://doi.org/10.5281/zenodo.22060287>
- 当前 63 章版本 DOI：<https://doi.org/10.5281/zenodo.22062547>
- GitHub 镜像：<https://github.com/KokunoYumeto/stacks-zh-hans-cn>

源作品及本衍生版依 GNU Free Documentation License 1.2 或其后版本发布，无不变章节、封面文字或封底文字。完整许可证正文收入 PDF 附录。
