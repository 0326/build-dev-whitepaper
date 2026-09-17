import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { themes as prismThemes } from 'prism-react-renderer';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const generatedPath = path.join(__dirname, 'whitepaper.generated.json');

if (!fs.existsSync(generatedPath)) {
  throw new Error(
    'whitepaper.generated.json is missing. Run the whitepaper manifest projection before starting Docusaurus.',
  );
}

const generated = JSON.parse(fs.readFileSync(generatedPath, 'utf8'));
const repository = process.env.GITHUB_REPOSITORY ?? '';
const [repositoryOwner, repositoryName] = repository.split('/');
const deployTarget = process.env.DEPLOY_TARGET ?? 'local';
const isGitHubPages = deployTarget === 'github-pages';
const isRootPagesRepository =
  repositoryOwner &&
  repositoryName &&
  repositoryName.toLowerCase() === `${repositoryOwner.toLowerCase()}.github.io`;

const inferredBaseUrl =
  isGitHubPages && repositoryName && !isRootPagesRepository ? `/${repositoryName}/` : '/';
const inferredSiteUrl =
  isGitHubPages && repositoryOwner ? `https://${repositoryOwner}.github.io` : 'http://localhost';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: process.env.SITE_TITLE ?? 'Developer Whitepaper',
  tagline: process.env.SITE_TAGLINE ?? 'Versioned developer whitepaper',
  url: process.env.SITE_URL ?? inferredSiteUrl,
  baseUrl: process.env.BASE_URL ?? inferredBaseUrl,
  trailingSlash: false,
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',

  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
      onBrokenMarkdownImages: 'throw',
    },
  },
  themes: ['@docusaurus/theme-mermaid'],

  presets: [
    [
      'classic',
      {
        docs: {
          path: generated.docsPath,
          routeBasePath: '/',
          sidebarPath: path.resolve(__dirname, 'sidebars.js'),
          include: generated.include,
          showLastUpdateTime: true,
        },
        blog: false,
        theme: {
          customCss: path.resolve(__dirname, 'src/css/custom.css'),
        },
      },
    ],
  ],

  themeConfig: {
    navbar: {
      title: process.env.SITE_TITLE ?? 'Developer Whitepaper',
      items: [],
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  },
};

export default config;
