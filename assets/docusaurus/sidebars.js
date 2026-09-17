import fs from 'node:fs';

const generated = JSON.parse(
  fs.readFileSync(new URL('./whitepaper.generated.json', import.meta.url), 'utf8'),
);

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = generated.sidebar;

export default sidebars;
