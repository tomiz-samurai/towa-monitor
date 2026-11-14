# TOWA カレンダー監視（GitHub Actions版）

GitHub Actions を使って **完全無料・Macなし・24時間** 自動監視します。
TOWAさんの予約枠に○が追加されたら LINE に通知します。

## 恵比寿 出勤日監視（究極の美爆乳さん）

`este_4064_monitor.py` が [プロフィール](https://mens-este.com/therapist/profile.php?id=4064) の「出勤予定」を確認します。ワークフローは `.github/workflows/este_monitor.yml` です。TOWA 監視（`towa_calendar_monitor.py` / `monitor.yml` / `towa_calendar_state.json`）とは別です。

通知するのは次のときだけです。

- 以前は未掲載、または `-`（休み）だった日に勤務時間が入った
- すでに出勤だった日の時間が変わった

日付の窓がずれて古い日が消え、新しい日が `-` で出るだけ、または出勤日が消えただけ、のときは通知しません。状態ファイルがまだ無い初回実行は保存のみで通知しません。取得や解析に失敗したときはログだけ出して状態を上書きせず、終了コード 0 で終わります。

状態は `este_4064_state.json` に保存します。

起動タイミング:

- `repository_dispatch`（type: `run-monitor`）。TOWA 監視と同じイベントなので、外部スケジューラの 1 回の ping で両方が動きます。
- `workflow_dispatch`
- 予備の schedule: `*/5 * * * *`（GitHub の時刻は UTC。検出時刻はスクリプト側で Asia/Tokyo にします）

通知先:

- リポジトリシークレット `SLACK_WEBHOOK_URL` があるとき、Slack Incoming Webhook に投稿します。**Slack に届けるには、このシークレットを自分で追加してください。**
- `LINE_CHANNEL_ACCESS_TOKEN` と `LINE_USER_ID`（既存の TOWA 用シークレット）があるとき、同じ LINE Push API にも送ります。両方設定されていれば両方に送ります。

`main` へ状態を戻すとき、TOWA 監視と同時に push しても追いつけるよう、このワークフローは concurrency で直列化し、`git pull --rebase` をリトライしてから push します。コミットメッセージには `[skip ci]` を付けます。

### テスト通知

Actions タブで「恵比寿 出勤日監視」を開き、Run workflow で `test_notify` をオンにします。変化の有無に関係なく、次の文面で現在の出勤予定を送り、状態ファイルは変更しません。

`🧪 テスト通知：恵比寿 出勤日監視` + 解析した出勤予定 + ページ URL

`workflow_dispatch` は、このワークフローがデフォルトブランチに入ってから使えます。PR のブランチだけでは Actions 一覧に出ないことがあります。その場合は PR をマージしてから実行してください。

## アロマミエリー 出勤日監視（profile id=433）

`miely_433_monitor.py` が [プロフィール](https://aroma-miely.com/therapist/profile.php?id=433) の「スケジュール」を確認します。ワークフローは `.github/workflows/miely_monitor.yml` です。TOWA 監視（`towa_calendar_monitor.py` / `monitor.yml` / `towa_calendar_state.json`）および恵比寿監視（`este_4064_monitor.py` / `este_monitor.yml` / `este_4064_state.json`）とは別です。

ページの `section.schedule` にある週の一覧（日付と、勤務時間または `―` / 休み / 未定）を読みます。スケジュールは HTML に含まれており、別エンドポイントは使いません。セラピスト名は同じページの「名前（年齢）」から読み、年齢は除きます。

通知するのは次のときだけです。

- 以前は未掲載、または休み・未定・`―` だった日に勤務時間が入った
- すでに出勤だった日の時間が変わった

日付の窓がずれて古い日が消え、新しい日が休みで出るだけ、または出勤日が消えただけ、のときは通知しません。状態ファイルがまだ無い初回実行は保存のみで通知しません。取得や解析に失敗したときはログだけ出して状態を上書きせず、終了コード 0 で終わります。

通知文には、ページから読んだセラピスト名、店名（アロマミエリー）、変化のあった日、現在の出勤予定全体、ページ URL を入れます。

状態は `miely_433_state.json` に保存します。

起動タイミング:

- `repository_dispatch`（type: `run-monitor`）。TOWA 監視・恵比寿監視と同じイベントなので、外部スケジューラの 1 回の ping で全部が動きます。
- `workflow_dispatch`
- 予備の schedule: `*/5 * * * *`（GitHub の時刻は UTC。検出時刻はスクリプト側で Asia/Tokyo にします）

通知先:

- リポジトリシークレット `SLACK_WEBHOOK_URL` があるとき、Slack Incoming Webhook に投稿します。**Slack に届けるには、このシークレットを自分で追加してください。**
- `LINE_CHANNEL_ACCESS_TOKEN` と `LINE_USER_ID`（既存の TOWA 用シークレット）があるとき、同じ LINE Push API にも送ります。両方設定されていれば両方に送ります。

`main` へ状態を戻すとき、他の監視と同時に push しても追いつけるよう、このワークフローは concurrency グループ `miely-433-monitor` で直列化し、`git pull --rebase` をリトライしてから push します。コミットメッセージには `[skip ci]` を付けます。

### テスト通知

Actions タブで「アロマミエリー 出勤日監視」を開き、Run workflow で `test_notify` をオンにします。変化の有無に関係なく、次の文面で現在の出勤予定を送り、状態ファイルは変更しません。

`🧪 テスト通知：アロマミエリー 出勤日監視` + 解析した出勤予定 + ページ URL

`workflow_dispatch` は、このワークフローがデフォルトブランチに入ってから使えます。PR のブランチだけでは Actions 一覧に出ないことがあります。その場合は PR をマージしてから実行してください。
