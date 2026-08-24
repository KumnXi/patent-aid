# PatentAid Demo 视频 — 分镜脚本与录制指引

> 目的：3 分钟主视频（mp4）+ 30 秒防编造 gif 配套素材，供用户录制时逐镜对照。
> 视频/gif 实际录制由用户在其环境执行（需要 DeepSeek API key + 录屏工具）。
> 最终成品放 `docs/demo/`（与 README 中 `docs/images/demo/*.png` 静态截图占位是两个独立产物，互不冲突）。

---

## 0. 录制前的环境与产物对齐

### 0.1 产物路径对照

| 产物 | 路径 | 用途 |
|---|---|---|
| 主视频 | `docs/demo/demo-3min.mp4` | GitHub README 嵌入、官网首页、社交媒体 |
| 防编造 gif | `docs/demo/anti-hallucination.gif` | README「Anti-hallucination before/after」位 |
| 静态截图（独立任务） | `docs/images/demo/{quickstart,anti-hallucination,word-output}.png` | README 表格位（由其他任务产出） |

### 0.2 命令入口速查

```bash
# 1) CLI 入口（最常用于录屏）
python scripts/generate_patent.py "A deep-learning-based method for defect detection in underground pipelines" --out output/disclosure.docx

# 2) Web UI 入口（用于录屏展示「零命令选项」）
python app.py
# 浏览器打开 http://localhost:5000

# 3) 交付自查（可选，画面素材：「.docx 渲染图 → AI 评图」）
python scripts/selfcheck_disclosure.py output/disclosure.docx
```

> **首次运行**：需先完成 `pip install -r requirements.txt` 与 `cp config/api_config.example.json config/api_config.json`（填入 DeepSeek `sk-` key）。首次会初始化专利数据库（约 1 分钟），建议录制前预热一次，避免正片出现"初始化中"等待镜头。

---

## 1. 3 分钟主视频分镜（180s）

**镜头编号规则**：`SC-序号`。**画面切换**指硬切，**叠化**指 0.3-0.5s 渐变。

| 时间 | 镜号 | 镜头 | 屏幕内容 | 旁白 / 字幕 | 备注 |
|---|---|---|---|---|---|
| 00:00-00:05 | SC-01 | 定场画面 | 黑底，居中显示 `PatentAid` 标题（白色无衬线大字号），副标题 `Turn your idea into a patent disclosure in 3 minutes` 淡入 | 旁白：「Writing a patent disclosure is high-barrier.」 | 画面静 2s，背景可叠 `docs/images/quickstart.png` 的低透明度版本作为纹理 |
| 00:05-00:10 | SC-02 | 对比痛点 | 左侧：手写专利的纸张/Word 文档堆叠（红 X 覆盖）；右侧：LLM 输出"实验数据表明准确率提升 30.7%"（红 X 覆盖） | 旁白：「And generic LLMs make it worse — they invent data your examiner will reject.」 | 节奏快，2 张图 0:03 + 0:02 切换 |
| 00:10-00:15 | SC-03 | 产品亮相 | 屏幕中央放大显示 `PatentAid` 标题 + 三条特性徽章：`Built-in anti-hallucination` `Standard patent format` `Native editable formulas` | 旁白：「PatentAid gives you a complete, standard-format disclosure — with built-in anti-hallucination.」 | 徽章依次淡入，节奏 0.5s/个 |
| 00:15-00:25 | SC-10 | 一句话想法 | 终端窗口（或 Web UI 输入框）高亮。命令/输入内容：`python scripts/generate_patent.py "A deep-learning-based method for defect detection in underground pipelines" --out output/disclosure.docx`（中文版可用「地下管道缺陷检测的多传感器融合机器人系统」） | 旁白：「One command. One idea. That's the input.」 | 输入时光标闪烁 1s 后回车 |
| 00:25-00:35 | SC-11 | 阶段 1 大纲规划 | 终端日志滚动：`[阶段 1/3] 大纲规划 LLM 输出 JSON 大纲 ... 01 背景  02 方案  03 效果 ... 64 项权利要求`。进度条 0→33% | 旁白：「Stage one: outline planning. Ten sections, sixty-four claim slots — generated as a JSON outline.」 | 进度条用绿色渐变，里程碑节点高亮 |
| 00:35-00:45 | SC-12 | 阶段 2 分章节生成 | 终端日志：`[阶段 2/3] 分章节生成 ... 8 维评分，<70 自动重写`。进度条 33→66%。右侧弹出评分小卡片：结构/长度/编号/技术深度/权利要求/实现细节/相关性/新颖度/对原想法支持（共 9 维，第 9 项作为后续镜头） | 旁白：「Stage two: section-by-section writing, with a nine-dimension quality check on every section.」 | 评分小卡片用色阶：绿 ≥85、橙 70-84、红 <70 |
| 00:45-00:50 | SC-13 | 阶段 3 质检迭代 | 终端日志：`[阶段 3/3] 质检迭代 完成`。进度条 100% 满格 + 短暂烟花特效 | 旁白：「Stage three: quality iteration. Weak sections rewrite themselves — rule-based, no extra LLM calls.」 | 此处可叠字幕「Three-stage generation · Quality iteration built-in」 |
| 00:50-01:00 | SC-20 | 防编造触发 | 终端日志切到新一屏：`[④ 防编造审查] 自动修复编造数据`。红色高亮一段虚构结论：`「实验数据显示，缺陷识别效率提升 30%」` | 旁白：「Now the part that matters most: anti-hallucination.」 | 红色高亮用 0.2s 闪烁两次 |
| 01:00-01:15 | SC-21 | 防编造修复前后 | 同一段文本被划掉（红色删除线），下方绿色高亮修复版：`「通过采用上述方案，能够实现对管道缺陷的有效识别」`（即把"实验数据 + 30%"降级为"示例性表述"）。左侧显示 before，右侧显示 after | 旁白：「The AI tried to invent an experiment with a 30% number. We strip out fabricated data, downgrade unverifiable quantities to qualitative language, and delete made-up patent numbers.」 | 红 → 绿切换用 0.4s 叠化 |
| 01:15-01:30 | SC-22 | 修复报告清单 | 终端滚动展示修复报告：`[防编造] 移除虚构专利号 CN10XXXX · 移除虚构实验数据 · 降级 3 处量化表述 · 1 处专利号 CN11... 替换为「相关现有技术」` | 旁白：「Every fix is logged. Nothing slips through.」 | 列表逐行出现，节奏 0.4s/行 |
| 01:30-01:45 | SC-30 | 9 维质检报告 | 弹窗显示完整 `quality_report.json` 可视化（雷达图或条形图）：结构 92 / 长度 88 / 编号 95 / 技术深度 86 / 权利要求 90 / 实现细节 85 / 相关性 94 / 新颖度 82 / 对原想法支持 96 | 旁白：「Nine-dimension quality review: structure, length, numbering, technical depth, claims, implementation, relevance, novelty, support for your original idea.」 | 雷达图用 9 轴，从中心向外动画展开 0.6s |
| 01:45-02:00 | SC-31 | 权利要求校验 | 终端日志：`[⑤ 权利要求校验] 编号 · 完整性 · 引用 · 特征条款 · 存在性 · 顺序 → 6/6 通过`。每项前显示绿色对勾（依次弹出） | 旁白：「Claim-format validation: numbering, completeness, referencing, feature clauses, existence, order — six checks, all green.」 | 对勾动画间隔 0.3s |
| 02:00-02:15 | SC-32 | 无新物质检查 | 终端日志：`[新增] 无新物质检查（no-new-matter）通过`。右侧小卡片：原始想法 vs 权利要求关键词对比，相似度 96% | 旁白：「And a no-new-matter check keeps your claims faithful to the idea you described.」 | 关键词对比用双栏并列，相似度数字放大显示 |
| 02:15-02:20 | SC-33 | 合规审查 | 终端日志：`[⑥ 合规审查] 禁用表述 / 引用关系 → 通过` | 旁白：「Compliance review: banned phrases, citation chains — clean.」 | 此处节奏可稍快，作为过渡 |
| 02:20-02:30 | SC-40 | 打开 Word | 文件管理器 / 命令行 `start output/disclosure.docx`（Windows）或 `open output/disclosure.docx`（macOS）。Word 打开文档，正文第一页显示 `说明书` 标题 + 章节 | 旁白：「Export. A standard Word document, ready to edit.」 | 打开过程用 1.5× 加速，最后 0.5s 正常速 |
| 02:30-02:40 | SC-41 | OMML 公式可编辑 | 滚动到 `具体实施方式` 章节，鼠标点击公式 `$E = mc^2$`（或 `L = \frac{1}{2} \rho v^2 S C_L`），弹出可编辑的公式编辑器（Word 内置，OMML 格式），双击进入编辑 | 旁白：「Formulas are native OMML — not images, not MathType. You can edit them right inside Word.」 | 鼠标点击动作 0.5s，进度 0.5s 放大公式 |
| 02:40-02:50 | SC-42 | Graphviz 附图 | 滚动到附图位置：一张 300 dpi 的专利风格框图（系统架构图，包含「图像采集 → 预处理 → 深度学习模型 → 缺陷分类」模块）。鼠标右键 → 图片另存为 → 确认 PNG 格式 | 旁白：「Figures are auto-generated from Mermaid via Graphviz, 300 dpi, patent-style.」 | 滚动动作 0.5s，右键菜单 0.5s，另存为对话框 0.5s |
| 02:50-02:55 | SC-43 | 完整目录 | 整页缩小滚动，依次显示：摘要 / 权利要求书 / 说明书 / 附图说明。底部字数统计：`全文 3,847 字 · 10 章 · 64 项权利要求 · 3 张附图` | 旁白：「One disclosure, standard format, all yours.」 | 滚动 1.5× 加速，最后静止 1s |
| 02:55-03:00 | SC-50 | 结尾引导 | 黑底居中：`⭐ Star on GitHub` + URL `github.com/<your-org>/patent-aid` + 副标题 `MIT License · Three-stage generation · Anti-hallucination built-in` | 旁白：「Star on GitHub — link in the description.」 | 静止 4s，最后 1s 渐隐 |

### 1.1 主视频转场与音频建议

- **转场**：SC-01→02 用叠化 0.5s；SC-03→10 用硬切（带轻微 0.1s 闪白）；其余段落间用 0.3s 叠化；SC-50 渐隐至黑。
- **背景音乐**：CC0 来源（如 YouTube Audio Library "Soft Corporate"），音量压至 -18dB，仅在 SC-01 / SC-50 段全开，中间段落留 30% 让旁白突出。
- **字幕**：所有终端命令与关键日志使用底部字幕条（黑底白字 16pt），旁白同步上移一行；公式与附图处字幕悬停 1s 后淡出。
- **节奏**：防编造段（00:50-01:30）是核心，故意放慢，让观众看清"红 → 绿"对照；其他生成阶段可适度 1.2-1.5× 加速。

---

## 2. 30 秒防编造 gif 分镜

**总时长 30s，文件大小目标 ≤ 15MB**。可直接用 ScreenToGif 录制终端窗口（约 900×600），或 OBS 录制后用 ffmpeg 压缩。

| 时间 | 镜号 | 屏幕内容 | 字幕 / 高亮 | 备注 |
|---|---|---|---|---|
| 00:00-00:08 | AG-01 | 终端窗口，居中运行命令（短版本）：`generate_patent.py "An AI-based pipeline defect detector"`。日志快速滚动显示 `[阶段 1] 大纲完成 · [阶段 2] 分章节完成 · [阶段 3] 质检通过` | 顶部字幕 `Stage 1 → 2 → 3 · all gates passed` | 滚动用 2× 加速 |
| 00:08-00:15 | AG-02 | 终端切到新一屏，红色高亮一行：`[防编造] 检测到虚构表述："实验数据表明检测效率提升 30%"` | 字幕 `Anti-hallucination triggered →` | 高亮闪烁两次 |
| 00:15-00:22 | AG-03 | 同一行划掉（红色删除线），下方绿色高亮修复版：`→ "通过采用上述方案，能够实现对管道缺陷的有效识别"` | 字幕 `30% → qualitative · patent# → "prior art"` | 修复用 0.4s 叠化 |
| 00:22-00:30 | AG-04 | 终端最后一行：`[✓] 导出完成：output/disclosure.docx (48 KB · 10 章 · 64 权利要求)`，然后用 `start output/disclosure.docx` 打开，文件图标显示 | 字幕 `No more hallucinated data.` | 打开用 1.5×，最后静止 2s |

### 2.1 gif 压缩建议

```bash
# ffmpeg 调色板模式，文件最小
ffmpeg -i demo-3min.mp4 -ss 00:00:50 -t 30 -vf "fps=15,scale=900:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 docs/demo/anti-hallucination.gif

# 进一步压缩（若仍 >15MB）
ffmpeg -i demo-3min.mp4 -ss 00:00:50 -t 30 -vf "fps=12,scale=720:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 docs/demo/anti-hallucination.gif
```

---

## 3. 录制指引清单

### 3.1 工具准备

| 用途 | 推荐工具 | 备选 | 备注 |
|---|---|---|---|
| mp4 录屏（Windows/macOS/Linux） | **OBS Studio 30+**（免费） | Camtasia（付费）、ShareX | OBS 设置：输出 H.264 mp4，分辨率 1920×1080，帧率 30fps，比特率 8-12 Mbps |
| gif 录屏（Windows） | **ScreenToGif 2.40+**（免费开源） | LICEcap、ffmpeg 直接录 | 录制前在 Editor 中直接裁剪到 30s 窗口 |
| gif 压缩 | **ffmpeg + 调色板模式** | gifsicle、ezgif.com | ffmpeg 调色板模式可压到源视频的 20-30% 大小 |
| 视频剪辑（可选） | **DaVinci Resolve**（免费）、CapCut | Adobe Premiere、剪映 | 若需加字幕、徽章、转场 |
| 终端美化 | Windows Terminal / iTerm2 | ConEmu | 字体推荐 `Cascadia Code` 或 `JetBrains Mono`，字号 16-20pt |
| 字体重置 | macOS | — | "加大对比度"、"减弱动态效果"全关 |

### 3.2 录制前 5 项必做

1. **预热**：`python -c "from src.core import PatentInnovationEngine; PatentInnovationEngine().initialize()"` 跑一次，避免正片出现 1 分钟初始化等待。
2. **API key 就绪**：`config/api_config.json` 填好 `sk-...`，并 `export DEEPSEEK_API_KEY=...`（若用环境变量）。
3. **终端窗口尺寸**：固定 1200×700（16:9 比例内），字体 16pt+；避免使用过窄窗口导致日志折行。
4. **关闭干扰项**：系统通知全静音、个人浏览器标签全关、Slack/微信最小化、屏幕录制时不接电话。
5. **示例想法备好**（中英文各一）：英文 `A deep-learning-based method for defect detection in underground pipelines`；中文 `地下管道缺陷检测的多传感器融合机器人系统`。

### 3.3 录制时 4 项注意

1. **命令路径绝对化**：演示时用 `python scripts/generate_patent.py ...`，不要用相对路径或 IDE 快捷键，避免观众看不清入口。
2. **不要展示真实 key**：若用环境变量，注意 `echo $DEEPSEEK_API_KEY` 之类的命令禁用；配置文件演示用 `cat config/api_config.example.json`，不要 `cat config/api_config.json`。
3. **进度节点留 1-2s 静止**：每个阶段（日志输出"阶段 1 完成"）后让观众看清再切镜，不要瞬切。
4. **错误不要重录**：若 LLM 偶发返回格式错误，重跑一次比剪辑掉帧更自然；若 LLM 把数字写错（"提升 30.7%"），正好用于防编造段，无需重录。

### 3.4 后期 3 项建议

1. **关键帧加标注**：防编造段（SC-20/21/22）加红框 + 绿色箭头 + 文字标注，让观众 0.5s 内抓住重点。
2. **旁白优先**：若自录旁白不专业，强烈建议用 ElevenLabs / 阿里云 CosyVoice 合成（CC0 风格：年轻男声 / 中性女声，语速 0.9×），不要用默认 TTS。
3. **结尾卡片统一**：所有视频/gif 结尾用同一张黑底卡片（GitHub URL + 许可证），形成品牌记忆点。

### 3.5 命名与放置

```
docs/demo/
├── storyboard.md              ← 本文件
├── demo-3min.mp4              ← 3 分钟主视频
├── demo-3min.zh.mp4           ← 3 分钟中文版（可选）
└── anti-hallucination.gif     ← 30 秒防编造 gif（≤15MB）
```

### 3.6 时间预估

| 阶段 | 耗时 |
|---|---|
| 环境预热 + 试跑 | 10 min |
| 主视频录制（分段） | 60-90 min |
| 主视频后期（剪辑 + 字幕 + 旁白） | 120-180 min |
| 防编造 gif 录制 + 压缩 | 30 min |
| 浏览器/手机预览校对 | 20 min |
| **合计** | **4-6 小时** |

---

## 4. 与 README 的衔接（录制完成后）

录制完成后，需要在 README 的 `## Demo` 段补一行：

```markdown
[![Demo video](docs/images/demo/video-thumbnail.png)](docs/demo/demo-3min.mp4)
[![Anti-hallucination](docs/images/demo/anti-hallucination.png)](docs/demo/anti-hallucination.gif)
```

视频缩略图（`docs/images/demo/video-thumbnail.png`）可由 ffmpeg 截取主视频第 5 秒静帧：

```bash
ffmpeg -i docs/demo/demo-3min.mp4 -ss 00:00:05 -vframes 1 docs/images/demo/video-thumbnail.png
```

> 注：README 现有占位 `docs/images/demo/{quickstart,anti-hallucination,word-output}.png` 由产品包装计划其他任务产出，与本任务的 mp4/gif 是独立产物，命名上特意区分（视频 vs 静态截图）以避免路径冲突。

---

## 5. 验收清单（录制完成后逐项打勾）

- [ ] `docs/demo/demo-3min.mp4` 存在，时长 170-200s
- [ ] `docs/demo/anti-hallucination.gif` 存在，时长 28-32s，文件 ≤ 15MB
- [ ] 主视频包含三阶段生成（00:15-00:50）镜头
- [ ] 主视频包含防编造红 → 绿对照（00:50-01:30）镜头
- [ ] 主视频包含 9 维质检可视化（01:30-01:45）镜头
- [ ] 主视频包含权利要求校验 6/6 通过（01:45-02:00）镜头
- [ ] 主视频包含 OMML 公式可编辑（02:30-02:40）镜头
- [ ] 主视频包含 Graphviz 附图（02:40-02:50）镜头
- [ ] 视频中无真实 API key、个人邮箱、手机号等隐私信息
- [ ] 终端字体在 1920×1080 下清晰可读
- [ ] 结尾 GitHub URL 正确，与仓库实际路径一致
