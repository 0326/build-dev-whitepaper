# 最小评测集

evals.json 是本 Skill 的第一轮回归基线，覆盖小型项目、多版本迁移、机制解释、来源冲突、文章去重和近似误触发六种场景。

## 先做结构校验

在 Skill 仓库根目录运行：

~~~bash
python3 scripts/validate_evals.py
~~~

该命令只检查评测文件的 schema、唯一 ID、提示词和 expectations，不代表文章内容已经正确。

## 运行方式

使用支持 Agent Skill 的评测 harness，对每个 case 分别运行：

- with_skill：加载当前 SKILL.md；
- without_skill：不加载本 Skill，作为基线；
- 旧版本优化时，额外运行 old_skill：加载修改前的 Skill 快照。

每个配置至少运行 3 次，再逐条核对 expectations。记录：

- 每个 case 的通过率和失败证据；
- 总耗时、Token、工具调用和错误；
- 读者测试中出现的误解；
- Skill 带来的新增步骤和实际收益。

只有固定模型、提示词、输入资料和评分规则后，版本间的 pass rate 才具有可比性。写作质量中的准确性、因果和易读性仍需人工或独立读者审阅，不用“包含某个词”替代判断。

## 增加评测

新增 case 时，优先覆盖当前失败模式或近似误触发；为每条 expectation 写可观察结果，避免“文章质量好”“解释清楚”这类无法复核的句子。
