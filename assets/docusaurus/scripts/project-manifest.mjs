#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

function fail(message) {
  console.error(`[build-dev-whitepaper] ${message}`);
  process.exit(2);
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      fail(`unexpected argument: ${token}`);
    }
    const key = token.slice(2);
    const value = argv[i + 1];
    if (!value || value.startsWith('--')) {
      fail(`missing value for --${key}`);
    }
    args[key] = value;
    i += 1;
  }
  return args;
}

function toPosix(value) {
  return value.split(path.sep).join('/');
}

function stripQuotes(value) {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function frontMatterId(filePath) {
  const source = fs.readFileSync(filePath, 'utf8');
  if (!source.startsWith('---')) {
    return null;
  }

  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(source);
  if (!match) {
    return null;
  }

  for (const line of match[1].split(/\r?\n/)) {
    const idMatch = /^id:\s*(.+?)\s*$/.exec(line);
    if (idMatch) {
      return stripQuotes(idMatch[1]);
    }
  }
  return null;
}

function ensureInside(root, candidate, label) {
  const relative = path.relative(root, candidate);
  if (relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))) {
    return;
  }
  fail(`${label} escapes its root: ${candidate}`);
}

const args = parseArgs(process.argv.slice(2));
if (!args.manifest) fail('--manifest is required');
if (!args.root) fail('--root is required');

const rootDir = path.resolve(args.root);
const siteDir = path.resolve(args['site-dir'] ?? process.cwd());
const manifestPath = path.resolve(args.manifest);
const outputPath = path.resolve(args.out ?? path.join(siteDir, 'whitepaper.generated.json'));

if (!fs.existsSync(manifestPath)) fail(`manifest not found: ${manifestPath}`);

let manifest;
try {
  manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
} catch (error) {
  fail(`cannot parse manifest JSON: ${error.message}`);
}

const versionId = args.version ?? manifest.policy?.default_version;
if (!versionId) fail('no --version provided and policy.default_version is missing');

const versions = Array.isArray(manifest.versions) ? manifest.versions : [];
const version = versions.find((item) => item.id === versionId);
if (!version) fail(`version not found in manifest: ${versionId}`);
if (!version.content_root) fail(`version ${versionId} is missing content_root`);

const contentRoot = path.resolve(rootDir, version.content_root);
ensureInside(rootDir, contentRoot, 'content_root');
if (!fs.existsSync(contentRoot) || !fs.statSync(contentRoot).isDirectory()) {
  fail(`content_root is not a directory: ${contentRoot}`);
}

const articles = Array.isArray(version.articles) ? version.articles : [];
const articleById = new Map();
for (const article of articles) {
  if (!article?.id || !article?.file || !article?.title) {
    fail(`version ${versionId} has an article missing id, title, or file`);
  }
  if (articleById.has(article.id)) {
    fail(`duplicate article id: ${article.id}`);
  }
  articleById.set(article.id, article);
}

const docIdByArticleId = new Map();
const seenDocIds = new Set();
const include = [];

for (const article of articles) {
  const relativeFile = toPosix(article.file);
  if (!/\.(md|mdx)$/i.test(relativeFile)) {
    fail(`Docusaurus article must be Markdown or MDX: ${relativeFile}`);
  }

  const absoluteFile = path.resolve(contentRoot, article.file);
  ensureInside(contentRoot, absoluteFile, `article ${article.id}`);
  if (!fs.existsSync(absoluteFile) || !fs.statSync(absoluteFile).isFile()) {
    fail(`article file not found: ${absoluteFile}`);
  }

  const explicitId = frontMatterId(absoluteFile);
  const defaultId = relativeFile.replace(/\.(md|mdx)$/i, '');
  const directoryId = path.posix.dirname(defaultId);
  const docId = explicitId
    ? directoryId === '.'
      ? explicitId
      : `${directoryId}/${explicitId}`
    : defaultId;
  if (!docId) fail(`cannot derive Docusaurus doc id for article ${article.id}`);
  if (seenDocIds.has(docId)) fail(`duplicate Docusaurus doc id: ${docId}`);

  seenDocIds.add(docId);
  docIdByArticleId.set(article.id, docId);
  include.push(relativeFile);
}

const groups = Array.isArray(version.groups) ? [...version.groups] : [];
groups.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

const sidebarItems = groups.map((group) => {
  const ids = Array.isArray(group.articles) ? group.articles : [];
  const items = ids.map((articleId) => {
    const article = articleById.get(articleId);
    if (!article) fail(`group ${group.id ?? group.title} references unknown article: ${articleId}`);
    const docId = docIdByArticleId.get(articleId);
    return {
      type: 'doc',
      id: docId,
      label: article.title,
    };
  });

  return {
    type: 'category',
    label: group.title ?? group.id,
    collapsed: false,
    items,
  };
});

const docsPath = toPosix(path.relative(siteDir, contentRoot) || '.');
const manifestRelative = toPosix(path.relative(siteDir, manifestPath) || path.basename(manifestPath));

const generated = {
  schema_version: 1,
  generated_by: 'build-dev-whitepaper',
  manifest: manifestRelative,
  version: version.id,
  docsPath,
  include,
  sidebar: {
    whitepaperSidebar: sidebarItems,
  },
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(generated, null, 2)}\n`, 'utf8');
console.log(`[build-dev-whitepaper] projected ${articles.length} articles for ${version.id}`);
console.log(`[build-dev-whitepaper] wrote ${outputPath}`);
