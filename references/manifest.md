# 白皮书 Manifest 与 Schema

Manifest 是项目级元数据的唯一事实源。它用于描述版本、来源锁、导航、独立文章、附件、论点与证据；站点菜单、版本选择、来源索引和审计输入都应从它投影，而不是再维护一份手工数组。

## 三层模型

| 层级 | 负责什么 | 典型字段 |
| --- | --- | --- |
| 项目策略 | 项目约定和版本入口 | `project`、`policy`、允许的发布通道、显式版本回退 |
| 版本快照 | 某一上游基线的完整文档集合 | `versions[*]`、`source_locks`、`groups`、`articles` |
| 文章证据 | 一篇文章的阅读职责与可追溯主张 | `type`、`normative_level`、`evidence`、`claims` |

`group` 只描述导航层级，`type` 描述读者任务，`kind` 区分正文和附件。项目可以有五组、两组或平铺目录；不要把某个项目的分组数量写进通用 schema。

## 来源锁与证据

- 顶层 `sources` 只登记来源身份、类型和官方属性，不代表它支持全部文章。
- 每个版本用 `source_locks` 固定该版本的 `ref`、Git commit、适用范围和访问时间。Git 来源必须有完整 40 或 64 位 commit；网页来源记录访问时间和范围。
- 文章用带稳定 `id` 的 `evidence` 引用当前版本的 `source_id`，并提供仓库路径、符号、章节、URL 等就近定位信息。
- `claims` 把一个可审阅主张绑定到文章和 evidence ID。`fact`、`inference`、`recommendation`、`unknown` 必须分开；verified 的事实或推断不能没有证据。

## 文章与附件

文章的 intrinsic metadata 可以放在 Markdown frontmatter 中，但版本、分组和发布状态以 manifest 为准。每篇文章必须有稳定 `id`、唯一 `slug`、主 `type`、读者对象、规范层级、核验状态和文件路径。

附件是一等文档，不是散落在首页末尾的链接。常见 `type` 包括：

- `glossary`：术语定义、同义词和禁止混用；
- `conventions`：本白皮书的阅读与编辑约定；
- `source-index`：官方来源、版本锁和访问范围；
- `compatibility`、`api-reference`、`checklist`、`faq`：按项目需要增加。

附件若描述上游契约，使用 `normative_level: normative` 并挂官方证据；只描述白皮书自身规则时使用 `editorial`，不能把编辑建议写成上游 MUST。

## 迁移现有白皮书

1. 为每个官方仓库、网页或第一方资料建立顶层 `sources` 条目。
2. 将每个维护中的版本放入 `versions`，固定发布通道、文档修订号、正文 / 图资产根目录和 `source_locks`。
3. 将现有分组、正文、术语表、规范和来源索引转成 `groups` 与 `articles`；同一文章 ID 可在不同版本快照中复用。
4. 将文章 frontmatter 的 `sources` 改为 `evidence`；每条证据增加稳定 ID，并用 `source_id` 指向当前版本的来源锁。
5. 对关键事实、推断和建议建立 `claims`；无法核实时保留 `unknown`、`blocked` 或 `draft`。
6. 先运行 manifest 校验，再运行固定来源审计、读者测试和内容评审。

## 校验命令

仓库提供不依赖第三方库的结构校验器：

```bash
python3 scripts/validate_manifest.py manifests/example.whitepaper.json
# 需要同时核对本地文章、附件和图资产时：
python3 scripts/validate_manifest.py manifests/example.whitepaper.json --root .
# 只检查一个版本：
python3 scripts/validate_manifest.py manifests/example.whitepaper.json --version v1.0.0
```

对应 JSON Schema 位于 `schemas/whitepaper.schema.json`、`schemas/article.schema.json` 和 `schemas/source.schema.json`。校验器负责字段、引用、版本、导航和本地路径一致性；它不替代官方来源核验、文章语义审读、Mermaid 渲染或独立读者测试。

## 扩展规则

优先复用现有字段。项目特有字段放在 `settings` 或以 `x-` 开头，避免修改通用字段语义。新增文章类型应先说明读者任务、验收问题和证据要求，再加入项目 profile；不要为了凑齐固定类型而拆文章。
