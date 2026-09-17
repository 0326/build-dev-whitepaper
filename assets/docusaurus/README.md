# Docusaurus 集成资产

这些文件用于把 build-dev-whitepaper 的 canonical manifest 与 Markdown 接入 Docusaurus。它们是**可复制模板**，不是 Skill 自己的网站。

推荐目标结构：

```text
website/whitepaper/
├── docusaurus.config.js
├── sidebars.js
├── whitepaper.generated.json   # 运行时生成，不手工维护
├── scripts/
│   └── project-manifest.mjs
└── package.json
```

## 使用

1. 用官方 Docusaurus classic 模板创建或复用站点；
2. 将本目录的 `docusaurus.config.js`、`sidebars.js` 与 `scripts/project-manifest.mjs` 复制到站点；
3. 如果使用 Mermaid，安装与当前 Docusaurus core 匹配的 `@docusaurus/theme-mermaid`；
4. 在站点 `package.json` 增加：

```json
{
  "scripts": {
    "whitepaper:project": "node scripts/project-manifest.mjs --manifest ../../manifests/whitepaper.json --root ../.. --site-dir .",
    "prestart": "npm run whitepaper:project",
    "prebuild": "npm run whitepaper:project"
  }
}
```

如果 manifest 不叫 `manifests/whitepaper.json`，或者站点不在 `website/whitepaper/`，按实际路径调整参数。

指定版本：

```bash
node scripts/project-manifest.mjs \
  --manifest ../../manifests/whitepaper.json \
  --root ../.. \
  --site-dir . \
  --version v1.2.0
```

未传 `--version` 时使用 manifest 的 `policy.default_version`。

## 部署模板

- `github-pages.yml`：复制到目标仓库 `.github/workflows/whitepaper-pages.yml`，调整 `DOCUSAURUS_DIR`；
- `vercel.json`：复制到 Docusaurus 站点根目录，并把 Vercel Root Directory 指向该目录；
- `netlify.toml`：复制到 Docusaurus 站点根目录，并把 Netlify Base directory 指向该目录。

所有部署都以 `npm run build` 生成的 `build/` 为输入。部署是可选步骤，本地构建不依赖任何托管平台。

完整约定见 [`references/docusaurus.md`](../../references/docusaurus.md)。
