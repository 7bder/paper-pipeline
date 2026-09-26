# paper-pipeline 编码与文档规范

> 读者：本仓库实现者与审查者（code review 的判定依据即本文件 + `architecture.md`）。

## 1. 文件与命名

- 目录/文件名：ASCII kebab-case，带**阶段号前缀**（`00-`…`70-`）；中文只允许出现在 `10-data/raw/**`（论文项目内），本仓库文档正文可中文，文件名不中文。
- 脚本：`scripts/{序号}-{用途}.py`，序号即职责段（30 生成、70 判据、75/78 守卫自测）。
- profile：`profiles/{00|10|20|30}-{领域}.yaml`，`00-` 为基类，`1x/2x/3x` 为领域/子领域档；档内 `version:` 与 `tool_dir/verify_tool` 是投喂口径，改动须在 `CHANGELOG.md` 留决策。
- 产物/临时物/原始件三分：产物入库、临时物落 `build*/`（`.gitignore` 已排）、原始件只读。

## 2. Python 脚本约定

- 顶部 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`（或等价的显式 UTF-8 输出层）：脚本输出的 FAIL 明细与 JSON 不得因宿主 console 编码（cp936）崩溃或截断。
- 读文本产物一律 `utf-8-sig`（剥 BOM）；`subprocess.run` 一律显式 `encoding="utf-8", errors="replace"`，不依赖 locale。
- 不得在目标项目或本仓库落 `.pyc`：跨进程调用带 `-B`，importlib 加载前设 `sys.dont_write_bytecode = True`。`.pyc` 内嵌本机绝对路径，属发布物污染。
- 只读承诺：技能脚本对**任何论文项目目录**零写入；写操作只落在 `--out` 指定处。
- 新脚本自带 `--selftest` 子命令（合成控制用例，离线可跑），不把守卫塞进 `75-verify-selftest.py`（那是基座与生成器的守卫面）。

## 3. 判据与断言

- `70-verify.py` 的断言类型集合**不得回退**；新增类型须同步 `--schema`、`assets/10-verify-manifest.template.json`、`SKILL.md` 判据基座小节三处。
- 展开后任务条目**四段全空 = 门禁空转**，生成期直接 die；实质判据（`contains` / `word_count` / `json_files` / `run`）优先于 `forbid + min_bytes` 通配。
- 退出码语义：FAIL 优先于 usage-error；单任务缺条目 = 2，不允许糊成 0。

## 4. 任务书写（orchd）

- `files_to_edit` / `exempt_files` 只列具体文件路径，禁目录式与通配；≤4 个为常态，5 个为上限（E029 锚点）。
- `verify_command`：单条命令、无管道、无 `;`、无嵌套引号 `python -c`；pytest 必须带 `--basetemp`；所引路径必须已声明或磁盘存在（E037）。
- acceptance_criteria：2–5 条，每条只判一件事，属"功能断言 / 数值阈值 / 行为边界 / 结构约束 / 否定条件"之一；禁"应该能 / 合理地 / 适当 / 正常 / 充分 / 足够"类模糊词。
- 共享单写真源（`SKILL.md`、`README.md`、`CHANGELOG.md`、`profiles/00-base-empirical.yaml`）：同一时刻只允许一个在途任务改动，由 `request` 的冲突过滤保证；分解时不为"逻辑相关"而造依赖，只有**必须读上游产出**或**同文件**才写 `depends_on`。
- 证据要求：报告"已修/已登记"必须给出 `file:line` 与生效机制链；判据类改动必须附反向对照（把判据拆掉后测试变红）。

## 5. 提交与中断纪律（git 工作树模式）

- 本仓库已纳入 git（远端 `7bder/paper-pipeline`）；改动以**任务分支 diff** 核算：引擎从 claim 时刻的 HEAD 建 `task/{id}` 分支，done/review 以该分支上的已提交改动判定越界。
- 结束时工作区必须只剩本任务声明文件的改动（或有明确说明）；未提交即中断属红线 5。
- 不手动跑 git 写操作（红线 1、2）：一律走 `orchd git` 代理，唯一豁免 = 任务分支上的 `git commit`（见 `.orchd/rules/git.md`）；也不手改 `_master.json` / `_ledger.jsonl` / `_checkpoint.json`。

## 6. 发布边界

- 入库：`SKILL.md`、`README.md`、`CHANGELOG.md`、`profiles/`、`references/`、`scripts/`、`assets/`、`static/`、`.gitignore`。
- 不入库：`build*/`（生成试验）、`_pilot/`（历史试点证据，需要时重建）、`reports/`（本机审计档案，如 09-26 审查报告）、`.orchd/` 引擎本体（仅 `_master.json`、`shared/`、`IDEAS.md`、`SKILL.md`、`rules/`、`VERSION`、`__main__.py` 跟踪）。
- 发布前实测：入库集合内机器路径/用户名命中数 = 0。
