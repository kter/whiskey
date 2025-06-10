<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuth, type UserProfile } from '~/composables/useAuth'

const { user, profile, profileLoading, updateUserProfile, getDisplayName } = useAuth()

const isEditing = ref(false)
const saving = ref(false)
const error = ref('')
const success = ref('')

const editForm = ref({
  nickname: '',
  display_name: ''
})

// プロフィール編集開始
const startEditing = () => {
  editForm.value = {
    nickname: profile.value?.nickname || '',
    display_name: profile.value?.display_name || ''
  }
  isEditing.value = true
  error.value = ''
  success.value = ''
}

// 編集キャンセル
const cancelEditing = () => {
  isEditing.value = false
  error.value = ''
  success.value = ''
}

// プロフィール保存
const saveProfile = async () => {
  try {
    saving.value = true
    error.value = ''
    success.value = ''

    if (!editForm.value.nickname.trim()) {
      error.value = 'ニックネームは必須です'
      return
    }

    await updateUserProfile(
      editForm.value.nickname.trim(),
      editForm.value.display_name.trim() || undefined
    )

    success.value = 'プロフィールを更新しました'
    isEditing.value = false
  } catch (err: any) {
    error.value = err.message || 'プロフィールの更新に失敗しました'
  } finally {
    saving.value = false
  }
}

// 初期データ読み込み
onMounted(() => {
  if (!profile.value && user.value) {
    // プロフィールが未読み込みの場合はfetchUserProfileを呼ぶ
    // これは通常、useAuthのinitializeで自動的に呼ばれる
  }
})
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <h1 class="text-3xl font-semibold text-amber-200 mb-6">
      プロフィール設定
    </h1>

    <!-- ローディング状態 -->
    <div v-if="profileLoading" class="text-center py-8">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-amber-500 border-t-transparent"></div>
      <p class="mt-2 text-amber-300">プロフィールを読み込み中...</p>
    </div>

    <!-- プロフィール表示/編集 -->
    <div v-else class="bg-stone-800 shadow-lg rounded-lg p-6 border border-amber-700">
      <!-- 現在のプロフィール表示 -->
      <div v-if="!isEditing">
        <div class="mb-6">
          <h2 class="text-xl font-medium text-amber-200 mb-4">現在のプロフィール</h2>
          
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-amber-200 mb-1">
                表示名
              </label>
              <p class="text-amber-100 text-lg">
                {{ getDisplayName() }}
              </p>
            </div>

            <div v-if="profile?.nickname">
              <label class="block text-sm font-medium text-amber-200 mb-1">
                ニックネーム
              </label>
              <p class="text-amber-100">
                {{ profile.nickname }}
              </p>
            </div>

            <div v-if="profile?.display_name">
              <label class="block text-sm font-medium text-amber-200 mb-1">
                フルネーム
              </label>
              <p class="text-amber-100">
                {{ profile.display_name }}
              </p>
            </div>

            <div v-if="user?.username">
              <label class="block text-sm font-medium text-amber-200 mb-1">
                アカウント名
              </label>
              <p class="text-amber-100 text-sm">
                {{ user.username }}
              </p>
            </div>

            <div v-if="profile?.created_at">
              <label class="block text-sm font-medium text-amber-200 mb-1">
                プロフィール作成日
              </label>
              <p class="text-amber-100 text-sm">
                {{ new Date(profile.created_at).toLocaleDateString('ja-JP') }}
              </p>
            </div>
          </div>
        </div>

        <button
          @click="startEditing"
          class="inline-flex items-center px-4 py-2 border border-amber-700 text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 transition-colors"
        >
          プロフィールを編集
        </button>
      </div>

      <!-- プロフィール編集フォーム -->
      <div v-else>
        <h2 class="text-xl font-medium text-amber-200 mb-4">プロフィール編集</h2>

        <form @submit.prevent="saveProfile" class="space-y-6">
          <!-- ニックネーム -->
          <div>
            <label for="nickname" class="block text-sm font-medium text-amber-200 mb-1">
              ニックネーム *
            </label>
            <input
              id="nickname"
              v-model="editForm.nickname"
              type="text"
              required
              maxlength="50"
              class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm placeholder-amber-400"
              placeholder="表示されるニックネームを入力"
            >
            <p class="mt-1 text-xs text-amber-400">
              他のユーザーに表示される名前です（50文字以内）
            </p>
          </div>

          <!-- 表示名 -->
          <div>
            <label for="display_name" class="block text-sm font-medium text-amber-200 mb-1">
              フルネーム（任意）
            </label>
            <input
              id="display_name"
              v-model="editForm.display_name"
              type="text"
              maxlength="100"
              class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm placeholder-amber-400"
              placeholder="フルネームまたは表示名（任意）"
            >
            <p class="mt-1 text-xs text-amber-400">
              必要に応じて設定してください（100文字以内）
            </p>
          </div>

          <!-- エラー・成功メッセージ -->
          <div v-if="error" class="text-red-300 bg-red-900/50 p-3 rounded-md border border-red-800 text-sm">
            {{ error }}
          </div>

          <div v-if="success" class="text-green-300 bg-green-900/50 p-3 rounded-md border border-green-800 text-sm">
            {{ success }}
          </div>

          <!-- ボタン -->
          <div class="flex justify-end space-x-3">
            <button
              type="button"
              @click="cancelEditing"
              :disabled="saving"
              class="inline-flex justify-center py-2 px-4 border border-stone-600 shadow-sm text-sm font-medium rounded-md text-amber-200 bg-stone-700 hover:bg-stone-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors disabled:opacity-50"
            >
              キャンセル
            </button>
            <button
              type="submit"
              :disabled="saving || !editForm.nickname.trim()"
              class="inline-flex justify-center py-2 px-4 border border-amber-700 shadow-sm text-sm font-medium rounded-md text-amber-100 bg-amber-800 hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 transition-colors disabled:opacity-50"
            >
              <span v-if="saving" class="inline-flex items-center">
                <svg class="animate-spin -ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                保存中...
              </span>
              <span v-else>保存</span>
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- ナビゲーション -->
    <div class="mt-6">
      <NuxtLink
        to="/reviews"
        class="inline-flex items-center text-sm text-amber-300 hover:text-amber-100 transition-colors"
      >
        ← レビュー一覧に戻る
      </NuxtLink>
    </div>
  </div>
</template>