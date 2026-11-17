import path from 'node:path'
import { Config } from '@remotion/cli/config'

// The caption components live in ../frontend/src/captions. Make every `react` import resolve to this
// project's copy, so the bundle never contains two Reacts.
Config.overrideWebpackConfig((config) => ({
  ...config,
  resolve: {
    ...config.resolve,
    alias: {
      ...(config.resolve?.alias ?? {}),
      react: path.resolve(process.cwd(), 'node_modules/react'),
      'react-dom': path.resolve(process.cwd(), 'node_modules/react-dom'),
    },
  },
}))
