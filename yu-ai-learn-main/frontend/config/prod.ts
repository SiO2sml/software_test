import type { UserConfigExport } from '@tarojs/cli'

export default {
  defineConstants: {
    API_BASE_URL: '"https://ai-learn.codefather.cn/api/v1"',
  },
  mini: {},
  h5: {},
} satisfies UserConfigExport<'webpack5'>
