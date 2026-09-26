<!-- orchd: agent 入口指针（由 orchd 安装器维护；如需自定义请保留该标记以免重复追加） -->
# AI agents

本项目使用 [orchd](https://github.com/7bder/orchd-core) 编排 AI agent 任务协作。

- 每个 AI agent 进场请先读 `.orchd/SKILL.md`（协议入口，含纪律红线与 guidance 导航）
- 引擎命令统一用 `python .orchd/__main__.py <子命令>`
- 具体规则按需读 `.orchd/rules/`（索引 `rules/README.md`）

若本目录尚无 `.orchd/`（新环境或尚未安装），可自行执行安装接入：

```bash
git clone https://github.com/7bder/orchd-core.git && python orchd-core/install.py . --agent --cleanup
```

装好后读 `.orchd/SKILL.md` 进入工作流。
<!-- /orchd -->
