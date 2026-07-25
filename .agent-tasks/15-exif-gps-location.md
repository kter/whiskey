# Task 15: アップロード画像の EXIF GPS から現在地（店候補検索）を取得

## 背景・スコープ
実機受入で「現在地は可能であればアップロード画像の EXIF から取得してほしい」との要望。
**フロントエンドのみ**（`frontend/` 配下）。`lambda/`・`infra/`・スキーマ・API 契約は変更禁止。
`git diff` が frontend 以外に触れていたら不合格。

## 最重要の設計制約（必読）
このアプリは**プライバシー保護のため画像の EXIF/GPS を意図的に除去**している:
`utils/imageResize.ts` の canvas 再エンコードで EXIF が消え、バックエンドも GPS を剥がす。
したがって **EXIF GPS は「リサイズ前の元 File」からクライアント側で読む**必要がある。

**座標の扱いは現行ポリシーと完全一致させる**: 読み取った緯度経度は **Google Places の
近隣検索にだけ使い、サーバーにもレコードにも保存しない**（座標は既に「Places に送るだけ・
非保存」。EXIF を新たな座標の"入手経路"にするだけで、保存しない原則は変えない）。

## 実装

### 1. 依存追加: `exifr`
- `frontend/package.json` に `exifr` を**正確なバージョン `7.1.3` で exact pin**（`^` なし）。
  `package-lock.json` も更新。exifr は JPEG も **HEIC も** GPS を直接読める（HEIF コンテナの
  Exif box をパースするため、heic 変換前の元ファイルから読める）。
- **動的 import** で読み込む（`await import('exifr')`）— 初期バンドルを太らせない。

### 2. 新規 `frontend/utils/exifLocation.ts`
```ts
export interface Coordinates { lat: number; lng: number }
/** 元ファイルの EXIF から GPS を読む。無い/失敗時は null。座標は保存しないこと。 */
export const readExifGps = async (file: File): Promise<Coordinates | null> => { ... }
```
- 実装: `const exifr = (await import('exifr')).default; const gps = await exifr.gps(file)`。
  `gps` は `{ latitude, longitude }` または `undefined`。有限数値かつ緯度∈[-90,90]・経度∈[-180,180]
  を検証し、`{ lat, lng }` に正規化して返す。例外・未取得・範囲外は `null`（fail-safe、投げない）。
- HEIC/JPEG/PNG/WebP いずれの File でも安全に呼べること（GPS が無ければ null）。

### 3. `frontend/pages/logs/new.vue` への配線
現在、店候補検索は「近くの店を探す」ボタン（`findNearbyPlaces` → `useGeolocation.requestPosition`
＝端末 GPS）で手動起動する。これを次のように拡張:
- **写真選択・処理時に、GPS EXIF を持つ最初の写真の元 File から `readExifGps` で座標を取得**し、
  取得できたら**自動で Places 近隣検索を実行**して店候補を表示する（共有店舗欄に反映）。
  - バッチは同一店の想定で店舗は全カード共有のため、**最初に GPS を持つ写真の座標**を採用。
  - 元 File は `useDrinkLogBatch` の各 item が保持している（`item.file`）。リサイズ前に読むこと。
    EXIF 読み取りは処理パイプライン（resize より前、または選択直後）で行い、resize が EXIF を
    消す前に完了させる。**座標は ref 等に一時保持し、Places 検索に渡したら破棄**（永続化しない、
    レコードにも payload にも入れない）。
- **`可能であれば` の解釈 = EXIF 優先・フォールバック維持**: EXIF に GPS が無ければ、従来の
  「近くの店を探す」ボタン（端末 GPS）をそのまま使えること。EXIF 取得成功時もボタンは残し、
  ユーザーが端末 GPS で取り直せるようにする。手入力の店名も従来通り可能。
- EXIF 由来で自動検索した場合、その旨が分かる軽い表示（例: 「写真の位置情報から近くの店を検索
  しました」）を任意で添えてよい（必須ではない）。

### 4. 同意文言の更新（`composables/useGeolocation.ts` の `GEOLOCATION_DISCLOSURE`、および
   プライバシーポリシー `pages/privacy.vue` に GPS 記述があれば）
- 現行文言は端末 GPS 前提。**「写真の位置情報(EXIF)またはお使いの端末の現在地」を Google Places
  に送信して店候補検索にのみ使用し、座標は保存しない**旨に更新。EXIF が新たな座標源になったことを
  正直に開示する。privacy.vue の位置情報セクションにも同趣旨を反映（存在する場合）。

## テスト（vitest, `frontend/tests/`）
- `readExifGps`（新規 `tests/utils/exifLocation.test.ts`）: `exifr` を**モック**し、
  `gps` が座標を返す場合 `{lat,lng}` を返す / `undefined` の場合 `null` / 範囲外や例外で `null`。
- new.vue（`tests/pages/logsNew.test.ts` に追加）: 元 File が GPS を持つとき、選択後に Places
  検索（`searchPlaces` 相当）が自動で呼ばれること。GPS 無しのときは自動検索されず手動ボタンで
  動くこと。`readExifGps`/`searchPlaces` はモックしてよい。座標が payload/レコードに乗らないことを
  最低1つのテストで確認（保存 payload に lat/lng が含まれない）。
- vitest の alias に `exifr` のモックを追加（`vitest.config.ts` + `tests/mocks/exifr.ts`）—
  heic-to のモックと同じ流儀。

## 受入条件
- `cd frontend && npm ci && npm run lint && npm run typecheck && npm run test -- --run && npm run generate` が全て成功。
- GPS 付き写真をアップロードすると自動で近くの店候補が出る。GPS 無しは従来のボタンで動く。
- **座標はレコード・API payload・localStorage 等に一切保存されない**（Places 検索に渡すのみ）。
- `git diff` は `frontend/` のみ。exifr は exact pin（`7.1.3`）、動的 import で code-split。
- 既存のバッチ確認フロー・手入力店名・端末 GPS ボタンが後方互換で維持される。

## 実装メモ（オーケストレーター向け・Codex は無視可）
- 依存追加の lockfile integrity はレジストリ正規値 `sha512-g/aje2noHivrRSLbAUtBPWFbxKdKhgj/xr1vATDdUXPOFYJlQ62Ft0oy+72V6XLIpDJfHs6gXLbBLAolqOXYRw==` と照合し、
  `rm -rf node_modules && npm ci` で検証してからコミットする（Codex はネットワーク制限で
  lockfile ハッシュを捏造しうるため）。
