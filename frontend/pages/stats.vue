<script setup lang="ts">
import { ref, computed } from 'vue'
import { Bar } from 'vue-chartjs'
import {
  Chart as ChartJS,
  Title,
  Tooltip,
  Legend,
  BarElement,
  CategoryScale,
  LinearScale
} from 'chart.js'
import { useAlcoholStats } from '~/composables/useAlcoholStats'

// Chart.jsの設定
ChartJS.register(
  Title,
  Tooltip,
  Legend,
  BarElement,
  CategoryScale,
  LinearScale
)

const { stats, loading, error, fetchStats, chartData } = useAlcoholStats()

// 期間選択
const period = ref<'daily' | 'weekly' | 'monthly'>('monthly')
const startDate = ref(
  new Date(new Date().setMonth(new Date().getMonth() - 1))
    .toISOString()
    .split('T')[0]
)
const endDate = ref(new Date().toISOString().split('T')[0])

// グラフオプション
const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: true,
      labels: {
        color: '#fbbf24' // amber-400
      }
    },
    title: {
      display: true,
      text: 'アルコール摂取量の推移',
      color: '#fde68a' // amber-200
    }
  },
  scales: {
    x: {
      ticks: {
        color: '#fbbf24' // amber-400
      },
      grid: {
        color: '#78716c' // stone-500
      }
    },
    y: {
      beginAtZero: true,
      title: {
        display: true,
        text: 'ml',
        color: '#fbbf24' // amber-400
      },
      ticks: {
        color: '#fbbf24' // amber-400
      },
      grid: {
        color: '#78716c' // stone-500
      }
    }
  }
}

// データ取得
const fetchData = async () => {
  await fetchStats(period.value, startDate.value, endDate.value)
}

// 初期データ取得
onMounted(fetchData)

// 期間変更時にデータ再取得
watch([period, startDate, endDate], fetchData)

// 期間表示用
const periodText = computed(() => {
  switch (period.value) {
    case 'daily':
      return '日次'
    case 'weekly':
      return '週次'
    case 'monthly':
      return '月次'
  }
})
</script>

<template>
  <div>
    <h1 class="text-3xl font-semibold text-amber-200 mb-6">
      アルコール摂取量の統計
    </h1>

    <!-- 期間選択 -->
    <div class="mt-6 bg-stone-800 shadow-lg px-4 py-5 sm:rounded-lg sm:p-6 border border-amber-700">
      <div class="grid grid-cols-1 gap-6 sm:grid-cols-3">
        <div>
          <label class="block text-sm font-medium text-amber-200">
            集計単位
          </label>
          <select
            v-model="period"
            class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-amber-700 bg-stone-700 text-amber-100 focus:outline-none focus:ring-amber-500 focus:border-amber-500 sm:text-sm rounded-md"
          >
            <option value="daily">日次</option>
            <option value="weekly">週次</option>
            <option value="monthly">月次</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-amber-200">
            開始日
          </label>
          <input
            v-model="startDate"
            type="date"
            class="mt-1 block w-full border-amber-700 bg-stone-700 text-amber-100 rounded-md shadow-sm focus:ring-amber-500 focus:border-amber-500 sm:text-sm"
          >
        </div>
        <div>
          <label class="block text-sm font-medium text-amber-200">
            終了日
          </label>
          <input
            v-model="endDate"
            type="date"
            class="mt-1 block w-full border-amber-700 bg-stone-700 text-amber-100 rounded-md shadow-sm focus:ring-amber-500 focus:border-amber-500 sm:text-sm"
          >
        </div>
      </div>
    </div>

    <!-- ローディング -->
    <div v-if="loading" class="mt-6 text-center">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-amber-500 border-t-transparent"></div>
    </div>

    <!-- エラー -->
    <div v-else-if="error" class="mt-6 bg-red-900/50 p-4 rounded-md border border-red-800">
      <div class="text-red-300">
        {{ error }}
      </div>
    </div>

    <!-- 統計データ -->
    <div v-else-if="stats" class="mt-6">
      <div class="bg-stone-800 shadow-lg overflow-hidden sm:rounded-lg border border-amber-700">
        <div class="px-4 py-5 sm:p-6">
          <h3 class="text-lg leading-6 font-medium text-amber-200">
            {{ periodText }}集計
          </h3>
          <dl class="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-3">
            <div class="px-4 py-5 bg-stone-700 shadow rounded-lg overflow-hidden sm:p-6 border border-amber-600">
              <dt class="text-sm font-medium text-amber-300 truncate">
                総摂取量
              </dt>
              <dd class="mt-1 text-3xl font-semibold text-amber-100">
                {{ stats.total_volume_ml.toLocaleString() }}ml
              </dd>
            </div>
            <div class="px-4 py-5 bg-stone-700 shadow rounded-lg overflow-hidden sm:p-6 border border-amber-600">
              <dt class="text-sm font-medium text-amber-300 truncate">
                1日平均
              </dt>
              <dd class="mt-1 text-3xl font-semibold text-amber-100">
                {{ stats.daily_average_ml.toLocaleString() }}ml
              </dd>
            </div>
            <div class="px-4 py-5 bg-stone-700 shadow rounded-lg overflow-hidden sm:p-6 border border-amber-600">
              <dt class="text-sm font-medium text-amber-300 truncate">
                最大摂取量
              </dt>
              <dd class="mt-1 text-3xl font-semibold text-amber-100">
                {{ stats.max_daily_volume_ml.toLocaleString() }}ml
              </dd>
            </div>
          </dl>
        </div>
      </div>

      <!-- グラフ -->
      <div v-if="chartData" class="mt-6 bg-stone-800 shadow-lg sm:rounded-lg p-6 border border-amber-700">
        <div class="h-96">
          <Bar
            :data="chartData"
            :options="chartOptions"
          />
        </div>
      </div>
    </div>
  </div>
</template> 