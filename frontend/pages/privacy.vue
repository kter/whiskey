<script setup lang="ts">
useHead({ title: 'プライバシーポリシー | Whiskey Log' })
</script>

<template>
  <article class="mx-auto max-w-3xl px-4 text-stone-200 sm:px-0">
    <h1 class="text-3xl font-semibold text-amber-200">プライバシーポリシー</h1>
    <p class="mt-3 text-sm text-stone-400">最終更新日: 2026年7月23日</p>

    <div class="mt-8 space-y-8 leading-relaxed">
      <section>
        <h2 class="text-xl font-medium text-amber-200">1. 位置情報とGoogle Places</h2>
        <p class="mt-2">アップロードした写真に位置情報（EXIF）が含まれる場合はそのGPS座標を使って自動検索し、「近くの店を探す」を選んだ場合はお使いの端末から取得したGPS座標を使って検索します。いずれの座標も当サービスのサーバー経由でGoogle Placesへ送信し、周辺の店候補検索だけに使用して保存しません。位置情報の提供は任意であり、写真に位置情報がない場合や端末の現在地を取得できない場合も店名を手入力して記録できます。</p>
        <p class="mt-2">Google Placesから取得した表示名・住所・帰属情報は候補表示のためだけに使用し、永続保存しません。記録に保存する店舗情報はplace_idと、ユーザーが自由入力した店名のみです。Googleによる情報の取扱いについては<a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer" class="text-amber-300 underline hover:text-amber-200">Googleプライバシーポリシー</a>をご確認ください。</p>
      </section>

      <section>
        <h2 class="text-xl font-medium text-amber-200">2. Amazon Bedrockによる画像解析</h2>
        <p class="mt-2">投稿画像は、ウイスキーの銘柄と飲み方の候補を判別するためAmazon Bedrockへ送信します。推論処理ではAPAC域内のクロスリージョン配送を利用します。モデル呼び出しログは無効にする運用方針です。AIの判定には誤りがあり得るため、提案内容は保存前に編集できます。</p>
      </section>

      <section>
        <h2 class="text-xl font-medium text-amber-200">3. 画像の保存と一時保持</h2>
        <p class="mt-2">アップロード直後の生画像は、処理のためS3の<code class="rounded bg-stone-800 px-1.5 py-0.5 text-amber-200">tmp/</code>領域に一時保持され、2日後に失効処理の対象になります。物理削除は非同期で行われるため、失効時刻と実際の削除時刻は一致しない場合があります。</p>
        <p class="mt-2">保存したテイスティング記録の画像はS3の<code class="rounded bg-stone-800 px-1.5 py-0.5 text-amber-200">logs/</code>領域へプライベート保存し、認証・認可を確認したうえで期限付きのpresigned URLを発行して表示します。</p>
      </section>

      <section>
        <h2 class="text-xl font-medium text-amber-200">4. 保存する情報</h2>
        <p class="mt-2">アカウント識別情報、ユーザーが保存した写真、銘柄、飲み方、評価、ノート、記録日時、自由入力した店名、および選択した店舗のplace_idを保存します。GPS座標とGoogleが返す店舗表示名は保存しません。</p>
      </section>
    </div>
  </article>
</template>
