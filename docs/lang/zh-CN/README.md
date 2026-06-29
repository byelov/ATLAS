> **[English](../../../README.md)** | **简体中文** | **[日本語](../ja/README.md)** | **[한국어](../ko/README.md)**

<p align="center">
  <img src="../../images/herodemo.gif" alt="ATLAS TUI 实时演示"/><br/>
  <sub><i>ATLAS TUI 实时演示（10× 加速）。V3 Pipeline 正在创建文件。</i></sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-V3.1.0-blue" alt="Version"/>
  <img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="License"/>
  <img src="https://img.shields.io/badge/model-agnostic-green" alt="模型无关"/>
</p>

<h1 align="center">A.T.L.A.S.</h1>
<p align="center"><b>Adaptive Test-time Learning and Autonomous Specialization</b></p>

## 什么是 ATLAS

ATLAS 是一个跑在你自己 GPU 上的编程助手。你把它指向一个项目，它就能完成你平常会丢给 Claude 或 Copilot 的工作：读代码、写功能、修 bug。模型从不离开你的机器。

任何托管 AI 工具都意味着一份订阅、一次隐私让步，以及一个你只能祈祷它还在的厂商。ATLAS 都不是。代码留在你自己的硬件上。不按 token 计费。即使这个项目明天消失，已经装好的那一份照常工作。

开源模型一直追不上托管模型。ATLAS 用一层推理脚手架补上这个差距：生成前先做规划，用自生成测试验证答案，失败时自己修复。14B 参考构建在 LiveCodeBench 上得到 74.6%。ATLAS 标配运行能装进 $500 GPU 的 9B 模型，但并不绑定任何单一模型。

---

## 最新动态

- **2026-04-05** - **[V3.0.1 发布](../../../CHANGELOG.md)** - 交互式命令行、Docker Compose 部署、95.8% 可靠性
- **2026-04-03** - ["$500 GPU Beats Claude: Local AI Revolution for Web Devs"](https://ownet.it/blog/500-gpu-beats-claude-local-ai-revolution-for-web-devs) - ownet.it
- **2026-03-29** - ["A $500 GPU Just Outscored Claude Sonnet on Coding Benchmarks"](https://aivy.com.au/news/atlas-500-gpu-outperforms-claude-sonnet-coding/) - Aivy
- **2026-03-28** - ["Why a $500 GPU Can Beat Claude Sonnet on Coding Benchmarks"](https://medium.com/data-science-collective/why-a-500-gpu-can-beat-claude-sonnet-on-coding-benchmarks-6c8169ffe4fe) - Data Science Collective
- **2026-03-27** - ["ATLAS: A $500 GPU Outperforms Claude Sonnet"](https://clauday.com/article/b92c5551-b490-4d76-ae3d-d8dedf10d88b) - Clauday
- **2026-03-26** - [Hacker News 首页](https://news.ycombinator.com/item?id=47533297) - 489 点赞、285 条评论
- **2026-03-05** - **[V3.0 发布](../../reports/V3_ABLATION_STUDY.md)** - 在冻结的 Qwen3-14B 上实现 74.6% LiveCodeBench pass@1-v(k=3)
- **2026-02-18** - **[V2.0 发布](../../../CHANGELOG.md)** - 基准测试基础设施、HumanEval/MBPP/LiveCodeBench/GPQA/SciCode 评估套件

---

## ATLAS 的功能

1. **[atlas-tui](../../CLI.md)** - 基于 Bubbletea 的原生终端 UI，是官方聊天客户端 (PC-062)。在任意项目目录中输入 `atlas` 即可启动。
   - [实时 Pipeline 视图](../../CLI.md#panes) - 在侧边窗格中观察 V3 各阶段
   - [斜杠命令](../../CLI.md#slash-commands) - `/add`、`/diff`、`/commit`、`/run` 操作本地文件与 shell
   - [输入模式](../../CLI.md#input-modes) - 聊天、`!bash`、`/slash` 三种模式带提示下拉

2. **[atlas-proxy](../../ARCHITECTURE.md#3-atlas-proxy-outer-layer)** - 基于 Go 的代理循环，负责编排整个系统。
   - [工具调用路由](../../ARCHITECTURE.md#tools) - 按复杂度层级分类文件操作
   - [语法强制执行](../../ARCHITECTURE.md#grammar-enforcement) - GBNF 模式保证 JSON 输出有效
   - [BiasBusters](../../ARCHITECTURE.md#tool-selection-bias-mitigations-may-2026-biasbusters-synthesis) - 工具选择偏差的四层组合缓解（描述、语法禁用、系统提示、ASA 操控）
   - [安全限制](../../ARCHITECTURE.md#safety-limits) - 轮次上限、token 预算、超时

3. **[V3 Pipeline](../../ARCHITECTURE.md#4-v3-pipeline-inner-layer)** - 将单个提示词转化为已验证候选的多阶段代码生成流程。
   - [PlanSearch](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - 约束驱动的结构化规划
   - [DivSampling](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - 跨温度和策略的多样化候选生成
   - [Budget Forcing](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - 按阶段控制思维 token 分配
   - [PR-CoT Repair](../../reports/V3_ABLATION_STUDY.md#pr-cot-repair-36-rescues) - 用自生成测试做迭代修复
   - [Refinement Loops](../../reports/V3_ABLATION_STUDY.md#refinement-loop-6-rescues) - 沙箱验证与修正反复进行
   - [Derivation Chains](../../reports/V3_ABLATION_STUDY.md#derivation-chains-0-rescues) - 针对难题的多步推理

4. **[Geometric Lens](../../ARCHITECTURE.md#5-geometric-lens)** - 基于模型自身嵌入的能量打分，无需外部预言机。（[什么是 "Geometric Lens"？](../../ARCHITECTURE.md#why-geometric-lens)）
   - [C(x) Cost Field](../../ARCHITECTURE.md#scoring-models) - hidden-dim→512→128→1 的 MLP，用于评估候选质量
   - [G(x) Quality Prediction](../../ARCHITECTURE.md#scoring-models) - 用于候选选择的 XGBoost 集成
   - [RAG / PageIndex V2](../../ARCHITECTURE.md#rag--pageindex-v2) - 感知 AST 的代码检索与项目索引
   - [Confidence Router](../../ARCHITECTURE.md#confidence-router--pattern-cache) - Thompson Sampling 把算力集中到真正需要的候选

5. **[Sandbox](../../ARCHITECTURE.md#6-sandbox)** - 用于构建验证的隔离执行环境。
   - 多语言执行：Python、Rust、Go、C、Shell 等
   - 评分前做编译与检查
   - 同时运行自生成测试和已有测试套件

6. **[llama-server](../../CONFIGURATION.md#6-llama-server)** - 在单块消费级 GPU 上的本地 LLM 推理。
   - GPU 加速的量化推理 (Q6_K / Q4_K_M) - NVIDIA CUDA、AMD ROCm、Apple Metal（macOS 混合方案）和 Vulkan；Intel SYCL 在路线图上
   - token 级语法约束解码
   - 自嵌入（无需额外模型）

完整文档（安装指南、架构、配置、故障排查、基准测试报告，以及每个组件背后的[研究依据](../../SOURCES.md)）位于 [docs/](../../) 目录中。

---

## 快速开始

一键安装：
```bash
curl -fsSL https://raw.githubusercontent.com/itigges22/ATLAS/main/scripts/atlas-bootstrap.sh | bash
```
脚本会自动识别发行版（Ubuntu、Debian、RHEL、Fedora、Rocky、Alma）和 GPU 厂商（NVIDIA → nvidia-container-toolkit；AMD → ROCm 设备直通），安装相应的运行时，下载模型权重，构建 ASA 操控向量，并启动整个栈。预计 10–30 分钟，大部分时间花在模型下载上。

完成后，在任意项目目录中执行 `atlas`。

**系统要求**

| | |
|---|---|
| GPU | 显存 16GB 以上。NVIDIA (CUDA)、AMD (ROCm) 或 Apple Silicon (Metal，macOS 混合方案)；其余大多数 GPU 由 Vulkan 覆盖。参见 [SETUP.md § Supported GPUs](../../SETUP.md#supported-gpus)。 |
| 运行时 | Docker（NVIDIA：+ nvidia-container-toolkit；AMD：单独的 Docker 即可）或 Podman |
| Python | 3.9 及以上 |
| 磁盘 | 约 20GB CUDA / 约 22GB ROCm（模型权重 + 容器镜像） |

Apple Silicon 通过原生 macOS 混合 Metal 方案运行（原生 llama-server 负责推理，其余组件用 Docker - 详见 **[SETUP_MACOS.md](../../SETUP_MACOS.md)**）；Intel Arc (SYCL) 在路线图上。完整的手动安装路径（Docker Compose、裸机、K3s）和全部 bootstrap 参数请参见 **[SETUP.md](../../SETUP.md)**。

---

## 已知限制

- **Linux Docker 栈，外加一条原生 macOS 路径。** NVIDIA、AMD ROCm 和 Vulkan 的 Docker 路径今天即可使用；Apple Silicon 通过原生 macOS 混合 Metal 方案运行 ([#32](https://github.com/itigges22/ATLAS/issues/32))。Intel Arc / SYCL 在路线图上。
- **9B 模型尚未正式基准测试。** V3.1.0 搭载 Qwen3.5-9B 与完整 V3 Pipeline，但目前公开的 74.6% LiveCodeBench 分数来自 14B 参考构建。9B 的正式数据将随 V3.1.1 一起放出。14B 的方法论与消融实验见 [`docs/reports/V3_ABLATION_STUDY.md`](../../reports/V3_ABLATION_STUDY.md)；原始 trace 发布在 [HuggingFace](https://huggingface.co/datasets/itigges22/ATLAS)。
- **复杂功能添加可能不稳定。** 模型有时会在陌生代码库上花掉几轮在探索而不是写代码。相对 V3.0 测量时，9B 构建的稳定性已有提升；新的数据会随 V3.1.1 基准更新。
- **语法约束解码速度偏慢。** llama-server 上约 51 tok/s。

---

## 路线图

**V3.1.0** - 当前版本。Bubbletea TUI 成为官方聊天客户端 (PC-062)、`atlas init` 首次运行向导 (PC-054)、`atlas doctor` 安装诊断 (PC-053)、`atlas tier` 硬件感知预设 (PC-055)、K3s 部署模板恢复、安装时自动构建的 ASA 操控向量 (BiasBusters #4)。

**V3.1.1** - 更广的硬件覆盖（已合并到 `main`）。
- 通过 llama.cpp 支持 AMD ROCm - 包括 RDNA4 / RX 9070 (gfx1200/gfx1201) 以及社区验证过的显卡 ([#26](https://github.com/itigges22/ATLAS/issues/26))。
- Apple Silicon - 原生 macOS 混合 Metal 方案：用原生 llama-server 获得推理性能，其余组件用 Docker ([#32](https://github.com/itigges22/ATLAS/issues/32)，见 [SETUP_MACOS.md](../../SETUP_MACOS.md))。
- Vulkan 通用回退 - 单个镜像即可覆盖 AMD / Intel / Snapdragon / 通过 MoltenVK 的 Apple / CPU ([#114](https://github.com/itigges22/ATLAS/issues/114))。
- 9B 正式基准测试 - 在 Qwen3.5-9B 上跑 LiveCodeBench、GPQA Diamond、SciCode（进行中，[#28](https://github.com/itigges22/ATLAS/issues/28)）。

**V3.1.2** - 下一个小版本：自带模型 + 集群。
- ASA 逐模型校准对齐 ([#113](https://github.com/itigges22/ATLAS/issues/113)) 与本地 Lens 训练流水线 ([#100](https://github.com/itigges22/ATLAS/issues/100)) - 为非默认 GGUF 训练 ASA / Lens 工件。
- 自动化 HuggingFace 提交流水线 ([#102](https://github.com/itigges22/ATLAS/issues/102))。
- ROCm 跑在 K3s / Kubernetes 上 - 在 Pod 规格中挂载 `/dev/kfd` + `/dev/dri` hostPath 并加入 `render`/`video` 组（相当于集群版的 `docker-compose.rocm.yml`）。

**V3.2** - 下一个里程碑：更深入的代码推理与规划。
- 架构优先的规划阶段 - RPG 式的先规划后填充：在模块尺度规划，再在函数尺度实现 ([#120](https://github.com/itigges22/ATLAS/issues/120))。
- 结构化代码推理 - 通过 tree-sitter 构建调用图 + 可达性分析，外加语法无关的小波特征分解，实现多分辨率的"哪些文件重要"检索 ([#39](https://github.com/itigges22/ATLAS/issues/39))。
- 带采样的推理 - 兼顾效率与质量提升 ([#9](https://github.com/itigges22/ATLAS/issues/9))。

**待办 / 欢迎贡献**
- 硬件：ARM64 多架构构建 ([#115](https://github.com/itigges22/ATLAS/issues/115))、面向更大模型的多 GPU ([#34](https://github.com/itigges22/ATLAS/issues/34))、Intel oneAPI / SYCL ([#27](https://github.com/itigges22/ATLAS/issues/27))。
- 工具链：VS Code / JetBrains 扩展 ([#35](https://github.com/itigges22/ATLAS/issues/35))。
- 沙箱语言：Java / Kotlin ([#29](https://github.com/itigges22/ATLAS/issues/29))、Ruby / PHP ([#30](https://github.com/itigges22/ATLAS/issues/30))。
- 架构：模型无关的平台 ([#66](https://github.com/itigges22/ATLAS/issues/66))、用 SQLite 替代 Redis ([#57](https://github.com/itigges22/ATLAS/issues/57))。

---

## 参与贡献

我们以开源方式构建 ATLAS，并积极寻找贡献者和核心维护者。无论你是修复 bug、添加加速器支持，还是重新设计某个子系统 - 这里都有你的位置。如果你认为开源模型值得拥有更好的基础设施，欢迎加入我们一起构建。

详见 **[CONTRIBUTING.md](../../../CONTRIBUTING.md)**。

---

## 许可证

基于 [GNU Affero General Public License v3.0 (AGPL-3.0)](../../../LICENSE) 许可发布。
