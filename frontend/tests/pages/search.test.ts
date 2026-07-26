import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { mount } from '@vue/test-utils'
import { computed, defineComponent, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'pages/search.vue'), 'utf8')
const template = source.match(/<template>([\s\S]*)<\/template>/)?.[1]

if (!template) throw new Error('search.vue template not found')

const renderSearch = (nextToken: string | null) => mount(defineComponent({
  setup: () => ({
    searchFilters: ref({ name: '響' }),
    advancedResults: ref([]),
    advancedNextToken: ref(nextToken),
    isAdvancedSearching: ref(false),
    advancedSearchError: ref(''),
    searchPerformed: ref(true),
    selectedResult: ref(null),
    canSearch: computed(() => true),
    handleSearch: vi.fn(),
    resetSearch: vi.fn(),
    loadMoreAdvancedResults: vi.fn(),
  }),
  template,
}))

describe('search page empty result pagination', () => {
  it('offers to load more when an empty page has a next token', () => {
    const wrapper = renderSearch('next-page')

    expect(wrapper.text()).not.toContain('該当するウイスキーが見つかりませんでした。')
    expect(wrapper.text()).toContain('続きを検索できます。')
    expect(wrapper.text()).toContain('さらに読み込む')
  })

  it('shows not found when an empty page has no next token', () => {
    const wrapper = renderSearch(null)

    expect(wrapper.text()).toContain('該当するウイスキーが見つかりませんでした。')
    expect(wrapper.text()).not.toContain('さらに読み込む')
  })
})
