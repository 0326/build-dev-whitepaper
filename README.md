# build-dev-whitepaper

面向软件、框架、协议和开发平台的开发者白皮书制作方法与工具包。

这个仓库将白皮书制作从一次性写作沉淀为可维护的工程流程：

项目级版本、来源锁、导航、文章、附件与论点证据由 canonical manifest 统一描述；对应 schema 与校验方式见 [Manifest 与 Schema](references/manifest.md)。

- 以官方源码、文档、测试和发布记录建立证据链；
- 按读者问题和概念依赖设计分组与独立文章；
- 用术语表、规范约定、来源索引和迁移表补足查阅需求；
- 把版本基线、内容核验和发布状态分开管理；
- 由 AI 负责理解、解释和论证，由脚本 / CI 负责可重复的结构与工程校验。

## 使用方式

将本目录作为 Codex skill 安装后，使用：

```text
$build-dev-whitepaper
请为这个项目创建或升级开发者白皮书，先核验官方资料，再设计文章分组、独立文章、术语表、规范附件和版本维护方案。
```

核心说明见 [SKILL.md](SKILL.md)。第一轮质量基线包括文章分型、标杆样稿、独立读者测试和最小评测集；从 [evals/README.md](evals/README.md) 开始运行。

结构校验：

~~~bash
python3 scripts/validate_evals.py
~~~

评测结果汇总：

~~~bash
python3 scripts/run_evals.py evals/fixtures/example-synthetic-run.json \
  --cases evals/evals.json
~~~

Manifest 结构校验：

~~~bash
python3 scripts/validate_manifest.py manifests/example.whitepaper.json --root .
~~~

## 目录

- `references/authoring.md`：读者路径、独立文章和写作深度
- `references/evidence-and-versions.md`：证据、来源锁和版本快照
- `references/engineering.md`：元数据投影、工程维护和离线审计
- `references/review.md`：内容与工程验收标准
- `references/dsh-example.md`：从 DSH 改版案例提炼的可迁移经验
- `assets/project-brief.md`：项目简报模板
- `assets/article.md`：通用独立文章模板
- `assets/article-types/`：五种文章类型模板与选择规则
- `examples/`：Raft 与 SQLite 的机制解释标杆样稿
- `references/reader-testing.md`：无作者上下文的独立读者测试协议
- `evals/evals.json`：第一轮最小评测集
- `evals/fixtures/example-synthetic-run.json`：评测 run 数据格式示例（非质量结论）
- `scripts/audit_snapshot.py`：只读的快照结构审计工具
- `scripts/validate_evals.py`：评测文件结构校验工具
- `scripts/run_evals.py`：逐项结果、证据和指标的 scorecard 汇总工具
- `schemas/`：白皮书、文章和来源的 JSON Schema
- `schemas/eval-run.schema.json`：评测 run JSON Schema
- `manifests/`：canonical manifest 示例
- `references/manifest.md`：Manifest 字段、迁移和扩展规则
- `scripts/validate_manifest.py`：manifest 结构与交叉引用校验工具

## 设计边界

DSH 的五组正文、RC + 稳定版策略、具体站点框架和路由只是项目设置，不是本方法的默认要求。小型库可以使用平铺 Markdown；协议、数据库或平台项目可以按自己的概念依赖组织目录。

本工具包不把开源对标项目当成目标项目事实来源，也不因目录齐全、构建成功或文件存在就自动宣称文章已核验。Manifest 是项目级元数据的唯一事实源，但校验通过仍不等于主张已被官方证据支持。examples/ 中的样稿只用于展示写作方法，事实范围以各自的官方来源声明为准。

## License

MIT


