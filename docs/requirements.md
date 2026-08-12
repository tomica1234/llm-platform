# GPUコーディングエージェント基盤 要件定義書

- 文書名: GPUコーディングエージェント基盤 要件定義書
- 版: 1.0
- 基準日: 2026-08-06
- 状態: 実装開始用ベースライン
- 想定利用者数: 通常2人、最大3人
- 想定GPU: 同一サーバー上のNVIDIA GPU 3枚
- 主用途: 複数ユーザーによるローカルLLMコーディングエージェント
- 主要推論ランタイム: llama.cpp、vLLM
- 例示モデル: DeepSeek V4 Flash（DVF）、Qwen 3.6 27B
- 注意: 例示モデルの量子化、必要RAM/VRAM、対応ランタイム、速度は導入時ベンチマークで確定し、コードへ固定しない。

---

## 0. 用語と要求レベル

本書では次の意味で用いる。

- **必須**: 初回本番運用までに満たす。
- **推奨**: 初回運用後の早い段階で満たす。未実装の場合は理由を記録する。
- **任意**: 将来拡張として実装できる。
- **モデル**: DVF、Qwenなどの論理的なモデル。
- **モデル成果物**: GGUF、safetensors、tokenizer、config、LoRAなどの実ファイル。
- **ランタイム**: llama.cpp、vLLM、将来のSGLang等。
- **デプロイメント**: 「モデル＋成果物＋ランタイム＋量子化＋GPU/RAM設定＋起動引数」の実行可能な組合せ。
- **プロファイル**: 同時に起動するデプロイメントとGPU配分をまとめた構成。
- **ハーネス**: リポジトリ調査、ファイル編集、shell/git/test実行、作業状態管理、モデル選定用メタデータ生成を行うコーディングエージェント。
- **推論ゲートウェイ**: 利用者に単一のOpenAI互換APIを提供し、認証・ルーティング・キュー・バックエンド転送を行うサーバー。
- **GPUオーケストレーター**: 必要なランタイムを起動・停止し、GPU配置を希望状態へ収束させる制御機能。
- **Slurm**: GPU、CPU、RAMの物理的な割当、隔離、待ち行列、会計を担当するジョブ管理基盤。

---

# 1. 背景

1台のGPUサーバーに3枚のGPUを搭載し、通常2人、最大3人がコーディングエージェントとして利用する。利用するモデルは処理ごとに異なり、実装、探索、設計、デバッグ、レビューなどの各段階で最適なモデルが変わる。

また、モデルごとに次の差がある。

- llama.cppでのみ現実的に動くGGUF・CPUオフロード中心のモデル
- vLLMで高いスループットを得やすいGPU常駐モデル
- 1GPUで動くモデル
- 2GPU＋CPUオフロードで動くモデル
- 3GPUを必要とするモデル
- 同じモデルを2人以上で共有した方が効率的なモデル
- tool calling、JSON schema、長文コンテキスト等の対応差

利用者が毎回モデル、ランタイム、GPU枚数、API接続先を選ぶ運用は避ける。通常はハーネスとゲートウェイが自動判断し、必要な場合のみ利用者が手動でモデルまたはランタイムを指定できるようにする。

---

# 2. 目的

本システムの目的は、利用者がGPU配置や推論ランタイムを意識せずにコーディングエージェントを利用できる基盤を構築することである。

## 2.1 達成目標

1. 利用者は原則として1つのコマンドまたは1つのOpenAI互換APIだけを使用する。
2. ハーネスは作業状況からタスク特性を自動抽出する。
3. モデルルーターは品質、速度、待ち時間、現在のGPU状態を考慮してモデルを選ぶ。
4. リソースプランナーはモデルに対応するllama.cpp／vLLMデプロイメントを選ぶ。
5. GPUオーケストレーターは必要に応じてモデルサーバーをdrain、停止、sleep、起動、再配置する。
6. 同じ大型モデルを複数人が必要とした場合、モデルを重複ロードせず1つのサーバーを共有する。
7. 自動選定に不満がある場合、モデル、ランタイム、デプロイメントを手動で優先または強制できる。
8. モデル重みは共有し、トークン、コンパイルキャッシュ、一時ファイル、ユーザー作業領域は分離する。
9. 各ユーザーのリポジトリ操作はそのユーザー権限で行い、中央サービスに全リポジトリへの書込権限を持たせない。
10. すべてのルーティング、GPU切替、失敗、利用量を後から検証できる。

## 2.2 成功条件

- 通常2人が同時に異なるモデルを利用できる。
- 2人の大型モデル要求が重なった場合、1つの3GPUデプロイメントへ自動集約できる。
- 3人目の要求が到着しても、先着順だけでなく公平な待ち行列で処理できる。
- llama.cppとvLLMを利用者操作なしに切り替えられる。
- 手動指定時は、自動ルーターが勝手に別モデルへ変更しない。
- 推論中の要求を失わず、要求境界でGPU構成を切り替えられる。
- サービス再起動後、永続状態からキューとデプロイメント状態を復旧できる。
- モデルまたはランタイムの更新失敗時に、直前の版へロールバックできる。

---

# 3. スコープ

## 3.1 対象

- ユーザーごとのコーディングエージェント・ハーネス
- OpenAI互換推論ゲートウェイ
- 自動モデルルーター
- 手動モデル／ランタイム指定
- デプロイメントレジストリ
- GPUリソースプランナー
- llama.cpp／vLLMランタイムアダプター
- SlurmによるGPU・CPU・RAM割当
- モデル共有ストア
- キュー、公平制御、同時実行制御
- ログ、メトリクス、監査
- 管理CLI
- バックアップ、更新、ロールバック
- コーディングツール実行の安全制御
- モデル選定結果の評価データ収集

## 3.2 初期スコープ外

- Kubernetes
- 複数計算ノード
- インターネットへ公開するSaaS
- 課金・請求
- 数十人以上の敵対的マルチテナント
- 推論途中のGPU枚数変更
- モデル切替時のゼロ秒再ロード
- すべてのOpenAI APIパラメータの完全互換
- 未登録モデルの利用者による無審査自動ダウンロード
- 人間の承認なしでのgit push、デプロイ、DB破壊的変更
- 学習型ルーターを初期版の唯一の判断手段にすること

---

# 4. 前提条件と信頼境界

## 4.1 ハードウェア前提

- NVIDIA GPU 3枚をSlurm GRESとして登録する。
- GPU型番とVRAMはインベントリから取得し、設定へ固定値を重複記載しない。
- システムRAMはOS、ファイルキャッシュ、CPUオフロード、KV cache、ランタイム用に予算化する。
- NVMe上にモデルストアとscratchを分離して配置する。
- 各デプロイメントは事前ベンチマークにより、必要GPU数、最大VRAM、最大RAM、起動時間、同時実行数を登録する。

## 4.2 利用者前提

- 通常2人、最大3人。
- 利用者は共同研究・共同開発者であり、完全に敵対的なテナントではない。
- 事故防止と情報分離は必須だが、強い敵対的隔離が必要になった場合は、別ログインノードまたはVM／コンテナ境界を追加する。
- 利用者はsudo権限を持たない。
- 管理者アカウント `firstuser` は日常の推論プロセスを実行しない。

## 4.3 ネットワーク前提

- 初期運用は同一LANまたはVPN内に限定する。
- 推論バックエンドは原則 `127.0.0.1` またはUnix socketへbindする。
- 外部から到達可能なのは推論ゲートウェイのみとする。
- LAN外へ公開する場合はTLS、アクセス制御、IP制限を必須とする。

---

# 5. 利用者とサービスアカウント

| 主体 | 役割 | sudo | SSH | GPU直接利用 |
|---|---|---:|---:|---:|
| `firstuser` | OS、ドライバー、Slurm、サービス更新・復旧 | あり | あり | 原則しない |
| 一般ユーザー | ハーネス、リポジトリ、Slurmジョブ利用 | なし | あり | Slurm経由のみ |
| `svc-control` | ゲートウェイ、ルーター、キュー、オーケストレーター | なし | 不可 | 原則なし |
| `svc-llm` | llama.cpp、vLLMバックエンド | なし | 不可 | Slurm割当内のみ |
| `svc-models` | モデルの取得、検証、登録 | なし | 不可 | 変換時のみSlurm経由 |

小規模な初期構築では `svc-control` と `svc-llm` を1つの `svc-llm` にまとめてもよい。ただし、コード上の権限境界とディレクトリは分離し、将来分割できる構造にする。

---

# 6. 全体アーキテクチャ

```text
┌─────────────────────────────────────────────────────────────┐
│ ユーザーA/B/CのLinuxアカウント                              │
│                                                             │
│  Agent Harness                                              │
│  ├─ リポジトリ調査                                          │
│  ├─ file/shell/git/test ツール                               │
│  ├─ タスク段階・リスク・コンテキスト量の抽出                 │
│  ├─ 手動モデル指定                                          │
│  └─ 作業状態保存                                             │
└─────────────────────┬───────────────────────────────────────┘
                      │ OpenAI互換API
                      │ model=auto / prefer/... / force/...
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Inference Gateway / Control Plane                           │
│  ├─ 認証・レート制限                                        │
│  ├─ OpenAI互換API正規化                                     │
│  ├─ Model Router                                            │
│  ├─ Request Queue                                           │
│  ├─ Resource Planner                                        │
│  ├─ Desired-State Reconciler                                │
│  ├─ Runtime Adapters                                        │
│  └─ 利用記録・監査                                          │
└─────────────────────┬───────────────────────────────────────┘
                      │ Slurm API/CLI
                      ▼
┌─────────────────────────────────────────────────────────────┐
│ Slurm                                                       │
│  ├─ llama.cpp backend job                                   │
│  ├─ vLLM backend job                                        │
│  ├─ user batch job                                          │
│  └─ GPU/CPU/RAM/cgroup/accounting                            │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
              GPU 0 / GPU 1 / GPU 2
```

## 6.1 分離原則

- **データ面**: OpenAI互換APIの推論要求とストリーミング応答。
- **制御面**: モデル選定、キュー、ランタイム起動停止、GPU再配置。
- **ツール実行面**: 各ユーザーのハーネスがそのユーザー権限でfile/shell/git/testを実行。
- 中央ゲートウェイは原則としてユーザーリポジトリを直接編集しない。
- バックエンドAPIキーはモデル選択子として使用しない。モデル選択は論理ID／デプロイメントIDで行い、APIキーは認証専用とする。

---

# 7. 標準処理フロー

1. 利用者が対象リポジトリで `agent` を起動する。
2. ハーネスがユーザー要求、git状態、変更ファイル、テスト結果、過去の失敗を確認する。
3. ハーネスがタスク特徴量を生成する。
4. ハーネスがゲートウェイへ `model=auto` と特徴量を送る。
5. ゲートウェイがユーザーを認証する。
6. モデルルーターが利用可能なモデル候補を順位付けする。
7. リソースプランナーが、現在ロード済みのモデル、GPU空き、キュー、切替コストを含めてデプロイメントを決定する。
8. 必要なバックエンドが稼働中なら即時転送する。
9. 稼働していなければ、要求をキューへ置き、希望プロファイルを作成する。
10. オーケストレーターが既存バックエンドをdrainする。
11. Slurmジョブを停止／起動し、必要なGPU数を確保する。
12. health checkとwarmupが成功した後、要求をバックエンドへ転送する。
13. 応答を利用者へストリーミングする。
14. ハーネスがtool callを各ユーザー権限で実行する。
15. テスト結果や差分を次の推論要求の特徴量へ反映する。
16. ルーティング結果、待ち時間、推論時間、テスト成否を記録する。
17. アイドル時間を超えた場合、オーケストレーターが通常プロファイルへ戻す。

---

# 8. コーディング・ハーネス要件

## 8.1 実行位置

- ハーネスは各一般ユーザーの権限で動作する。
- 開発版リポジトリは各ユーザーのホーム以下に置いてよい。
- 本番CLIは `/opt/agent-harness/releases/<version>` に配置し、`/usr/local/bin/agent` から起動できるようにする。
- ユーザー固有状態は `~/.local/share/agent-harness`、設定は `~/.config/agent-harness`、一時領域は `/scratch/$USER/agent-harness` に置く。

## 8.2 タスク段階

ハーネスは少なくとも次の段階を内部状態として持つ。

```text
DISCOVER
→ PLAN
→ IMPLEMENT
→ TEST
→ DEBUG
→ REVIEW
→ FINALIZE
```

利用者が「レビュー」「実装」と明示する必要はない。以下のイベントから段階を推定する。

- まだ対象ファイルが不明: DISCOVER
- 実装方針と変更対象が確定: PLAN
- ファイル変更中: IMPLEMENT
- テスト実行中: TEST
- テスト失敗または再現不能: DEBUG
- 差分が存在し主要テストが通過: REVIEW
- 指摘解消、差分とテスト結果確定: FINALIZE

## 8.3 タスク特徴量

ハーネスは次をゲートウェイへ送信できること。

- タスク種別の推定
- 現在の段階
- 変更予定／変更済みファイル数
- 推定差分行数
- 対象言語・フレームワーク
- リポジトリ規模
- コンテキスト推定トークン数
- tool calling必須か
- JSON schema必須か
- テスト失敗回数
- 同じ失敗の繰返し回数
- セキュリティ／認証／権限／決済／削除／DB migration等の高リスク判定
- 直前のモデル
- 直前のモデルの失敗理由
- 望ましい速度／品質ポリシー
- 利用者の手動指定
- タスクの締切または最大待ち時間
- 機密性ラベル

原文コード全体をルーター専用ログへ保存してはならない。特徴量と必要最小限の要約のみを中央へ渡す。

## 8.4 ツール

必須ツール:

- ファイル一覧・検索
- ファイル読取
- パッチ適用
- shell command
- git status/diff/log
- lint
- type check
- unit/integration test
- build
- テスト結果解析

推奨ツール:

- 言語サーバー
- AST検索
- 依存関係グラフ
- coverage
- セキュリティスキャン
- ブラウザ／HTTPテスト
- GitHub連携

## 8.5 ツール安全制御

- 読取操作は自動実行可能とする。
- 作業ディレクトリ内の編集、テスト、ビルドはポリシーにより自動実行可能とする。
- `sudo`、OS設定変更、ユーザー管理、ディスク初期化、秘密鍵読取、任意の外部送信は拒否または明示確認を必須とする。
- `git push`、本番デプロイ、破壊的migration、データ削除は明示確認を必須とする。
- ハーネスは許可されたworkspace外へ書き込まない。
- 推奨既定は、タスクごとにgit worktreeを `/scratch/$USER/agent-worktrees/<task-id>` に作る。
- in-place編集は利用者が明示した場合のみ許可する。
- tool callと終了コードをユーザー側へ記録する。
- モデル出力だけで安全ポリシーを無効化できない。

## 8.6 作業状態

タスクごとに次を保存する。

- task_id
- 利用者
- リポジトリとcommit
- ユーザー要求
- 現在段階
- 計画
- 読み込んだファイル一覧
- 適用パッチ
- git diff
- テスト履歴
- 未解決事項
- 使用モデル／ランタイム
- ルーティング理由
- 推論要求ID
- 人間の承認／却下
- 終了状態

モデルサーバー再起動やモデル切替でこの状態を失ってはならない。

## 8.7 失敗時の昇格

次のいずれかを検出した場合、より高品質な候補へ自動昇格できること。

- 同じテスト失敗が2回以上
- 無効なtool callが連続
- パッチが適用不能
- 変更がループしている
- 予定ステップ数を超過
- セキュリティ高リスク
- 最終レビューで重大指摘
- 利用者が「強いモデルへ」と要求

昇格回数、最大ステップ、最大トークン、最大実行時間は設定可能とする。

## 8.8 モデル多様性

高リスク変更では、実装と最終レビューに異なるモデル系列を使用するポリシーを設定可能とする。利用可能な別系列がない場合は、同一モデルで独立コンテキストの再レビューを行い、その事実を表示する。

---

# 9. 推論ゲートウェイ要件

## 9.1 公開API

必須:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- ストリーミング
- Bearer API key認証
- request ID
- タイムアウト
- キャンセル
- usage情報
- health endpoint
- metrics endpoint

推奨:

- embeddings
- rerank
- batch requests
- Anthropic Messages互換
- 管理用status API

ゲートウェイが保証する互換範囲は文書化し、バックエンド固有機能との差を正規化する。対応できないパラメータは黙って無視せず、対応デプロイメントへ限定するか明示エラーを返す。

## 9.2 仮想モデル名

利用者・既存クライアントは次を指定できる。

```text
auto
fast
balanced
strong
max
auto/fast
auto/balanced
auto/strong
auto/max
prefer/<logical-model>
force/<logical-model>
force/<logical-model>@<runtime>
force-deployment/<deployment-id>
```

意味:

- `auto`: balanced を基準とし、実行時状態、失敗回数、リスク、キュー、負荷を加味する自動選択。
- `fast`: 低遅延、低待ち時間、ロード済み、低リソースを強く優先。
- `balanced`: 品質と速度の標準的なトレードオフ。
- `strong`: 品質優先。ただし遅延とリソースコストも考慮する。
- `max`: 最高品質を最優先し、起動、遅延、リソースのペナルティを弱くする。
- `auto/<policy>`: 対応する `fast`、`balanced`、`strong`、`max` ポリシー。
- `quality` と `auto/quality`: 後方互換のため `strong` として解釈する非推奨エイリアス。
- `prefer`: 指定を優先するが、設定された最大待ち時間を超える場合は代替可能。
- `force`: 指定モデル以外へ変更しない。利用不可なら待機または明示エラー。
- `force-deployment`: モデル、ランタイム、量子化、GPUプロファイルまで固定。

## 9.3 追加メタデータ

標準OpenAIクライアントとの互換性を保つため、拡張情報はHTTP headerまたは別のルーティングエンドポイントで渡す。

例:

```text
X-Agent-Task-ID
X-Agent-Phase
X-Agent-Priority
X-Agent-Risk
X-Agent-Context-Tokens
X-Agent-Deadline-Ms
X-Agent-Previous-Model
X-Agent-Failure-Count
```

リポジトリの秘密情報やAPIキーをheaderへ含めない。

## 9.4 応答メタデータ

デバッグ権限を持つ利用者には次をheaderまたはusage拡張で返す。

```text
X-Selected-Logical-Model
X-Selected-Runtime
X-Selected-Deployment
X-Route-Mode
X-Queue-Wait-Ms
X-Backend-Load-Ms
X-Request-ID
```

ルーティング理由の詳細は、一般利用者には要約、管理者には完全なreason codeを表示する。

## 9.5 認証・認可

- 利用者ごとに異なるゲートウェイAPIキーを発行する。
- APIキーはハッシュ化して保存する。
- キーには利用可能モデル、最大同時要求、優先度、日次上限を関連付ける。
- バックエンド用内部キーを利用者へ渡さない。
- バックエンドAPIはloopbackからのみ受け付ける。
- キーの失効・ローテーションを無停止で行えること。
- 管理APIは一般APIキーで利用できないこと。

## 9.6 エラー

少なくとも次を区別する。

- 400: 不正な要求、非対応パラメータ
- 401: 認証失敗
- 403: モデル／機能権限なし
- 409: 強制デプロイメントと現在の保護ジョブが競合
- 429: 同時実行またはレート上限
- 499相当: クライアントキャンセル
- 503: 利用可能なデプロイメントなし
- 504: 利用者の最大待ち時間超過

エラーには `request_id` と再試行可能性を含める。

---

# 10. モデルルーター要件

## 10.1 二段階選定

モデル選定と実際のデプロイメント選定を分離する。

1. **Model Router**
   - このタスクに適した論理モデル候補を順位付けする。
2. **Resource Planner**
   - 各論理モデルの利用可能デプロイメントから、現在のGPU状態を考慮して実行先を決める。

## 10.2 ハード制約

スコア計算前に次を満たさない候補を除外する。

- モデル成果物が登録済み
- ランタイムがモデルアーキテクチャに対応
- 必要コンテキスト長を満たす
- tool calling要件を満たす
- structured output要件を満たす
- 必要な画像／音声入力要件を満たす
- GPU数、VRAM、RAM上限内
- 利用者に権限がある
- 機密性ポリシーを満たす
- 手動force条件を満たす
- デプロイメントが有効化されている
- 既知の致命的不具合がない

## 10.3 ソフトスコア

初期版の概念式:

```text
score =
  quality_weight       × predicted_success
- latency_weight       × predicted_latency
- wait_weight          × predicted_queue_wait
- switch_weight        × backend_switch_cost
- resource_weight      × gpu_ram_cost
+ loaded_bonus         × already_loaded
+ batching_bonus       × same_model_batch_opportunity
+ continuity_bonus     × session_model_stickiness
+ diversity_bonus      × independent_review_value
```

重みは `fast`、`balanced`、`strong`、`max` ごとに変える。

## 10.4 初期ルーター

初期版はルール＋統計ベースとする。LLMルーターは補助に留める。

ルール例:

- 小規模な単一ファイル修正: 軽量または高速モデル優先
- 複数ファイル設計: 高品質モデル候補を上げる
- テスト失敗2回以上: 高品質モデルへ昇格
- 高リスク領域: 最終レビューを高品質モデルで必須化
- 既に十分なモデルがロード済み: 小さな品質差なら切り替えない
- 同一大型モデル要求が複数待機: 共有3GPUデプロイメントの価値を上げる

## 10.5 学習型ルーター

将来、次の実績から成功確率と所要時間を学習できること。

- タスク特徴量
- 選択モデル／ランタイム
- テスト成功
- 修正回数
- 人間採用率
- レビュー指摘数
- 推論時間
- 待ち時間
- ループ／昇格の有無
- 最終的に成功したモデル

学習型ルーター導入後も、ハード制約、手動force、安全ポリシーはルーターより優先する。

## 10.6 説明可能性

各判断にreason codeを残す。

例:

```text
MANUAL_FORCE
MODEL_ALREADY_LOADED
BEST_PREDICTED_SUCCESS
LOWEST_EXPECTED_COMPLETION_TIME
BATCH_WITH_EXISTING_REQUEST
ESCALATED_AFTER_TEST_FAILURE
HIGH_RISK_FINAL_REVIEW
FALLBACK_DUE_TO_NO_CAPACITY
RUNTIME_INCOMPATIBLE
CONTEXT_TOO_LONG
```

---

# 11. デプロイメントレジストリ要件

## 11.1 論理モデル

論理モデルは次を持つ。

- `model_id`
- 表示名
- モデル系列
- revision
- license
- 用途タグ
- 対応コンテキスト長
- tool calling能力
- structured output能力
- multimodal能力
- 品質評価
- 有効／無効
- 既知の制約

## 11.2 デプロイメント

デプロイメントは次を持つ。

- `deployment_id`
- `model_id`
- `runtime_id`
- model path
- tokenizer path
- quantization
- executable/container image
- runtime version
- GPU数
- CPU数
- RAM予約
- VRAM見積
- context上限
- 最大同時要求
- tensor/pipeline parallel設定
- CPU offload設定
- 起動引数
- 環境変数
- listen port
- health check
- metrics endpoint
- 起動時間実測
- 単独tok/s
- 2要求同時tok/s
- 有効／無効
- benchmark revision

## 11.3 例

```yaml
models:
  dvf:
    display_name: DeepSeek V4 Flash
    family: deepseek
    capabilities:
      tool_calling: true
      structured_output: tested
      max_context: 32768

  qwen-main:
    display_name: Qwen 3.6 27B
    family: qwen
    capabilities:
      tool_calling: true
      structured_output: tested
      max_context: 32768

deployments:
  dvf-llama-2gpu:
    model: dvf
    runtime: llama_cpp
    artifact: /srv/models/gguf/dvf/<revision>/model.gguf
    resources:
      gpus: 2
      cpus: 16
      ram_gb: 96
    serving:
      concurrency: 1

  dvf-llama-3gpu-shared:
    model: dvf
    runtime: llama_cpp
    artifact: /srv/models/gguf/dvf/<revision>/model.gguf
    resources:
      gpus: 3
      cpus: 20
      ram_gb: 96
    serving:
      concurrency: 2

  qwen-vllm-1gpu:
    model: qwen-main
    runtime: vllm
    artifact: /srv/models/hf/qwen-main/<revision>
    resources:
      gpus: 1
      cpus: 8
      ram_gb: 24
    serving:
      concurrency: 2
```

上記数値は例であり、ベンチマーク未実施のまま本番有効化してはならない。

---

# 12. GPUリソースプランナー要件

## 12.1 基本原則

- GPUは特定ユーザーへ固定しない。
- 同じモデルを複数ユーザーが要求した場合、原則として1つのバックエンドを共有する。
- モデル重みをユーザー数分重複ロードしない。
- 推論中にGPU枚数を変更しない。
- GPU構成変更は要求境界で行う。
- GPU番号を設定へ固定せず、Slurm割当と `CUDA_VISIBLE_DEVICES` に従う。
- RAM不足でOSが不安定になる構成を許可しない。
- 1つの大型要求が他の利用者を恒久的に飢餓状態にしない。

## 12.2 代表プロファイル

### Balanced

```text
大型モデル: 2GPU
実装用モデル: 1GPU
```

用途:

- Aが大型モデル、Bが実装用モデル
- 通常時の既定候補

### Strong Shared

```text
大型モデル1インスタンス: 3GPU
concurrency: 2または3
```

用途:

- 2人以上の大型モデル要求が重なった
- 実装用モデル要求がない、または待機可能

### Implementation Burst

```text
実装用モデル: 1〜2GPU
補助モデル: 残りGPU
```

用途:

- 複数実装タスク
- 大型レビュー要求なし

### Idle / Cold

```text
モデル停止、または小型モデルのみ
```

用途:

- 長時間アイドル
- 消費電力削減
- バッチジョブへGPU返却

### Maintenance

```text
すべての推論バックエンド停止
```

用途:

- ドライバー／CUDA／ランタイム更新
- GPU診断
- モデル変換

## 12.3 プロファイル選択

次を比較する。

- 待機要求のモデル候補
- 各要求の優先度
- 各利用者の待ち時間
- 現在のバックエンド
- 実行中要求
- バックエンド切替時間
- モデルロード時間
- 同時バッチの効果
- RAM／VRAM上限
- Slurm上の他ジョブ
- 手動force
- 最大待ち時間

## 12.4 スラッシング防止

既定値は設定可能とし、初期推奨は次とする。

```yaml
scheduler:
  reconcile_interval_seconds: 2
  same_model_coalesce_window_seconds: 2
  minimum_profile_dwell_seconds: 120
  rebalance_idle_seconds: 90
  drain_timeout_seconds: 300
  backend_health_timeout_seconds: 30
  max_switches_per_10_minutes: 3
```

切替による期待短縮時間がロードコストより小さい場合は、現在のプロファイルを維持する。

## 12.5 状態遷移

```text
STOPPED
  ↓ start
ALLOCATING
  ↓ Slurm allocation
STARTING
  ↓ process launch
WARMING
  ↓ health + test request
READY
  ↓ stop accepting new requests
DRAINING
  ↓ active requests = 0
SLEEPING または STOPPING
  ↓
STOPPED
```

異常状態:

```text
FAILED
DEGRADED
ORPHANED
TIMEOUT
```

Reconcilerは現在状態と希望状態との差分を見て、繰返し実行しても同じ結果になる冪等処理を行う。

## 12.6 要求中の切替

- ストリーミング中の要求を通常のプロファイル切替で中断しない。
- 新規要求受付を止めてdrainする。
- drain timeout超過時は、管理ポリシーに従い継続待機、要求キャンセル、現在プロファイル維持のいずれかを選ぶ。
- 緊急停止は管理者のみ実行可能とし、影響するrequest IDを表示する。

---

# 13. キュー・同時利用要件

## 13.1 キュー分類

- `interactive`: 人間が待っているエージェントステップ
- `agent`: 自律ループ中の通常ステップ
- `background`: 評価、インデックス、長時間生成
- `maintenance`: 管理者専用

優先順は設定可能だが、backgroundが永久に実行されない状態を防ぐ。

## 13.2 公平性

- 通常はユーザーごとに同じshareを持つ。
- 1ユーザーが大量に要求を積んでも、他のユーザーの先頭要求を追い越し続けない。
- 既定では1ユーザー1本のinteractive生成を優先し、空きスロットがあれば2本目を許可する。
- 最大3ユーザーを同時に管理できる。
- 同じデプロイメントを待つ要求は短いcoalesce windowでまとめられる。
- 手動forceはモデル選択を固定するが、他ユーザーを無期限に追い越す権利は与えない。
- 管理者は一時的な優先度変更ができる。

## 13.3 キュー表示

利用者は次を確認できる。

- 自分のrequest ID
- 待機／割当／ロード中／実行中
- 選択予定モデル
- 手動指定状態
- 自分より前の要求数
- backend切替中か
- キャンセル可否

他ユーザーのプロンプト、リポジトリ名、コード内容は表示しない。

## 13.4 キャンセル

- 待機中要求は即時キャンセルできる。
- 実行中要求はバックエンドへキャンセルを伝播する。
- クライアント切断時の自動キャンセル有無を設定できる。
- 共有バッチ内の1要求キャンセルで他要求を停止しない。

---

# 14. 推論ランタイム要件

## 14.1 共通Runtime Adapter

```python
class RuntimeAdapter:
    async def validate(self, deployment): ...
    async def start(self, deployment, allocation): ...
    async def health(self, instance): ...
    async def warmup(self, instance): ...
    async def drain(self, instance): ...
    async def sleep(self, instance, level=None): ...
    async def wake(self, instance): ...
    async def stop(self, instance): ...
    async def metrics(self, instance): ...
    async def cancel(self, request_id): ...
```

Adapterはランタイム固有差をゲートウェイから隠蔽する。

## 14.2 llama.cpp Adapter

必須:

- GGUF成果物
- CPUオフロード設定
- 複数GPU設定
- OpenAI互換Chat Completions／Responses
- streaming
- tool calling設定
- chat template設定
- `--parallel`
- continuous batching
- health
- metrics
- graceful stop
- model alias
- 起動引数のrevision管理

推奨:

- llama-server router mode
- model load/unload API
- idle sleep
- speculative decoding
- LoRA切替

ただし、GPU枚数、split、CPU offload、context等が異なるプロファイルへ変更する場合は、同一プロセス内の単純load/unloadに固執せず、プロセス再起動を許容する。

## 14.3 vLLM Adapter

必須:

- Hugging Face形式または対応量子化成果物
- OpenAI互換Chat Completions／Responses
- streaming
- tool calling/parser設定
- tensor parallel設定
- GPU memory utilization設定
- context上限
- health
- Prometheus metrics
- graceful stop
- request cancellation
- 起動引数のrevision管理

推奨:

- sleep/wake
- prefix caching
- LoRA
- structured output
- speculative decoding

vLLMの制御用開発endpointを利用する場合、一般利用者へ公開せずloopback限定とする。sleep level 1でCPU RAMへ重みを保持する場合、システムRAM予算を超えないことを事前に検証する。

## 14.4 共通API正規化

ランタイム差に対して次を正規化する。

- model ID
- finish reason
- tool call形式
- reasoning出力の扱い
- usage
- streaming event
- error形式
- request ID
- structured output
- unsupported parameter

共通機能でないものはデプロイメントcapabilityとして登録する。

## 14.5 将来拡張

新しいランタイムはRuntime Adapterとデプロイメント定義の追加だけで導入可能とする。ルーター、ハーネス、ユーザーAPIへランタイム固有コードを散在させない。

---

# 15. Slurm要件

## 15.1 役割

Slurmは次を担当する。

- GPU GRES割当
- CPU、RAM割当
- cgroupによるジョブ隔離
- ジョブ待ち行列
- 優先度／QOS
- ジョブ会計
- ユーザーバッチ処理との競合管理

OpenAI API要求1件ごとにSlurmジョブを作らない。バックエンドインスタンス単位でSlurmジョブを起動し、その中で複数要求を処理する。

## 15.2 バックエンド起動方式

- `svc-control` が希望デプロイメントを決める。
- `svc-llm` 名義のSlurmジョブとしてバックエンドを起動する。
- ジョブは必要GPU数、CPU、RAMを明示する。
- Slurmが割り当てたGPUだけを利用する。
- バックエンドは自分に割り当てられていないGPUへアクセスしない。
- job IDとbackend instance IDをDBで関連付ける。
- orphan processを検出して終了する。

## 15.3 QOS

初期推奨:

| QOS | 用途 | 性質 |
|---|---|---|
| `agent-service` | 推論バックエンド | interactive、長時間 |
| `user-interactive` | 利用者の短いGPU実験 | 1GPU、短時間 |
| `batch` | 通常学習・評価 | 非プリエンプト既定 |
| `opportunistic` | 空きGPU利用 | requeue／preempt可能 |
| `maintenance` | 管理・診断 | 管理者限定 |

## 15.4 推論とバッチの競合

- 空きGPUがある場合は共存する。
- `opportunistic` ジョブはagent需要でrequeue可能とする。
- 非プリエンプトbatchジョブの実行中は、agent要求を待機または別モデルへフォールバックする。
- 通常のプロファイル切替のために、チェックポイント不能な利用者ジョブを強制終了しない。
- 管理者はメンテナンス予約を設定できる。
- バッチジョブを優先する時間帯、agentを優先する時間帯を設定可能とする。

## 15.5 cgroup

必須:

- cgroup v2
- GPU device制限
- CPU制限
- RAM制限
- swap方針
- ジョブ終了時プロセス回収

同一ノードをlogin兼computeとして利用する初期構成では、利用者は信頼された共同利用者とする。Slurm外GPU利用の強制防止をさらに強める場合は、別login node、PAM連携、またはユーザーセッション分離を追加する。

## 15.6 会計

少なくとも次を記録する。

- job ID
- user/service account
- QOS
- GPU枚数
- CPU/RAM
- 開始／終了
- exit code
- elapsed
- model/deployment ID
- backend instance ID
- GPU時間

Slurm会計とゲートウェイ要求ログをrequest ID／backend instance IDで相関できるようにする。

---

# 16. モデルストア・キャッシュ要件

## 16.1 ディレクトリ

```text
/srv/models/
├── gguf/
├── hf/
├── adapters/
├── draft/
├── embeddings/
├── rerankers/
└── manifests/

/srv/cache/
└── huggingface/
    └── hub/

/scratch/svc-llm/
├── vllm/
├── triton/
├── torch/
├── llama/
└── tmp/

/scratch/$USER/
├── agent-harness/
├── agent-worktrees/
└── user-cache/
```

## 16.2 所有権

```text
/srv/models
  owner: svc-models
  group: modelusers
  svc-llm: read-only
  general users: read-onlyまたは必要モデルのみread

/srv/cache/huggingface/hub
  owner: svc-models
  service consumers: read-only

/scratch/svc-llm
  owner: svc-llm
  mode: 700

/scratch/$USER
  owner: each user
  mode: 700
```

## 16.3 共有対象

共有する:

- model weights
- tokenizer
- config
- GGUF
- 公開LoRA
- draft model
- revision manifest
- checksum
- license metadata

共有しない:

- 個人Hugging Face token
- API key
- ユーザー固有Triton cache
- ユーザー固有vLLM cache
- 作業リポジトリ
- 独自データセット
- 個人LoRA
- prompt履歴

`HF_HOME` はtokenとcacheの両方を含み得るため、全利用者で同じ書込可能な `HF_HOME` を共有しない。共有する場合は管理された `HF_HUB_CACHE` または固定snapshotをread-onlyで提供する。

## 16.4 モデル登録

モデル追加手順:

1. 管理者または `svc-models` がrevisionを固定して取得。
2. checksumを記録。
3. licenseと利用条件を確認。
4. malware／異常ファイル検査。
5. 1GPU、2GPU、3GPU候補をベンチ。
6. tool call、structured output、長文、同時要求を検証。
7. manifestを作成。
8. デプロイメントをdisabledで登録。
9. acceptance benchmark通過後にenabledへ変更。
10. 既定ルーティングへ追加。

利用者がAPI要求を送っただけで未知のモデルを自動ダウンロードしてはならない。

## 16.5 ガベージコレクション

- 未使用成果物を自動削除する前に参照デプロイメントを確認する。
- `current` のような可変リンクだけでrevisionを管理せず、実体revisionをDBへ保存する。
- publicモデルは再取得可能でも、量子化済み成果物、独自LoRA、benchmark、manifestはバックアップする。
- ディスク残量が閾値を下回った場合、新規モデル取得を停止する。

---

# 17. 配置要件

## 17.1 本番配置

```text
/opt/llm-platform/
├── gateway/
│   ├── releases/
│   └── current
├── harness/
│   ├── releases/
│   └── current
└── runtimes/
    ├── llama.cpp/
    │   ├── releases/
    │   └── current
    └── vllm/
        ├── envs/
        └── current

/etc/llm-platform/
├── platform.yaml
├── models.yaml
├── deployments.yaml
├── routing.yaml
├── gpu-profiles.yaml
├── users.yaml
└── secrets.env

/var/lib/llm-platform/
├── database/
├── state/
├── locks/
└── runtime-state/

/var/log/llm-platform/

/srv/models/

/scratch/svc-llm/
```

## 17.2 所有権

- `/opt/llm-platform`: `root:root`、サービスはread/executeのみ。
- `/etc/llm-platform`: `root:svc-control`、秘密情報は640以下。
- `/var/lib/llm-platform`: `svc-control:svc-control`。
- `/var/log/llm-platform`: サービスごとに分離。
- `/srv/models`: `svc-models:modelusers`。
- `/scratch/svc-llm`: `svc-llm:svc-llm`。

## 17.3 `firstuser` の役割

`firstuser` のホームに本番ランタイムや本番ハーネスを置かない。

`firstuser` が行うこと:

- インストール
- 新版のビルド
- テスト
- `/opt` へのデプロイ
- symlink切替
- systemd再起動
- ロールバック
- 障害復旧

本番プロセスは `svc-control`／`svc-llm` で実行する。

---

# 18. 永続データモデル

初期推奨DBはPostgreSQL。単一プロセスMVPでSQLiteを使う場合も、将来移行できるRepository層を設ける。

## 18.1 主テーブル

### users

- id
- linux_username
- display_name
- status
- default_policy
- max_concurrency
- model_permissions
- created_at

### api_keys

- id
- user_id
- key_hash
- scopes
- expires_at
- last_used_at
- revoked_at

### agent_runs

- id
- user_id
- repository_hash
- initial_commit
- status
- policy
- created_at
- completed_at

### agent_steps

- id
- run_id
- phase
- task_features
- selected_model
- selected_runtime
- outcome
- created_at

### inference_requests

- id
- user_id
- run_id
- mode
- requested_model
- selected_deployment
- priority
- state
- queued_at
- started_at
- completed_at
- prompt_tokens
- output_tokens
- error_code

### route_decisions

- id
- request_id
- config_revision
- candidate_scores
- hard_filter_reasons
- selected_deployment
- reason_codes

### models

- id
- family
- revision
- capabilities
- license
- enabled

### model_artifacts

- id
- model_id
- format
- path
- checksum
- size_bytes
- created_at

### deployments

- id
- model_id
- runtime
- profile
- config
- benchmark_id
- enabled

### backend_instances

- id
- deployment_id
- slurm_job_id
- state
- port
- started_at
- stopped_at
- failure_reason

### gpu_profiles

- id
- name
- desired_deployments
- config_revision

### benchmarks

- id
- deployment_id
- hardware_revision
- runtime_revision
- startup_seconds
- prompt_tps
- generation_tps
- concurrent_tps
- max_vram
- max_ram
- quality_metrics

### audit_events

- id
- actor
- action
- target
- before
- after
- timestamp

## 18.2 プロンプト保存

- 中央DBへprompt本文、コード本文、diff全文を既定で保存しない。
- 保存するのはtoken数、hash、サイズ、task feature、結果メタデータ。
- 明示的なdebug modeでのみ本文保存を許可し、保存期間と閲覧権限を限定する。
- ユーザー側のハーネス履歴はそのユーザーだけが読める。

---

# 19. 監視・ログ要件

## 19.1 メトリクス

GPU:

- 使用率
- VRAM使用量
- 温度
- 消費電力
- クロック
- throttle
- Xid／driver error

ホスト:

- CPU
- RAM
- swap
- load average
- NVMe空き容量
- NVMe温度
- I/O
- ネットワーク

バックエンド:

- state
- health
- active requests
- queued requests
- prompt tok/s
- generation tok/s
- context使用量
- KV cache使用量
- error count
- startup time
- restart count

ゲートウェイ:

- request rate
- p50/p95待ち時間
- p50/p95推論時間
- route decision時間
- model/runtimes別利用数
- fallback数
- manual force数
- profile switch数
- cancellation数

ハーネス品質:

- test pass率
- 1回で完了した割合
- 昇格率
- review指摘数
- human accept率
- model別成功率

## 19.2 ログ

必須ログ:

- gateway access log
- route decision log
- scheduler transition log
- backend stdout/stderr
- Slurm job ID
- admin action
- model registry変更
- authentication failure
- tool execution summary

禁止:

- APIキー平文
- Hugging Face token
- SSH秘密鍵
- prompt本文の既定保存
- ユーザー間で見えるコード内容

## 19.3 アラート

- GPU Xid
- backend連続再起動
- モデルロード失敗
- VRAM/RAM OOM
- NVMe残量低下
- DB障害
- Slurm node DOWN/DRAIN
- gateway未応答
- キュー待ち時間異常
- profile切替ループ
- 温度／電力閾値超過

---

# 20. 非機能要件

| ID | 要件 |
|---|---|
| NFR-001 | 制御面はサーバー稼働中に自動起動し、異常終了後にsystemdで再起動する。 |
| NFR-002 | バックエンド切替が不要な要求では、ゲートウェイ追加遅延p95を100ms以内の目標とする。 |
| NFR-003 | ルーティング判断は通常p95 200ms以内を目標とする。モデルロード時間は除外する。 |
| NFR-004 | 最大3ユーザーの要求とキューを同時に安全に管理できる。 |
| NFR-005 | 同じAPI要求を二重実行しないようrequest IDと状態遷移を管理する。 |
| NFR-006 | サービス再起動後、未完了要求を再判定し、重複実行せず復旧または失敗確定する。 |
| NFR-007 | 設定変更はGit管理し、config revisionをroute decisionへ記録する。 |
| NFR-008 | ランタイム更新はversioned releaseと`current` symlinkでロールバック可能にする。 |
| NFR-009 | モデルrevision、checksum、runtime revisionを再現可能な形で保存する。 |
| NFR-010 | 一般ユーザーは他ユーザーのworkspace、APIキー、prompt履歴を読めない。 |
| NFR-011 | バックエンドは外部ネットワークへ直接公開しない。 |
| NFR-012 | prompt本文の中央保存はopt-inとする。 |
| NFR-013 | 管理者が自動ルーティングを停止し、固定プロファイルへ切り替えられる。 |
| NFR-014 | 新ランタイムはAdapter追加で導入できる。 |
| NFR-015 | ハードウェア値、モデル名、GPU番号をアプリコードへ直書きしない。 |
| NFR-016 | 主要障害についてrunbookを用意する。 |
| NFR-017 | publicモデル本体以外の重要データは定期バックアップする。 |
| NFR-018 | システムRAMに安全余白を残し、OS OOMを避ける。 |
| NFR-019 | 実測ベンチマーク未登録のデプロイメントをautoルーティングへ入れない。 |
| NFR-020 | 監査ログは利用者操作と管理者操作を区別する。 |

---

# 21. 管理CLI要件

コマンド例:

```bash
llmctl status
llmctl queue
llmctl backends
llmctl gpus
llmctl routes --request <id>
llmctl profile show
llmctl profile set balanced
llmctl profile set auto
llmctl drain <backend>
llmctl restart <backend>
llmctl deployment enable <id>
llmctl deployment disable <id>
llmctl deployment benchmark <id>
llmctl model add <manifest>
llmctl model verify <model-id>
llmctl maintenance enter
llmctl maintenance exit
llmctl config validate
llmctl rollback gateway <version>
llmctl rollback runtime llama.cpp <version>
```

## 21.1 運転モード

- `auto`: 通常。ルーターとオーケストレーターが自動制御。
- `fixed-profile`: 管理者が指定したプロファイルを維持。
- `drain`: 新規要求を拒否し、実行中要求完了後に停止。
- `maintenance`: すべての推論バックエンドを停止。
- `safe-mode`: 自動切替を停止し、事前指定の1モデルだけを起動。

---

# 22. ユーザーCLI要件

```bash
agent
agent --policy fast
agent --policy quality
agent --prefer-model dvf
agent --force-model dvf
agent --force-runtime llama_cpp
agent --force-deployment dvf-llama-3gpu-shared
agent --max-wait 300
agent --resume <task-id>
agent status
```

会話中コマンド:

```text
/model auto
/model prefer dvf
/model force dvf
/runtime auto
/runtime force llama_cpp
/deployment force dvf-llama-3gpu-shared
/route status
/route explain
/route unlock
```

`force` は安全制約、権限、物理容量を無効化しない。物理的に実行不能な場合は、別モデルへ黙って変更せず、待機または明示エラーとする。

---

# 23. バックアップ・復旧要件

## 23.1 バックアップ対象

- `/etc/llm-platform`
- PostgreSQL
- model manifests
- benchmark results
- route policy
- runtime/version manifest
- custom quantization
- custom LoRA
- agent harness code
- gateway code
- systemd units
- Slurm設定
- 独自データセット
- 管理runbook

公開モデルの再取得可能な原本は必須バックアップ対象外としてよい。ただしrevisionとchecksumは保存する。

## 23.2 復旧

- gateway再起動
- scheduler再起動
- DB復旧
- Slurm再起動
- backend orphan cleanup
- GPU driver reset後の復旧
- runtime rollback
- model rollback
- disk fullからの復旧

をrunbook化する。

## 23.3 再起動時

1. DBを起動。
2. Slurmを起動。
3. gateway/control planeを起動。
4. DB上のRUNNING backendをSlurmと照合。
5. 存在しないbackendをFAILEDにする。
6. orphan Slurm jobを検出する。
7. 未完了要求を復旧方針に従って再キューまたは失敗確定。
8. auto modeなら既定プロファイルを再構築。
9. health check通過後に新規要求受付。

---

# 24. テスト要件

## 24.1 単体テスト

- ルーティングhard filter
- score計算
- manual override
- state machine
- queue fairness
- config validation
- runtime adapter
- error normalization
- auth
- permission
- path sandbox

## 24.2 結合テスト

- Gateway → llama.cpp
- Gateway → vLLM
- Gateway → Slurm → backend
- streaming
- tool calling
- cancellation
- backend crash
- model load failure
- DB restart
- Slurm restart
- user key revocation
- profile transition

## 24.3 負荷テスト

- 2ユーザー同時
- 3ユーザー同時
- 同じ大型モデル2要求
- 異なるモデル2要求
- 長文＋短文混在
- streaming中の新規要求
- 大量待機要求
- 連続profile切替要求

## 24.4 セキュリティテスト

- 他ユーザーworkspace読取
- path traversal
- promptからのsudo誘導
- API key漏洩
- backend port直接アクセス
- 管理APIへの一般キーアクセス
- secretsのログ出力
- workspace外書込
- symlink攻撃
- 不正model manifest
- 悪意あるモデルファイル

---

# 25. 受入試験

| ID | シナリオ | 合格条件 |
|---|---|---|
| AT-001 | Aが実装用モデル、Bが大型モデル | 1GPU＋2GPU構成で同時処理できる。 |
| AT-002 | AとBが同時に大型モデル | 3GPU共有デプロイメントへ集約し、モデルを2個ロードしない。 |
| AT-003 | 3人が同時要求 | 公平キューで処理され、1人が全枠を独占しない。 |
| AT-004 | `force dvf@llama_cpp` | 別モデルへ変更せず、利用可能になるまで待機または明示エラー。 |
| AT-005 | `force qwen@vllm` | 指定ランタイムで起動し、応答headerに選定結果を返す。 |
| AT-006 | llama.cpp backend crash | 要求を失敗確定または安全に再試行し、backendを再構築する。 |
| AT-007 | vLLM load OOM | deploymentをDEGRADEDにし、同じ失敗を無限再起動しない。 |
| AT-008 | profile切替中に既存stream | stream完了後に切り替え、通常切替で途中切断しない。 |
| AT-009 | Qwen実行中に大型要求2件 | Qwenをdrain後、大型3GPUへ遷移する。 |
| AT-010 | 非プリエンプトbatchが実行中 | batchを勝手にkillせず、agentを待機またはfallbackする。 |
| AT-011 | opportunistic batchが実行中 | 設定に従いrequeueし、agent用GPUを確保できる。 |
| AT-012 | user Aのrepo | user Bと中央backendから書込不可。 |
| AT-013 | prompt logging既定 | 中央ログにprompt本文とコード本文が残らない。 |
| AT-014 | HF token | 他ユーザーと共有されず、ログにも出ない。 |
| AT-015 | モデル更新失敗 | 直前revisionへロールバックできる。 |
| AT-016 | runtime更新失敗 | `current`を旧版へ戻して復旧できる。 |
| AT-017 | サーバー再起動 | DBとSlurmを照合し、二重backendを起動しない。 |
| AT-018 | test失敗反復 | ハーネスが高品質モデルへ昇格する。 |
| AT-019 | 高リスク変更 | 最終レビューが必須になり、可能なら別モデル系列を使う。 |
| AT-020 | 未対応runtimeをforce | 黙って別runtimeを使わず、明示エラーを返す。 |
| AT-021 | キャンセル | 共有backendの他ユーザー要求へ影響しない。 |
| AT-022 | config誤り | 起動前validationで拒否し、稼働中設定を壊さない。 |
| AT-023 | disk残量低下 | 新規モデル取得を停止し、アラートを出す。 |
| AT-024 | route explain | 選択モデル、runtime、主要reason codeを確認できる。 |
| AT-025 | 既存OpenAIクライアント | `base_url`とgateway keyの変更だけで基本Chat Completionsを利用できる。 |

---

# 26. 実装フェーズ

## Phase 0: 基盤確認

- GPU 3枚認識
- NVIDIA driver/CUDA確認
- RAM/NVMeインベントリ
- Slurm/MUNGE/cgroup v2
- 個別ユーザーとservice account
- `/opt` `/srv` `/scratch` 構築

完了条件: 1GPU、2GPU、3GPUのテストジョブがSlurmから実行できる。

## Phase 1: 推論ランタイム

- llama.cppをversioned build
- vLLMを独立venv
- 代表モデルを各runtimeで起動
- OpenAI互換API
- health/metrics
- 基本ベンチマーク

完了条件: 手動で各デプロイメントを起動し、API応答と停止ができる。

## Phase 2: Gatewayと手動ルーティング

- 単一OpenAI互換endpoint
- user API key
- deployment registry
- `force`／`prefer`
- proxyとstreaming
- normalized error
- route logging

完了条件: 利用者は1つのbase URLからllama.cppとvLLMを選べる。

## Phase 3: GPUオーケストレーター

- Slurm backend job管理
- desired-state reconciler
- drain/start/stop
- balanced／strong-shared
- queue
- fairness
- failure recovery
- admin CLI

完了条件: 2+1構成と3GPU共有構成が要求に応じて自動切替する。

## Phase 4: ハーネス

- per-user CLI
- file/shell/git/test
- phase inference
- task features
- state persistence
- manual override
- escalation
- worktree isolation

完了条件: 利用者がモデル名を指定せず、調査→実装→テスト→レビューを継続できる。

## Phase 5: 自動モデルルーター

- hard constraints
- rule score
- measured latency
- switch cost
- loaded bonus
- same-model batching
- route explain

完了条件: 受入タスク群で手動ベースライン以上の成功率または完了時間を達成する。

## Phase 6: 評価・学習型ルーター

- outcome収集
- golden task set
- offline評価
- learned router
- A/B評価
- routing collapse監視

完了条件: 学習型ルーターがルール型より統計的に改善し、安全制約を破らない。

---

# 27. 初期設定例

```yaml
platform:
  max_users: 3
  default_policy: balanced
  prompt_logging: false
  backend_bind: 127.0.0.1

routing:
  modes:
    fast:
      quality_weight: 0.7
      latency_weight: 1.5
      wait_weight: 1.5
      switch_weight: 1.3
    balanced:
      quality_weight: 1.0
      latency_weight: 1.0
      wait_weight: 1.0
      switch_weight: 1.0
    strong:
      quality_weight: 2.0
      latency_weight: 0.5
      wait_weight: 0.5
      switch_weight: 0.4
    max:
      quality_weight: 4.0
      latency_weight: 0.1
      wait_weight: 0.1
      switch_weight: 0.05

queue:
  default_user_concurrency: 1
  max_user_concurrency: 2
  max_pending_per_user: 20
  same_model_coalesce_seconds: 2

scheduler:
  mode: auto
  minimum_profile_dwell_seconds: 120
  rebalance_idle_seconds: 90
  drain_timeout_seconds: 300
  max_switches_per_10_minutes: 3

privacy:
  store_prompt_body: false
  store_code_body: false
  metadata_retention_days: 90
```

数値は初期値であり、実測後に調整する。

---

# 28. 実装上の重要決定

1. **利用者は1つのゲートウェイAPIだけを見る。**
2. **llama.cppとvLLMのAPIは内部backendsとして扱う。**
3. **APIキーでモデルを識別しない。**
4. **モデル選択はlogical model／deployment IDで行う。**
5. **モデル選定とGPU配置決定を分離する。**
6. **ハーネスはユーザー権限、推論制御はservice accountで動かす。**
7. **本番コードとランタイムは`firstuser`のホームではなく`/opt`へ置く。**
8. **モデルは`/srv/models`、一時cacheは`/scratch`へ置く。**
9. **バックエンドはSlurmジョブ単位でGPUを確保する。**
10. **推論中に2GPUから3GPUへhot resizeしない。**
11. **要求をdrainしてから別プロファイルで再起動する。**
12. **同じ大型モデルを2人が使う場合は1サーバーを共有する。**
13. **自動ルーティングを既定にし、prefer／forceを残す。**
14. **初期ルーターはルール型、学習型は実績収集後に導入する。**
15. **未ベンチマークのデプロイメントをautoへ入れない。**

---

# 29. 未確定パラメータ

以下は要件不足ではなく、導入ベンチマークで埋める運用パラメータである。

- 各GPUの正確な型番とVRAM
- DVFの採用量子化
- Qwenの採用量子化
- 各モデルのllama.cpp／vLLM対応可否
- 1GPU／2GPU／3GPUの実測速度
- 同時2要求時の速度
- 最大context
- KV cache量子化
- CPU offload量
- system RAM安全余白
- default warm profile
- model load時間
- user batchとagentの優先時間帯
- prompt metadata保持期間
- exact runtime versions
- tool parser/chat template
- learned router導入基準

これらは `benchmark → manifest → deployment enable` の手順で確定する。

---

# 30. Definition of Done

本システムを本番運用可能と判定する条件:

1. 必須要件がすべて実装済み。
2. AT-001〜AT-025が合格。
3. 代表モデルの1／2／3GPUベンチマークが登録済み。
4. 2人同時、3人同時の負荷試験が完了。
5. prompt本文が既定ログへ残らないことを確認。
6. 各ユーザーのworkspace分離を確認。
7. gateway、Slurm、llama.cpp、vLLMの再起動試験完了。
8. runtime／modelのロールバック試験完了。
9. 障害runbookと日常運用手順が完成。
10. `firstuser` を使わずservice accountで本番プロセスが動作。
11. 自動モードと固定プロファイルモードの双方が動作。
12. route decisionをrequest IDから説明できる。
13. GPU外プロセス、orphan backend、無限再起動を検出できる。
14. バックアップからDB・設定・manifestを復元できる。
15. 利用者が `agent` または1つのOpenAI互換base URLだけで利用できる。

---

# 31. 技術的前提に使用した公式資料

- llama.cpp server README  
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- vLLM Online Serving  
  https://docs.vllm.ai/en/stable/serving/online_serving/
- vLLM Sleep Mode  
  https://docs.vllm.ai/en/stable/features/sleep_mode/
- Slurm GRES / cgroup / FAQ / accounting  
  https://slurm.schedmd.com/gres.conf.html  
  https://slurm.schedmd.com/cgroup.conf.html  
  https://slurm.schedmd.com/faq.html  
  https://slurm.schedmd.com/sacct.html
- Hugging Face Hub environment variables  
  https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables
