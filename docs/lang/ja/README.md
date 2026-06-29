> **[English](../../../README.md)** | **[简体中文](../zh-CN/README.md)** | **日本語** | **[한국어](../ko/README.md)**

<p align="center">
  <img src="../../images/herodemo.gif" alt="ATLAS TUI 動作中"/><br/>
  <sub><i>ATLAS TUI のライブデモ（10倍速）。V3 パイプラインがファイル生成を実行中。</i></sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-V3.1.0-blue" alt="Version"/>
  <img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="License"/>
  <img src="https://img.shields.io/badge/model-agnostic-green" alt="Model-agnostic"/>
</p>

<h1 align="center">A.T.L.A.S.</h1>
<p align="center"><b>Adaptive Test-time Learning and Autonomous Specialization</b></p>

## ATLAS とは

ATLAS は、自分の GPU 上で動くコーディングアシスタントです。プロジェクトに向ければ、Claude や Copilot に頼むような作業（コードを読む、機能を書く、バグを直す）をこなします。モデルは自分のマシンから出ません。

ホスト型 AI ツールはどれも、サブスクリプション、プライバシーの妥協、そして存続を信じるしかないベンダーの三点セットです。ATLAS はそのどれでもありません。コードは自分のハードウェアに残ります。トークン課金もありません。プロジェクトが明日消えても、すでに入っているものはそのまま動き続けます。

オープンモデルは歴史的にホスト型に追いつけませんでした。ATLAS は推論スキャフォールディングの層でその差を埋めます。生成前にプランを立て、自分で生成したテストで答えを検証し、失敗を自分で修復します。14B リファレンスビルドは LiveCodeBench で 74.6% を記録しました。ATLAS は標準で 500 ドルの GPU に収まる 9B を走らせますが、特定モデルに縛られてはいません。

---

## 最新ニュース

- **2026-04-05** - **[V3.0.1 リリース](../../../CHANGELOG.md)** - インタラクティブ CLI、Docker Compose デプロイ、95.8% の信頼性
- **2026-04-03** - ["$500 GPU Beats Claude: Local AI Revolution for Web Devs"](https://ownet.it/blog/500-gpu-beats-claude-local-ai-revolution-for-web-devs) - ownet.it
- **2026-03-29** - ["A $500 GPU Just Outscored Claude Sonnet on Coding Benchmarks"](https://aivy.com.au/news/atlas-500-gpu-outperforms-claude-sonnet-coding/) - Aivy
- **2026-03-28** - ["Why a $500 GPU Can Beat Claude Sonnet on Coding Benchmarks"](https://medium.com/data-science-collective/why-a-500-gpu-can-beat-claude-sonnet-on-coding-benchmarks-6c8169ffe4fe) - Data Science Collective
- **2026-03-27** - ["ATLAS: A $500 GPU Outperforms Claude Sonnet"](https://clauday.com/article/b92c5551-b490-4d76-ae3d-d8dedf10d88b) - Clauday
- **2026-03-26** - [Hacker News フロントページ](https://news.ycombinator.com/item?id=47533297) - 489 ポイント、285 コメント
- **2026-03-05** - **[V3.0 リリース](../../reports/V3_ABLATION_STUDY.md)** - 凍結された Qwen3-14B で LiveCodeBench pass@1-v(k=3) 74.6%
- **2026-02-18** - **[V2.0 リリース](../../../CHANGELOG.md)** - ベンチマークインフラ、HumanEval/MBPP/LiveCodeBench/GPQA/SciCode 評価スイート

---

## ATLAS の機能

1. **[atlas-tui](../../CLI.md)** - ネイティブ Bubbletea ターミナル UI。公式チャットクライアント (PC-062)。任意のプロジェクトディレクトリで `atlas` と入力すれば起動します。
   - [ライブパイプライン表示](../../CLI.md#panes) - V3 ステージをサイドペインで監視
   - [スラッシュコマンド](../../CLI.md#slash-commands) - `/add`、`/diff`、`/commit`、`/run` でローカルファイルとシェルを操作
   - [入力モード](../../CLI.md#input-modes) - チャット、`!bash`、`/slash` をヒントドロップダウン付きで切り替え

2. **[atlas-proxy](../../ARCHITECTURE.md#3-atlas-proxy-outer-layer)** - システム全体を統括する Go 製エージェントループ。
   - [ツールコールルーティング](../../ARCHITECTURE.md#tools) - ファイル操作を複雑度ティアで分類
   - [文法強制](../../ARCHITECTURE.md#grammar-enforcement) - GBNF スキーマで JSON 出力の妥当性を担保
   - [BiasBusters](../../ARCHITECTURE.md#tool-selection-bias-mitigations-may-2026-biasbusters-synthesis) - ツール選択バイアス対策の四段構成（説明文、文法禁則、システムノート、ASA ステアリング）
   - [安全制限](../../ARCHITECTURE.md#safety-limits) - ターン上限、トークン予算、タイムアウト

3. **[V3 パイプライン](../../ARCHITECTURE.md#4-v3-pipeline-inner-layer)** - 単一のプロンプトを検証済み候補に変換するマルチフェーズコード生成。
   - [PlanSearch](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - 制約駆動の構造化プランニング
   - [DivSampling](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - 温度と戦略をまたぐ多様な候補生成
   - [Budget Forcing](../../reports/V3_ABLATION_STUDY.md#phase-1-constraint-driven-generation-124pp) - フェーズごとの思考トークン割り当て
   - [PR-CoT Repair](../../reports/V3_ABLATION_STUDY.md#pr-cot-repair-36-rescues) - 自己生成テストによる反復修正
   - [Refinement Loops](../../reports/V3_ABLATION_STUDY.md#refinement-loop-6-rescues) - サンドボックスでの検証と修正を繰り返す
   - [Derivation Chains](../../reports/V3_ABLATION_STUDY.md#derivation-chains-0-rescues) - 難問向けのマルチステップ推論

4. **[Geometric Lens](../../ARCHITECTURE.md#5-geometric-lens)** - モデル自身の埋め込み上で動くエネルギーベースのスコアリング。外部オラクル不要。(「[Geometric Lens とは?](../../ARCHITECTURE.md#why-geometric-lens)」)
   - [C(x) Cost Field](../../ARCHITECTURE.md#scoring-models) - 候補の品質をスコア化する hidden-dim→512→128→1 の MLP
   - [G(x) Quality Prediction](../../ARCHITECTURE.md#scoring-models) - 選択に用いる XGBoost アンサンブル
   - [RAG / PageIndex V2](../../ARCHITECTURE.md#rag--pageindex-v2) - AST 対応のコード検索とプロジェクトインデキシング
   - [Confidence Router](../../ARCHITECTURE.md#confidence-router--pattern-cache) - Thompson Sampling で必要な候補に計算を寄せる

5. **[Sandbox](../../ARCHITECTURE.md#6-sandbox)** - ビルド検証のための分離実行環境。
   - 多言語実行: Python、Rust、Go、C、Shell など
   - スコアリング前のコンパイルとリント
   - 生成テストと既存テストスイートの両方を実行

6. **[llama-server](../../CONFIGURATION.md#6-llama-server)** - 単一のコンシューマ GPU 上でのローカル LLM 推論。
   - GPU 加速の量子化推論 (Q6_K / Q4_K_M) — NVIDIA CUDA、AMD ROCm、Apple Metal (macOS ハイブリッド)、Vulkan に対応。Intel SYCL はロードマップ
   - トークンレベルの文法制約デコーディング
   - セルフ埋め込み（別モデル不要）

詳細ドキュメント（セットアップ、アーキテクチャ、設定、トラブルシューティング、ベンチマークレポート、各コンポーネントの[研究的背景](../../SOURCES.md)）は [docs/](../../) にあります。

---

## はじめに

ワンショットインストール:
```bash
curl -fsSL https://raw.githubusercontent.com/itigges22/ATLAS/main/scripts/atlas-bootstrap.sh | bash
```
ディストロ (Ubuntu、Debian、RHEL、Fedora、Rocky、Alma) と GPU ベンダー (NVIDIA → nvidia-container-toolkit; AMD → ROCm デバイスパススルー) を判定し、適切なランタイムをインストール、モデル重みをダウンロード、ASA ステアリングベクトルをビルドしてスタックを起動します。所要時間は 10〜30 分程度、ほとんどがモデルダウンロードです。

完了後、プロジェクトディレクトリで `atlas` を実行してください。

**要件**

| | |
|---|---|
| GPU | VRAM 16GB 以上。NVIDIA (CUDA)、AMD (ROCm)、または Apple Silicon (Metal、macOS ハイブリッド)。その他大半の GPU は Vulkan でカバー。[SETUP.md § Supported GPUs](../../SETUP.md#supported-gpus) を参照。 |
| ランタイム | Docker (NVIDIA: + nvidia-container-toolkit; AMD: 単体の Docker で十分) または Podman |
| Python | 3.9 以上 |
| ディスク | 約 20GB CUDA / 約 22GB ROCm (モデル重み + コンテナイメージ) |

Apple Silicon は macOS ハイブリッド Metal パス（ネイティブ llama-server + 残りは Docker — **[SETUP_MACOS.md](../../SETUP_MACOS.md)** を参照）でネイティブ動作します。Intel Arc (SYCL) はロードマップ上の項目です。Docker Compose、ベアメタル、K3s の手動インストール手順とブートストラップフラグの一覧は **[SETUP.md](../ja/SETUP.md)** をご参照ください。

---

## 既知の制限事項

- **Linux の Docker スタック、加えてネイティブ macOS パス。** NVIDIA、AMD ROCm、Vulkan の Docker パスは現在提供中です。Apple Silicon はネイティブ macOS ハイブリッド Metal パス ([#32](https://github.com/itigges22/ATLAS/issues/32)) で動作します。Intel Arc / SYCL はロードマップ上の項目です。
- **9B モデルはまだ正式にベンチマークされていません。** V3.1.0 は Qwen3.5-9B と完全な V3 パイプラインを同梱しますが、現在公開されている 74.6% LiveCodeBench スコアは 14B リファレンスビルドのものです。9B の正式数値は V3.1.1 で公開予定。14B のベンチ手法とアブレーションは [`docs/reports/V3_ABLATION_STUDY.md`](../../reports/V3_ABLATION_STUDY.md) に、生トレースは [HuggingFace](https://huggingface.co/datasets/itigges22/ATLAS) に公開しています。
- **複雑な機能追加は不安定なことがあります。** 不慣れなコードベースを探索しすぎてコードを書き始めないことがあります。9B ビルド上では V3.0 計測時より改善していますが、最新の数値は V3.1.1 のベンチで更新予定です。
- **文法制約デコーディングは遅め。** llama-server で約 51 tok/s。

---

## ロードマップ

**V3.1.0** - 現在のリリース。Bubbletea TUI を公式チャットクライアントに採用 (PC-062)、`atlas init` 初回セットアップウィザード (PC-054)、`atlas doctor` 診断ツール (PC-053)、`atlas tier` ハードウェア対応プリセット (PC-055)、K3s デプロイテンプレートの復元、インストール時に自動構築される ASA ステアリングベクトル (BiasBusters #4)。

**V3.1.1** - ハードウェア対応の拡大（`main` に着地済み）。
- llama.cpp 経由の AMD ROCm — RDNA4 / RX 9070 (gfx1200/gfx1201) およびコミュニティ検証済みカードを含む ([#26](https://github.com/itigges22/ATLAS/issues/26))。
- Apple Silicon — ネイティブ macOS ハイブリッド Metal パス: 推論性能のためにネイティブ llama-server を、スタックの残りには Docker を使用 ([#32](https://github.com/itigges22/ATLAS/issues/32)、[SETUP_MACOS.md](../../SETUP_MACOS.md) を参照)。
- Vulkan ユニバーサルフォールバック — AMD / Intel / Snapdragon / MoltenVK 経由の Apple / CPU を 1 つのイメージでカバー ([#114](https://github.com/itigges22/ATLAS/issues/114))。
- 9B 正式ベンチマーク — Qwen3.5-9B での LiveCodeBench、GPQA Diamond、SciCode（進行中、[#28](https://github.com/itigges22/ATLAS/issues/28)）。

**V3.1.2** - 次期ポイントリリース: 持ち込みモデル + クラスター。
- ASA のモデル別キャリブレーション同等化 ([#113](https://github.com/itigges22/ATLAS/issues/113)) とローカル Lens トレーニングパイプライン ([#100](https://github.com/itigges22/ATLAS/issues/100)) — デフォルト以外の GGUF 向けに ASA / Lens アーティファクトをトレーニング。
- 自動化された HuggingFace 投稿パイプライン ([#102](https://github.com/itigges22/ATLAS/issues/102))。
- K3s / Kubernetes 上の ROCm — Pod スペックでの `/dev/kfd` + `/dev/dri` の hostPath マウントと `render` / `video` グループ所属（`docker-compose.rocm.yml` のクラスター版に相当）。

**V3.2** - 次のマイルストーン: より深いコード推論とプランニング。
- アーキテクチャ優先のプランニングフェーズ — RPG スタイルのプラン先行・後埋め: モジュールスコープでプランを立ててから関数スコープで実装 ([#120](https://github.com/itigges22/ATLAS/issues/120))。
- 構造的コード推論 — tree-sitter による呼び出しグラフ + 到達可能性に加え、「どのファイルが重要か」を多解像度で検索する構文非依存のウェーブレット特徴分解 ([#39](https://github.com/itigges22/ATLAS/issues/39))。
- サンプリングを用いた推論 — 効率と品質の向上 ([#9](https://github.com/itigges22/ATLAS/issues/9))。

**バックログ / 協力者募集**
- ハードウェア: ARM64 マルチアーキテクチャビルド ([#115](https://github.com/itigges22/ATLAS/issues/115))、大規模モデル向けのマルチ GPU ([#34](https://github.com/itigges22/ATLAS/issues/34))、Intel oneAPI / SYCL ([#27](https://github.com/itigges22/ATLAS/issues/27))。
- ツール: VS Code / JetBrains 拡張機能 ([#35](https://github.com/itigges22/ATLAS/issues/35))。
- サンドボックス言語: Java / Kotlin ([#29](https://github.com/itigges22/ATLAS/issues/29))、Ruby / PHP ([#30](https://github.com/itigges22/ATLAS/issues/30))。
- アーキテクチャ: モデル非依存プラットフォーム ([#66](https://github.com/itigges22/ATLAS/issues/66))、Redis に代わる SQLite ([#57](https://github.com/itigges22/ATLAS/issues/57))。

---

## コントリビュート

ATLAS はオープンに開発されており、コントリビューターとコアメンテナーを積極的に募集しています。バグ修正、アクセラレータサポートの追加、サブシステム全体の再設計など、どの形の貢献も歓迎します。オープンモデルにはより良いインフラが必要だと考える方は、ぜひ一緒に開発しましょう。

ガイドラインは **[CONTRIBUTING.md](../../../CONTRIBUTING.md)** をご覧ください。

---

## ライセンス

[GNU Affero General Public License v3.0 (AGPL-3.0)](../../../LICENSE) の下でライセンスされています。
