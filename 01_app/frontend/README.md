# 前端

React、TypeScript、Vite 与 Ant Design。`src/App.tsx` 管理公司工作台和页面导航，`src/components/` 存放界面组件，`src/api.ts` 封装本机 API 请求。

在本目录执行：

```sh
npm ci
npm test
npm run typecheck
npm run build
```

`dist/` 由构建生成，本机 Python 服务直接提供该目录的页面；它不进入 Git。行为测试位于 `../tests/frontend_*`，由 `../scripts/test_frontend.mjs` 运行。

完整启动步骤见根目录 [README](../../README.md)，接口见 [API](../docs/API.md)。
