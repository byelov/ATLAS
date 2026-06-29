> **[English](../../../README.md)** | **[简体中文](../zh-CN/README.md)** | **[日本語](../ja/README.md)** | **한국어**

<p align="center">
  <img src="../../images/herodemo.gif" alt="ATLAS TUI 실행 모습"/><br/>
  <sub><i>ATLAS TUI 라이브 데모 (10배속). V3 파이프라인이 파일을 생성하는 모습.</i></sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-V3.1.0-blue" alt="버전"/>
  <img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="라이선스"/>
  <img src="https://img.shields.io/badge/model-agnostic-green" alt="모델 독립적"/>
</p>

<h1 align="center">A.T.L.A.S.</h1>
<p align="center"><b>Adaptive Test-time Learning and Autonomous Specialization</b></p>

## ATLAS란

ATLAS는 본인 GPU에서 돌아가는 코딩 어시스턴트입니다. 프로젝트에 가리키면 Claude나 Copilot에 시킬 법한 일(코드베이스 읽기, 기능 작성, 버그 수정)을 합니다. 모델은 본인 머신을 떠나지 않습니다.

호스팅형 AI 도구는 모두 구독료, 프라이버시 양보, 그리고 살아남기를 바라야 하는 벤더에 매여 있습니다. ATLAS는 그 어느 것도 아닙니다. 코드는 본인 하드웨어에 머뭅니다. 토큰별 과금이 없습니다. 이 프로젝트가 내일 사라져도 이미 깔린 것은 계속 작동합니다.

오픈 모델은 역사적으로 호스팅형을 따라잡지 못해 왔습니다. ATLAS는 추론 스캐폴딩 레이어로 그 격차를 메웁니다. 생성 전 계획 수립, 자체 생성한 테스트로 답 검증, 실패 부분 수리. 14B 레퍼런스 빌드는 LiveCodeBench에서 74.6%를 기록했습니다. ATLAS는 표준으로 500달러 GPU에 들어가는 9B를 돌리지만, 특정 모델에 묶여 있지는 않습니다.

---

## 최신 소식

- **2026-04-05** - **[V3.0.1 출시](../../../CHANGELOG.md)** - 대화형 CLI, Docker Compose 배포, 95.8% 안정성
- **2026-04-03** - ["$500 GPU Beats Claude: Local AI Revolution for Web Devs"](https://ownet.it/blog/500-gpu-beats-claude-local-ai-revolution-for-web-devs) - ownet.it
- **2026-03-29** - ["A $500 GPU Just Outscored Claude Sonnet on Coding Benchmarks"](https://aivy.com.au/news/atlas-500-gpu-outperforms-claude-sonnet-coding/) - Aivy
- **2026-03-28** - ["Why a $500 GPU Can Beat Claude Sonnet on Coding Benchmarks"](https://medium.com/data-science-collective/why-a-500-gpu-can-beat-claude-sonnet-on-coding-benchmarks-6c8169ffe4fe) - Data Science Collective
- **2026-03-27** - ["ATLAS: A $500 GPU Outperforms Claude Sonnet"](https://clauday.com/article/b92c5551-b490-4d76-ae3d-d8dedf10d88b) - Clauday
- **2026-03-26** - [Hacker News 첫 페이지](https://news.ycombinator.com/item?id=47533297) - 489 포인트, 285 댓글
- **2026-03-05** - **[V3.0 출시](../../reports/V3_ABLATION_STUDY.md)** - 동결된 Qwen3-14B에서 LiveCodeBench pass@1-v(k=3) 74.6% 달성
- **2026-02-18** - **[V2.0 출시](../../../CHANGELOG.md)** - 벤치마크 인프라, HumanEval/MBPP/LiveCodeBench/GPQA/SciCode 평가 모음

---

## ATLAS의 기능

1. **[atlas-tui](../../CLI.md)** - 네이티브 Bubbletea 터미널 UI. 공식 채팅 클라이언트 (PC-062). 프로젝트 디렉토리에서 `atlas`를 입력해 실행합니다.
   - [라이브 파이프라인 뷰](../../CLI.md#panes) - 사이드 패널에서 V3 단계를 실시간으로 확인
   - [슬래시 명령](../../CLI.md#slash-commands) - `/add`, `/diff`, `/commit`, `/run` 으로 파일/셸 조작
   - [입력 모드](../../CLI.md#input-modes) - 채팅, `!bash`, `/slash` 모드 전환과 힌트 드롭다운

2. **[atlas-proxy](../../ARCHITECTURE.md#3-atlas-proxy-outer-layer)** - 시스템 전체를 오케스트레이션하는 Go 에이전트 루프.
   - [도구 호출 라우팅](../../ARCHITECTURE.md#tools) - 파일 작업을 복잡도 등급별로 분류
   - [문법 강제](../../ARCHITECTURE.md#grammar-enforcement) - GBNF 스키마로 JSON 출력의 유효성을 보장
   - [BiasBusters](../../ARCHITECTURE.md#tool-selection-bias-mitigations-may-2026-biasbusters-synthesis) - 도구 선택 편향 완화의 4단계 조합 (설명, 문법 금지, 시스템 노트, ASA 스티어링)
   - [안전 제한](../../ARCHITECTURE.md#safety-limits) - 턴 상한, 토큰 예산, 타임아웃

3. **[V3 파이프라인](../../ARCHITECTURE.md#4-v3-pipeline-inner-layer)** - 단일 프롬프트를 검증된 후보로 바꾸는 멀티 페이즈 코드 생성.
   - [PlanSearch](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - 제약 기반 구조화 계획
   - [DivSampling](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - 온도와 전략에 따른 다양한 후보 생성
   - [Budget Forcing](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - 페이즈별 사고 토큰 할당
   - [PR-CoT Repair](../../reports/V3_ABLATION_STUDY.md#pr-cot-repair-36-rescues) - 자체 생성 테스트 케이스를 활용한 반복 수정
   - [Refinement Loops](../../reports/V3_ABLATION_STUDY.md#refinement-loop-6-rescues) - 샌드박스 검증과 수정 반복
   - [Derivation Chains](../../reports/V3_ABLATION_STUDY.md#derivation-chains-0-rescues) - 복잡한 문제를 위한 다단계 추론

4. **[Geometric Lens](../../ARCHITECTURE.md#5-geometric-lens)** - 모델 자체 임베딩 위에서 동작하는 에너지 기반 스코어링. 외부 오라클 불필요. (["Geometric Lens"란?](../../ARCHITECTURE.md#why-geometric-lens))
   - [C(x) Cost Field](../../ARCHITECTURE.md#scoring-models) - 후보 품질을 스코어링하는 hidden-dim→512→128→1 MLP
   - [G(x) Quality Prediction](../../ARCHITECTURE.md#scoring-models) - 선택에 쓰이는 XGBoost 앙상블
   - [RAG / PageIndex V2](../../ARCHITECTURE.md#rag--pageindex-v2) - AST 인식 코드 검색과 프로젝트 인덱싱
   - [Confidence Router](../../ARCHITECTURE.md#confidence-router--pattern-cache) - Thompson Sampling으로 필요한 후보에 연산 집중

5. **[Sandbox](../../ARCHITECTURE.md#6-sandbox)** - 빌드 검증을 위한 격리 실행 환경.
   - 다중 언어 실행: Python, Rust, Go, C, Shell 등
   - 스코어링 전 컴파일과 린팅
   - 생성된 테스트와 기존 테스트 스위트 실행

6. **[llama-server](../../CONFIGURATION.md#6-llama-server)** - 단일 소비자용 GPU에서의 로컬 LLM 추론.
   - GPU 가속 양자화 추론 (Q6_K / Q4_K_M) — NVIDIA CUDA, AMD ROCm, Apple Metal (macOS 하이브리드), Vulkan; Intel SYCL은 로드맵에 있음
   - 토큰 수준 문법 제약 디코딩
   - 셀프 임베딩 (별도 모델 불필요)

전체 문서 (설정, 아키텍처, 구성, 문제 해결, 벤치마크 보고서, 각 구성요소의 [연구 배경](../../SOURCES.md))는 [docs/](../../) 디렉토리에 있습니다.

---

## 시작하기

원샷 설치:
```bash
curl -fsSL https://raw.githubusercontent.com/itigges22/ATLAS/main/scripts/atlas-bootstrap.sh | bash
```
배포판(Ubuntu, Debian, RHEL, Fedora, Rocky, Alma)과 GPU 벤더(NVIDIA → nvidia-container-toolkit; AMD → ROCm 디바이스 패스스루)를 자동 감지해 적절한 런타임을 설치하고, 모델 가중치 다운로드, ASA 스티어링 벡터 빌드, 스택 기동을 수행합니다. 소요 시간은 약 10~30분이며 대부분 모델 다운로드 시간입니다.

완료 후 프로젝트 디렉토리에서 `atlas`를 실행하세요.

**요구 사항**

| | |
|---|---|
| GPU | VRAM 16GB 이상. NVIDIA (CUDA), AMD (ROCm), 또는 Apple Silicon (Metal, macOS 하이브리드); 그 외 대부분의 GPU는 Vulkan으로 커버됩니다. [SETUP.md § Supported GPUs](../../SETUP.md#supported-gpus) 참고. |
| 런타임 | Docker (NVIDIA: + nvidia-container-toolkit; AMD: 단독 Docker로 충분) 또는 Podman |
| Python | 3.9 이상 |
| 디스크 | 약 20GB CUDA / 약 22GB ROCm (모델 가중치 + 컨테이너 이미지) |

Apple Silicon은 macOS 하이브리드 Metal 경로(추론은 네이티브 llama-server, 나머지 스택은 Docker — **[SETUP_MACOS.md](../../SETUP_MACOS.md)** 참고)를 통해 네이티브로 동작합니다. Intel Arc (SYCL)는 로드맵에 있습니다. Docker Compose, 베어메탈, K3s 수동 설치 경로와 부트스트랩 플래그 전체 목록은 **[SETUP.md](../ko/SETUP.md)**를 참고하세요.

---

## 알려진 제한 사항

- **Linux Docker 스택과 네이티브 macOS 경로.** NVIDIA, AMD ROCm, Vulkan Docker 경로는 현재 제공됩니다. Apple Silicon은 네이티브 macOS 하이브리드 Metal 경로([#32](https://github.com/itigges22/ATLAS/issues/32))로 동작합니다. Intel Arc / SYCL은 로드맵에 있습니다.
- **9B 모델 공식 벤치마크 미실시.** V3.1.0은 Qwen3.5-9B와 전체 V3 파이프라인을 제공하지만, 공개된 74.6% LiveCodeBench 점수는 14B 레퍼런스 빌드 기준입니다. 9B 공식 수치는 V3.1.1 출시와 함께 공개됩니다. 14B 방법론과 어블레이션은 [`docs/reports/V3_ABLATION_STUDY.md`](../../reports/V3_ABLATION_STUDY.md)에, 원시 트레이스는 [HuggingFace](https://huggingface.co/datasets/itigges22/ATLAS)에 있습니다.
- **복잡한 기능 추가는 불안정할 수 있음.** 모델이 익숙하지 않은 코드베이스를 너무 오래 탐색해 코드를 늦게 쓰는 경우가 있습니다. 9B 빌드에서는 V3.0 측정 시점보다 안정성이 개선되었으며, 최신 수치는 V3.1.1 벤치마크와 함께 갱신될 예정입니다.
- **문법 제약 디코딩 속도가 느림.** llama-server에서 약 51 tok/s.

---

## 로드맵

**V3.1.0** - 현재 릴리스. Bubbletea TUI가 공식 채팅 클라이언트로 (PC-062), `atlas init` 초기 설정 마법사 (PC-054), `atlas doctor` 진단 도구 (PC-053), `atlas tier` 하드웨어 인식 프리셋 (PC-055), K3s 배포 템플릿 복원, 설치 시 자동 빌드되는 ASA 스티어링 벡터 (BiasBusters #4).

**V3.1.1** - 더 넓은 하드웨어 지원 (`main`에 반영 완료).
- llama.cpp 경유 AMD ROCm — RDNA4 / RX 9070 (gfx1200/gfx1201)과 커뮤니티 검증 카드 포함 ([#26](https://github.com/itigges22/ATLAS/issues/26)).
- Apple Silicon — 네이티브 macOS 하이브리드 Metal 경로: 추론 성능을 위한 네이티브 llama-server, 나머지 스택은 Docker ([#32](https://github.com/itigges22/ATLAS/issues/32), [SETUP_MACOS.md](../../SETUP_MACOS.md) 참고).
- Vulkan 범용 폴백 — AMD / Intel / Snapdragon / MoltenVK 경유 Apple / CPU를 하나의 이미지로 커버 ([#114](https://github.com/itigges22/ATLAS/issues/114)).
- 9B 공식 벤치마크 — Qwen3.5-9B에서 LiveCodeBench, GPQA Diamond, SciCode (진행 중, [#28](https://github.com/itigges22/ATLAS/issues/28)).

**V3.1.2** - 다음 포인트 릴리스: BYO 모델 + 클러스터.
- ASA 모델별 캘리브레이션 패리티 ([#113](https://github.com/itigges22/ATLAS/issues/113))와 로컬 Lens 학습 파이프라인 ([#100](https://github.com/itigges22/ATLAS/issues/100)) — 기본 GGUF가 아닌 모델에 대해 ASA / Lens 아티팩트 학습.
- 자동화된 HuggingFace 제출 파이프라인 ([#102](https://github.com/itigges22/ATLAS/issues/102)).
- K3s / Kubernetes 상의 ROCm — `/dev/kfd` + `/dev/dri` hostPath 마운트와 Pod 스펙의 `render`/`video` 그룹 멤버십 (`docker-compose.rocm.yml`의 클러스터 등가물).

**V3.2** - 다음 마일스톤: 더 깊은 코드 추론과 계획.
- 아키텍처 우선 계획 페이즈 — RPG 스타일의 계획 후 채우기: 모듈 범위에서 계획하고 함수 범위에서 구현 ([#120](https://github.com/itigges22/ATLAS/issues/120)).
- 구조적 코드 추론 — tree-sitter를 통한 콜 그래프 + 도달성 분석에 더해, 다중 해상도 "어떤 파일이 중요한가" 검색을 위한 구문 비의존적 wavelet 피처 분해 ([#39](https://github.com/itigges22/ATLAS/issues/39)).
- 샘플링 기반 추론 — 효율성과 품질 향상 ([#9](https://github.com/itigges22/ATLAS/issues/9)).

**백로그 / 도움 요청**
- 하드웨어: ARM64 멀티 아키텍처 빌드 ([#115](https://github.com/itigges22/ATLAS/issues/115)), 더 큰 모델을 위한 멀티 GPU ([#34](https://github.com/itigges22/ATLAS/issues/34)), Intel oneAPI / SYCL ([#27](https://github.com/itigges22/ATLAS/issues/27)).
- 툴링: VS Code / JetBrains 확장 ([#35](https://github.com/itigges22/ATLAS/issues/35)).
- 샌드박스 언어: Java / Kotlin ([#29](https://github.com/itigges22/ATLAS/issues/29)), Ruby / PHP ([#30](https://github.com/itigges22/ATLAS/issues/30)).
- 아키텍처: 모델 비의존적 플랫폼 ([#66](https://github.com/itigges22/ATLAS/issues/66)), Redis 대신 SQLite ([#57](https://github.com/itigges22/ATLAS/issues/57)).

---

## 기여하기

ATLAS는 오픈으로 개발되고 있으며, 기여자와 핵심 메인테이너를 적극적으로 찾고 있습니다. 버그 수정, 가속기 지원 추가, 하위 시스템 전면 재설계 등 어떤 형태의 기여든 환영합니다. 오픈 모델이 더 나은 인프라를 갖추어야 한다고 생각하신다면, 함께 만들어 가시기 바랍니다.

가이드라인은 **[CONTRIBUTING.md](../../../CONTRIBUTING.md)**를 참조하십시오.

---

## 라이선스

[GNU Affero General Public License v3.0 (AGPL-3.0)](../../../LICENSE)에 따라 라이선스가 부여됩니다.
