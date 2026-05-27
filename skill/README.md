# skill/

为下游使用 `fyuneru-pylib` 的项目准备的 agent 上下文 skill，提供 Claude Code 和 opencode 两种形态。设计目标：当下游项目的 AI agent 编写涉及 `fyuneru` 的代码时，按需自动加载本库的 API 参考，避免凭印象写错签名或漏掉关键约束。

## 目录结构

```
skill/
  README.md                       # 本文件
  references/                     # 共享：按模块拆出来的 API 参考（14 个）
    00_overview.md                # 项目约定 + extra 矩阵 + 配置 YAML
    01_result.md                  # Result / @safe / unwrap（所有模块都引用）
    10_logger.md
    11_config.md
    12_converter.md
    13_markdown_utils.md
    20_redis_toolkit.md
    21_s3_toolkit.md
    22_s3_source.md
    23_mongo_toolkit.md
    24_gemini_toolkit.md
    30_task_queue.md
    31_dramatiq_toolkit.md
    32_worker_env.md
    40_pipeline_project.md        # WorkerEnv + task_queue 项目骨架
  claudecode/fyuneru/
    SKILL.md                      # Claude Code skill（YAML frontmatter 按需触发）
    references -> ../../references  # symlink，指向共享 references/
  opencode/fyuneru/
    SKILL.md                      # opencode skill（YAML frontmatter 按需触发）
    references -> ../../references  # symlink，指向共享 references/
  opencode/fyuneru-pipeline/
    SKILL.md                      # opencode pipeline 搭建专用 skill
    references -> ../fyuneru/references
```

数字前缀分组：`0x` 通用 / `1x` 默认安装模块 / `2x` 可选 toolkit / `3x` pipeline 模块 / `4x` 下游 pipeline 项目骨架。

## 设计要点

- **索引 + 渐进式加载**：两个 `SKILL.md` 只列出 references 触发条件，agent 在动手前先读 `references/00_overview.md` + `references/01_result.md`，再按用户实际涉及的模块按需读 ref，避免一次灌 600 行进上下文。
- **references 共享**：两种形态通过 symlink 共用同一份 `references/`，SKILL.md 里路径统一写 `references/xx.md`。
- **pipeline 专用入口**：opencode 额外提供 `fyuneru-pipeline` skill，默认按 WorkerEnv + task_queue 的多节点骨架指导下游项目；单节点也使用同一骨架，worker 统一走 `worker/main.py --node <node>`。
- **与 `src/fyuneru/GUIDE.md` 的关系**：GUIDE.md 是「人读的完整版」，会随 pip 包分发；`references/*.md` 是从 GUIDE.md 拆出来的「机器按需读」版本。改 GUIDE.md 时请同步对应 reference 段落。

## 本机安装（symlink 方式）

在仓库根目录执行：

```bash
# Claude Code 全局
mkdir -p ~/.claude/skills
ln -s "$PWD/skill/claudecode/fyuneru" ~/.claude/skills/fyuneru

# opencode 全局
ln -s "$PWD/skill/opencode/fyuneru" ~/.config/opencode/skills/fyuneru
ln -s "$PWD/skill/opencode/fyuneru-pipeline" ~/.config/opencode/skills/fyuneru-pipeline
```

安装后 `~/.claude/skills/fyuneru/references/` 与 `~/.config/opencode/skills/fyuneru/references/` 均通过 symlink 链式解析到本仓库的 `skill/references/`，skill 内容随仓库更新自动生效。

## 维护

- 改 [`src/fyuneru/GUIDE.md`](../src/fyuneru/GUIDE.md) 时，同步对应 `references/*.md` 段落
- 新增模块时：写 `references/<NN>_<module>.md` + 在两个 SKILL.md 的索引表里加一行
- 新增下游项目搭建范式时：优先写 `references/4x_*.md`，必要时新增 opencode 专用 skill 入口
- 不要在 `references/` 内重复维护内容，每个模块只放一份
