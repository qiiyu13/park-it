// @ts-check
import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt(
  {
    rules: {
      // Clearing a Vue `reactive()` map means deleting computed keys — a
      // reactive object cannot be reassigned. This rule targets TS typing and
      // perf concerns that do not apply to that pattern.
      '@typescript-eslint/no-dynamic-delete': 'off',
    },
  },
  {
    // `page` is a useCrudPage() controller handle holding refs, not plain data.
    // Assigning `props.page.x.value` mutates the ref, not the prop binding —
    // which is the entire reason the handle is passed down.
    files: ['components/admin/CrudTab.vue'],
    rules: {
      'vue/no-mutating-props': 'off',
    },
  },
)
