import { ref } from 'vue'
import type { AlcoholStats, ChartDataPoint } from '~/types/whiskey'
import { useAuth } from '~/composables/useAuth'

export const useAlcoholStats = () => {
  const { getToken } = useAuth()
  const config = useRuntimeConfig()

  const stats = ref<AlcoholStats | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const chartData = ref<any>(null)

  // 統計データの取得
  const fetchStats = async (
    period: 'daily' | 'weekly' | 'monthly',
    startDate: string,
    endDate: string
  ) => {
    try {
      loading.value = true
      error.value = null

      const token = await getToken()
      const response = await fetch(
        `${config.public.apiBaseUrl}/api/stats?` +
          new URLSearchParams({
            period,
            start_date: startDate,
            end_date: endDate
          }),
        {
          headers: {
            Authorization: `Bearer ${token}`
          }
        }
      )

      if (!response.ok) {
        throw new Error('統計データの取得に失敗しました')
      }

      const data = await response.json()
      stats.value = data.stats
      updateChartData(data.chart_data)
    } catch (err) {
      error.value = '統計データの取得に失敗しました'
      stats.value = null
      chartData.value = null
    } finally {
      loading.value = false
    }
  }

  // グラフデータの更新
  const updateChartData = (data: ChartDataPoint[]) => {
    chartData.value = {
      labels: data.map(point => point.date),
      datasets: [
        {
          label: 'アルコール摂取量 (ml)',
          data: data.map(point => point.volume_ml),
          backgroundColor: 'rgba(99, 102, 241, 0.5)',
          borderColor: 'rgb(99, 102, 241)',
          borderWidth: 1
        }
      ]
    }
  }

  return {
    stats,
    loading,
    error,
    chartData,
    fetchStats
  }
} 