---
title: "ZenWiki 系统时序图 & 触发图"
date: 2026-04-29
---

# ZenWiki 系统时序图 & 触发图

## 1. 模块依赖图（静态结构）

```mermaid
graph TD
    CLI["cli.py<br/><i>Typer 命令入口</i>"]
    COMPILER["compiler.py<br/><i>Agent CLI 编排</i>"]
    PENDING["pending.py<br/><i>待处理文件检测</i>"]
    MANIFEST["manifest.py<br/><i>状态追踪 + 溯源</i>"]
    LINT["lint.py<br/><i>确定性健康检查</i>"]
    SEARCH["search.py<br/><i>qmd 搜索适配器</i>"]
    DEDUP["dedup.py<br/><i>Token Jaccard 去重</i>"]
    INDEX["index.py<br/><i>index.md / log.md</i>"]
    MD["markdown.py<br/><i>frontmatter / wikilink</i>"]
    CONFIG["config.py<br/><i>配置加载</i>"]
    WEB["web.py<br/><i>FastAPI + Web UI</i>"]

    CLI --> COMPILER
    CLI --> PENDING
    CLI --> LINT
    CLI --> SEARCH
    CLI --> DEDUP
    CLI --> INDEX
    CLI --> MANIFEST
    CLI --> WEB
    CLI --> CONFIG
    CLI --> MD

    COMPILER --> PENDING
    COMPILER --> MANIFEST
    COMPILER --> MD
    COMPILER --> CONFIG
    COMPILER --> LINT

    PENDING --> MANIFEST

    MANIFEST --> CONFIG
    MANIFEST --> MD

    LINT --> CONFIG
    LINT --> MD

    DEDUP --> MD

    INDEX --> CONFIG
    INDEX --> MD

    WEB --> CONFIG
    WEB --> SEARCH
    WEB --> INDEX
    WEB --> MD

    SEARCH -.-> |"子进程调用"| QMD["qmd CLI"]
    COMPILER -.-> |"子进程调用<br/>(/ingest 编译)"| AGENT["Agent CLI<br/>(claude / codex)"]
    WEB -.-> |"子进程调用<br/>(/query 触发 /zenwiki-ask)"| AGENT
    AGENT -.-> |"按 description 加载"| SKILL["my-wiki/.claude/skills/<br/>zenwiki-ask/SKILL.md<br/><i>Q&A 工作流</i>"]
    SKILL -.-> |"在 skill 内调用<br/>zenwiki search/find-similar/..."| CLI

    style AGENT fill:#f9f,stroke:#333
    style QMD fill:#f9f,stroke:#333
    style SKILL fill:#bfb,stroke:#333
```

---

## 2. 自动编译完整时序图（`zenwiki compile`）

这是系统的核心链路，从用户放入文件到 git commit 的完整时序。

```mermaid
sequenceDiagram
    participant User as 用户
    participant CLI as cli.py
    participant Compiler as compiler.py
    participant Pending as pending.py
    participant Manifest as manifest.py
    participant FS as 文件系统 (raw/ wiki/)
    participant Agent as Agent CLI (claude/codex)
    participant Lint as lint.py
    participant Git as git

    User->>CLI: zenwiki compile
    CLI->>Compiler: compile_once(root)

    Note over Compiler: ─── 阶段 1: 扫描 ───
    Compiler->>Pending: get_pending(root)
    Pending->>Manifest: scan_raw(root)
    Manifest->>FS: 遍历 raw/ 所有文件
    FS-->>Manifest: 文件列表 + stat (mtime, size)
    Manifest->>Manifest: 对比 manifest.json<br/>mtime/size 变化 → 计算 SHA-256
    Manifest->>FS: 写回 manifest.json
    Manifest-->>Pending: manifest dict
    Pending-->>Compiler: PendingFile[] (status=pending|failed)

    Note over Compiler: ─── 阶段 2: 检测 Agent ───
    Compiler->>Compiler: detect_agent(config)<br/>which claude / which codex

    Note over Compiler: ─── 阶段 3: 并行编译 ───
    Compiler->>Compiler: 分批 (batch_size=2)

    par 批次 1 (ThreadPoolExecutor)
        Compiler->>Compiler: _compile_batch(batch_1)
        Compiler->>Compiler: build_prompt(batch_1)
        Compiler->>Agent: subprocess.run(claude -p "prompt")
        Note over Agent: Agent 读 CLAUDE.md<br/>按 /ingest 工作流处理：<br/>1. 读 raw/ 源文件<br/>2. zenwiki find-similar<br/>3. 写 wiki/summaries/<br/>4. 写/更新 entities/ concepts/<br/>5. zenwiki rebuild-index<br/>6. zenwiki refresh<br/>7. zenwiki log "ingest|..."
        Agent-->>Compiler: 进程退出
        loop 每个 PendingFile
            Compiler->>Compiler: _verify_single(root, pf)
            Compiler->>FS: 扫描 wiki/summaries/*.md
            Compiler->>Manifest: slug ? mark_compiled : mark_failed
        end
    and 批次 2
        Compiler->>Agent: subprocess.run(claude -p "prompt")
        Agent-->>Compiler: 进程退出
        Compiler->>Manifest: mark_compiled / mark_failed
    and 批次 3
        Compiler->>Agent: subprocess.run(claude -p "prompt")
        Agent-->>Compiler: 进程退出
        Compiler->>Manifest: mark_compiled / mark_failed
    end

    Note over Compiler: ─── 阶段 4: Lint Gate ───
    Compiler->>Lint: run_lint(wiki/)
    Lint->>FS: 读取所有 wiki 页面
    Lint->>Lint: 5 条规则检查
    Lint-->>Compiler: LintReport (issues[])
    Compiler->>Compiler: 过滤：仅新编译的 summaries/
    alt 存在 blocking issues (missing_frontmatter / empty_section)
        Compiler->>Manifest: mark_failed(raw_path)
        Compiler->>Compiler: compiled → failed (降级)
        Note over Compiler: lint-gate ✗ 输出
    else 仅 warning issues
        Note over Compiler: lint-gate ⚠ 输出
    end

    Note over Compiler: ─── 阶段 5: Auto Commit ───
    Compiler->>Git: git add wiki/ .zenwiki/
    Compiler->>Git: git diff --cached --quiet
    alt 有变更
        Compiler->>Git: git commit -m "compile: N compiled, M failed"
    end

    Compiler-->>CLI: CompileResult
    CLI-->>User: 输出统计
```

---

## 3. Watch 模式时序图（`zenwiki compile --watch`）

```mermaid
sequenceDiagram
    participant User as 用户
    participant CLI as cli.py
    participant Compiler as compiler.py
    participant Watchdog as watchdog Observer
    participant Timer as threading.Timer
    participant FS as raw/ 目录

    User->>CLI: zenwiki compile --watch
    CLI->>Compiler: watch(root)
    Compiler->>Watchdog: observer.schedule(Handler, raw/)
    Compiler->>Watchdog: observer.start()
    Note over Compiler: 阻塞，等待 Ctrl+C

    loop 持续监听
        FS->>Watchdog: 文件变化事件
        Watchdog->>Timer: 取消旧 Timer<br/>启动新 Timer (30s 去抖)
        Note over Timer: 等待 30 秒<br/>(防止用户还在拷贝文件)
        Timer->>Compiler: _trigger()
        Compiler->>Compiler: compile_once(root)
        Note over Compiler: 完整编译流程<br/>(同上面的时序)
    end

    User->>Compiler: Ctrl+C
    Compiler->>Watchdog: observer.stop()
```

---

## 4. Serve 模式时序图（`zenwiki serve`）

```mermaid
sequenceDiagram
    participant User as 用户
    participant CLI as cli.py
    participant Watcher as compile watcher
    participant Vite as Vite Dev Server (:5173)
    participant API as FastAPI (:3334)
    participant Browser as 浏览器

    User->>CLI: zenwiki serve
    CLI->>Watcher: start_watcher(root)
    Note over Watcher: watchdog 监听 raw/<br/>(后台线程)
    CLI->>Vite: subprocess.Popen(npx vite)
    Note over Vite: React 前端 :5173
    CLI->>API: uvicorn.run(app, :3334)
    Note over API: FastAPI 阻塞主线程

    CLI->>Browser: webbrowser.open (2s 延迟)

    par 用户浏览
        Browser->>Vite: http://localhost:5173
        Vite->>API: proxy /tree /doc /search /status<br/>/crystallize /rebuild-index /refresh-index
        API-->>Vite: JSON
        Vite->>API: proxy /query (EventSource — SSE)
        API-->>Vite: text/event-stream<br/>(results / step / done)
        Vite-->>Browser: 渲染页面 + 实时进度
    and 自动编译 (后台)
        Note over Watcher: raw/ 文件变化 → 30s 去抖 → compile_once()
    end
```

---

## 5. Agent /ingest 工作流时序图

这是 Agent 内部的工作流 — Agent 读 CLAUDE.md 后按照规则执行。

```mermaid
sequenceDiagram
    participant Agent as Agent CLI
    participant CLAUDE as CLAUDE.md (Schema)
    participant ZW as zenwiki CLI 工具
    participant FS as wiki/ 文件系统
    participant Search as qmd 搜索引擎

    Agent->>CLAUDE: 读取规则和模板
    Note over Agent: 理解 6 种页面类型<br/>frontmatter schema<br/>交叉引用规则

    loop 每个待处理的 raw 文件
        Agent->>FS: 读取 raw/papers/xxx.pdf

        Agent->>ZW: zenwiki find-similar "Flash Attention"
        ZW-->>Agent: JSON [{path, title, score}]

        alt score > 0.8 → 已有页面
            Agent->>FS: 更新已有 wiki 页面
        else 全新概念
            Agent->>FS: 写 wiki/summaries/xxx.md
            Note over FS: frontmatter:<br/>title, source_path,<br/>tags, importance,<br/>date_added
            Agent->>FS: 写/更新 wiki/entities/*.md
            Agent->>FS: 写/更新 wiki/concepts/*.md
            Agent->>FS: 写/更新 wiki/comparisons/*.md (如适用)
        end

        Agent->>FS: 更新双向 [[wikilinks]]

        Agent->>ZW: zenwiki rebuild-index
        Agent->>ZW: zenwiki refresh
        ZW->>Search: WikiIndex.refresh() → SQLite FTS5 增量更新<br/>+ qmd update / qmd embed (若可用)

        Agent->>ZW: zenwiki log "ingest | added: ... | updated: ..."
    end
```

---

## 6. Web UI 查询时序图（Ask AI + Crystallize）

Web UI 搜索栏只有一种交互：**Ask AI**。按 Enter 后 FastAPI 不再"自己拼 prompt"，而是把任务整体外包给 `zenwiki-ask` skill —— spawn `claude -p "/zenwiki-ask <q>"`，把 stream-json 事件翻译成 SSE 推给浏览器。`/zenwiki-ask` 前缀是必需的（stage-0 验证：description 自动匹配在 `-p` 模式不可靠）。合成返回后可选 Crystallize 把问答沉淀回 wiki。

```mermaid
sequenceDiagram
    participant User as 用户 (浏览器)
    participant Vite as React 前端
    participant API as FastAPI 后端
    participant FTS as SQLite FTS5
    participant QMD as qmd vsearch (可选)
    participant Agent as Agent CLI<br/>(claude / codex)
    participant Skill as zenwiki-ask skill<br/>(.claude/skills/)
    participant FS as wiki/ 文件系统

    Note over User: Ask AI (Enter)
    User->>Vite: 输入问题，按 Enter
    Vite->>API: GET /query?q=... (EventSource)

    Note over API: ─── 阶段 1: 本地检索 → 结果面板 ───
    API->>FTS: hybrid_search(q, limit=10,<br/>exclude_deprecated=True,<br/>promote=maps,comparisons)
    par 并行检索
        FTS->>FTS: BM25 (jieba + frontmatter 折入 title)
    and
        FTS->>QMD: qmd vsearch (仅当 qmd 在 PATH)
        QMD-->>FTS: JSON 向量结果
    end
    FTS->>FTS: RRF 融合 + 硬位推举 + 过滤 deprecated
    FTS-->>API: top-10 SearchResult[]
    API-->>Vite: SSE event: results<br/>{results: [{path, score, snippet}]}

    Note over API: ─── 阶段 2: spawn agent + skill 接管 ───
    API->>Agent: subprocess.create_subprocess_exec<br/>claude -p "/zenwiki-ask <q>"<br/>--allowed-tools "Bash(zenwiki:*),Read"<br/>--output-format stream-json --verbose
    Agent->>Skill: 按 /zenwiki-ask 前缀强制加载 SKILL.md

    loop skill 多步检索（典型 3-5 turn）
        Skill->>Agent: 工具调用 Bash: zenwiki search "<q>" --json ...
        Agent-->>API: stream-json: assistant tool_use Bash
        API-->>Vite: SSE event: step {kind: "searching", detail: cmd}
        Skill->>FS: zenwiki search 子进程 → 读 wiki 页面
        Skill->>Agent: 工具调用 Read: wiki/<top-K>.md
        Agent-->>API: stream-json: assistant tool_use Read
        API-->>Vite: SSE event: step {kind: "reading", detail: path}
    end

    Skill->>Agent: 综合答案 → emit JSON {answer, sources}
    Agent-->>API: stream-json: assistant text (首次出现)
    API-->>Vite: SSE event: step {kind: "synthesizing"}
    Agent-->>API: stream-json: result envelope
    API->>API: parse envelope.result 为 inner JSON
    API-->>Vite: SSE event: done<br/>{answer, sources}

    Vite-->>User: 渲染回答 + sources 链接 + 💎 Crystallize 按钮

    Note over User: Crystallize (可选)
    User->>Vite: 点击 💎 Crystallize to Wiki
    Vite->>API: POST /crystallize {question, answer, sources}
    API->>FS: 写 wiki/outputs/{slug}.md<br/>(frontmatter 含 citations)
    API->>FS: rebuild_index() 更新 index.md
    API->>FS: append_log() 记录到 log.md
    API->>FTS: WikiIndex.refresh() 立即进搜索
    API-->>Vite: {path, slug}
    Vite-->>User: ✓ 已沉淀到 outputs/xxx.md
```

**几个关键点**：

- **本地检索结果会跑两次**：FastAPI 阶段 1 跑一次给 UI 透明面板用，skill 内部又跑一次给 LLM 综合用。前者廉价（SQLite + 可选 qmd），换来 UI 不耦合 skill 输出 schema。
- **Codex 路径退化**：`_detect_query_agent` 选到 codex 时不走 stream-json（schema 未实测），改成 `subprocess.run` + 一次性 `done` 事件，无中途 step 进度。
- **qmd 不在 PATH 时静默降级**为纯 BM25；整条链路依旧可用，只是检索精度下降。
- **`--allowed-tools` 是变长 flag**：必须放在 prompt 之后，否则会贪婪吞掉 prompt 参数 —— 这是 `_Agent.argv()` 把 prompt 夹在 `pre`（`-p`）和 `post`（`--output-format ...` `--allowed-tools ...`）之间的原因。

---

## 7. 系统触发图（谁触发谁）

展示所有入口动作和它们触发的内部调用链。

```mermaid
graph TB
    subgraph 用户入口
        E2["zenwiki compile"]
        E3["zenwiki compile --watch"]
        E4["zenwiki serve"]
        E5["zenwiki lint"]
        E6["zenwiki search"]
        E7["zenwiki pending"]
        E8["zenwiki status"]
        E9["zenwiki provenance"]
        E10["zenwiki find-similar"]
        E11["zenwiki rebuild-index"]
        E12["zenwiki refresh"]
        E13["zenwiki doctor"]
        E14["Agent 手动交互<br/>(claude / codex)"]
    end

    subgraph 内部模块
        scan["scan_raw()<br/>manifest.py"]
        pending["get_pending()<br/>pending.py"]
        detect["detect_agent()<br/>compiler.py"]
        batch["_compile_batch()<br/>compiler.py"]
        verify["_verify_single()<br/>compiler.py"]
        lintfn["lint()<br/>lint.py"]
        commit["_auto_git_commit()<br/>compiler.py"]
        searchfn["search()<br/>search.py"]
        dedupfn["find_similar()<br/>dedup.py"]
        idx["rebuild_index()<br/>index.py"]
        logfn["append_log()<br/>index.py"]
        refreshfn["refresh()<br/>search.py"]
        prov["get_provenance()<br/>manifest.py"]
        watcher["start_watcher()<br/>compiler.py"]
    end

    subgraph 外部进程
        agent_proc["Agent CLI<br/>(claude -p / codex exec)"]
        qmd_proc["qmd CLI<br/>(search / query / update)"]
        git_proc["git<br/>(add / commit)"]
    end

    subgraph "Skill 资产"
        skill_md["my-wiki/.claude/skills/<br/>zenwiki-ask/SKILL.md"]
    end

    E2 --> pending --> scan
    E2 --> detect --> agent_proc
    E2 --> batch --> verify
    batch --> agent_proc
    E2 --> lintfn
    E2 --> commit --> git_proc

    E3 --> watcher
    watcher -->|"文件变化 + 30s 去抖"| E2

    E4 --> watcher
    E4 -->|":3334"| API["FastAPI"]
    E4 -->|":5173"| VITE["Vite"]
    API --> searchfn --> qmd_proc
    API -->|"/query → spawn<br/>'/zenwiki-ask <q>'"| agent_proc
    agent_proc -->|"按 description 加载"| skill_md
    skill_md -->|"skill 内调用<br/>(子进程)"| E6
    skill_md -->|"skill 内调用"| E10

    E5 --> lintfn

    E6 --> searchfn --> qmd_proc

    E7 --> pending

    E8 -->|"统计页面数"| idx

    E9 --> prov --> scan

    E10 --> dedupfn

    E11 --> idx

    E12 --> refreshfn --> qmd_proc

    E14 -->|"Agent 内部调用"| E10
    E14 -->|"Agent 内部调用"| E11
    E14 -->|"Agent 内部调用"| E12
    E14 -->|"Agent 内部调用"| E6
    E14 --> logfn

    style agent_proc fill:#f9f,stroke:#333
    style qmd_proc fill:#bbf,stroke:#333
    style git_proc fill:#bfb,stroke:#333
    style skill_md fill:#bfb,stroke:#333
```

---

## 8. 数据流向图（信息从哪来，到哪去）

```mermaid
graph LR
    subgraph "源材料层 (只读)"
        RAW["raw/<br/>papers/ articles/<br/>notes/ docs/"]
    end

    subgraph "状态层"
        MANIFEST[".zenwiki/manifest.json<br/>SHA-256 + status + slug"]
    end

    subgraph "知识层 (Agent 维护)"
        INDEX["wiki/index.md<br/>全量目录"]
        LOG["wiki/log.md<br/>操作日志"]
        SUM["wiki/summaries/<br/>源摘要 (1:1 raw)"]
        ENT["wiki/entities/<br/>人物/公司/工具"]
        CON["wiki/concepts/<br/>理论/方法/技术"]
        CMP["wiki/comparisons/<br/>跨源对比"]
        MAP["wiki/maps/<br/>领域全景"]
        OUT["wiki/outputs/<br/>查询回写"]
    end

    subgraph "搜索层"
        FTS[".zenwiki/search.db<br/>SQLite FTS5 (BM25 + jieba)"]
        QMD_IDX["~/.cache/qmd/<br/>qmd 向量索引 (可选)"]
    end

    subgraph "访问层"
        WEBUI["Web UI (:5173)"]
        OBSIDIAN["Obsidian"]
        GIT["Git 仓库"]
    end

    RAW -->|"Agent 读取"| SUM
    RAW -->|"scan_raw() 计算 hash"| MANIFEST
    SUM -->|"source_path 回指"| RAW
    SUM -->|"wikilinks"| ENT
    SUM -->|"wikilinks"| CON
    ENT <-->|"双向 wikilinks"| CON
    CON -->|"对比分析"| CMP
    ENT --> MAP
    CON --> MAP

    SUM --> INDEX
    ENT --> INDEX
    CON --> INDEX
    CMP --> INDEX
    MAP --> INDEX

    SUM --> FTS
    ENT --> FTS
    CON --> FTS
    FTS -.->|"可选向量补充"| QMD_IDX

    INDEX --> WEBUI
    INDEX --> OBSIDIAN
    INDEX --> GIT

    FTS --> WEBUI
    QMD_IDX --> WEBUI
    FTS -->|"Ask AI 检索 → Agent 合成"| OUT
```

---

## 9. 编译单文件的完整生命周期

一个 raw 文件从进入系统到最终呈现的全部状态变迁。

```mermaid
stateDiagram-v2
    [*] --> detected: 用户放入 raw/

    detected --> pending_new: scan_raw() 发现新文件<br/>计算 SHA-256

    pending_new --> compiling: compile_once() 分配到批次

    compiling --> verify: Agent 进程退出

    verify --> lint_check: _verify_single() 找到 summary
    verify --> failed_no_summary: 未找到 summary

    lint_check --> compiled: lint gate 通过
    lint_check --> failed_lint: lint gate 拦截<br/>(missing_frontmatter / empty_section)

    compiled --> committed: auto_commit<br/>git add + commit
    committed --> searchable: refresh → qmd update

    failed_no_summary --> pending_retry: 下次 compile 自动重试
    failed_lint --> pending_retry: 下次 compile 自动重试
    pending_retry --> compiling: compile_once()

    state modified <<choice>>
    searchable --> modified: 用户修改 raw 源文件
    modified --> pending_modified: scan_raw() 检测到<br/>mtime/size 变化 + hash 不同
    pending_modified --> compiling

    state deleted <<choice>>
    searchable --> deleted: 用户删除 raw 源文件
    deleted --> source_removed: scan_raw() 标记
    source_removed --> pruned: compile --prune<br/>Agent 清理孤儿页面
```

---

## 10. Lint Gate 决策流程图

```mermaid
flowchart TD
    START["所有批次编译完成<br/>collected compiled_slugs"]
    START --> HAS_COMPILED{compiled_slugs<br/>不为空?}
    HAS_COMPILED -->|No| SKIP["跳过 lint gate"]
    HAS_COMPILED -->|Yes| RUN_LINT["run_lint(wiki/)"]
    RUN_LINT --> LOOP["遍历 report.issues"]
    LOOP --> IS_NEW{issue.path 对应的 slug<br/>在 compiled_slugs 中?}
    IS_NEW -->|No| LOOP
    IS_NEW -->|Yes| IS_BLOCKING{rule ∈ _LINT_GATE_BLOCKING?<br/>missing_frontmatter<br/>empty_section<br/>thin_summary<br/>missing_backlink<br/>link_to_deprecated}
    IS_BLOCKING -->|Yes| DEMOTE["mark_failed(raw_path)<br/>compiled → failed<br/>输出: lint-gate ✗"]
    IS_BLOCKING -->|No| WARN["输出: lint-gate ⚠"]
    DEMOTE --> LOOP
    WARN --> LOOP
    LOOP -->|遍历完成| SUMMARY["输出降级统计"]
    SUMMARY --> COMMIT["auto_commit<br/>(只有通过 lint 的页面是 compiled)"]
    SKIP --> COMMIT
```
