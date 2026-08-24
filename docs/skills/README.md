# PatentAid Skills — Claude Code Marketplace

PatentAid 的 6 个内置 Claude Code skills 已打包为一个通用 marketplace（`patent-aid-skills`），
可在任何 Claude Code 环境中安装使用。

## 通用性说明

这套 skills 面向**任何技术领域**的专利撰写：

- `idea-to-disclosure` 把一句话技术想法（或随手画/截图）转成可直接提交的标准中文专利交底书（Word）
- 文档内置的示例覆盖电力、管道检测机器人等领域，但流程本身与领域无关——
  只要你描述得出问题和方案，它就能起草交底书与申请文件
- 全程带防无中生有（anti-hallucination）检查与权利要求格式校验，AI 不会编造审查员会拒掉的数据

## 安装

在 Claude Code 中执行两条命令：

```
/plugin marketplace add https://github.com/KumnXi/patent-aid
/plugin install idea-to-disclosure@patent-aid-skills
```

安装后可随时调用 `/idea-to-disclosure`、`/patent-writer` 等 skill。

## Skills 一览

| Skill | 用途 | 触发场景 |
|---|---|---|
| `idea-to-disclosure` | 从技术想法生成标准专利交底书（项目核心流程），支持贴图/草图输入 | 提供技术想法/问题/方案，要求"生成交底书""写技术交底"或一键出 Word |
| `patent-writer` | 从技术交底书生成完整中国专利申请文件（权利要求书 + 说明书 + 摘要） | 手上有技术交底书，需撰写申请文件的具体章节 |
| `compliance-checker` | 专利文件合规性检查：权利要求格式、术语一致性、引用关系等 | 要求"检查专利文件合规性""审查权利要求格式"或生成后的格式校验 |
| `patent-supervisor` | 专利撰写监督官：监控进展、审查质量、确保各阶段达标（含防 AI 编造数据） | 要求"监督撰写进度""审查当前专利文件质量"或流程中需要阶段质量把关 |
| `patent-orchestrator` | 专利撰写流程编排器：协调 writer / checker / supervisor 三角色，驱动"交底书 → 专利"完整流程 | 手上有交底书并要求生成完整专利申请文件，进入撰写阶段 |
| `patent-fetcher` | 获取/检索专利全文，填充参考专利库作为撰写依据 | 要求"获取某专利""搜索某领域专利""补充参考专利库" |

## 使用示例

一句话想法即可起步：

```
你：我有一个想法——一种基于多传感器融合的地下管道缺陷检测机器人。
Claude：自动识别意图 → 调用 /idea-to-disclosure → 产出标准交底书 Word
```

已有交底书、想要完整申请文件时：

```
你：帮我把这份交底书写成完整的专利申请文件（权利要求书 + 说明书 + 摘要）。
Claude：调用 /patent-orchestrator 编排 /patent-writer → /compliance-checker → /patent-supervisor
```

## 上架状态与待办

**当前状态**：本地 marketplace 已就绪（`.claude-plugin/marketplace.json`，6 个 skill 与
`.claude/skills/` 目录一一对应）。**官方 marketplace 提交为待办**，需由仓库所有者执行：

### 1. 发布 tag

```bash
git tag -a v1.0.0 -m "patent-aid-skills v1.0.0"
git push origin v1.0.0
```

### 2. 本地校验

```bash
claude plugin validate .          # 需实测确认通过（结果以实际输出为准，勿断言）
```

### 3. 提交官方 marketplace（Anthropic Claude Code 插件市场）

- **个人作者**：打开 <https://platform.claude.com/plugins/submit> 提交
- **Team / Enterprise 组织**：`claude.ai` 管理后台 → 目录设置 → 提交新插件
- 提交前请确保：仓库公开、`README.md` 完整、`.claude-plugin/marketplace.json` 通过校验

### 4. 审核与确认上架

- 提交后经自动化安全筛查与校验；通过后插件被固定（pin）到
  `anthropics/claude-plugins-community` 仓库的特定 commit SHA
- 后续推送新 commit 时，CI 会自动更新该 pin（改动需重新审核）
- 在 <https://github.com/anthropics/claude-plugins-community> 的
  `.claude-plugin/marketplace.json` 中搜索 `patent-aid` 即可确认是否已上架
