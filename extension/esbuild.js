const esbuild = require('esbuild');

const isWatch = process.argv.includes('--watch');

const baseConfig = {
  bundle: true,
  minify: false,
  sourcemap: true,
};

async function build() {
  // Extension host bundle
  const extCtx = await esbuild.context({
    ...baseConfig,
    platform: 'node',
    entryPoints: ['src/extension.ts'],
    outfile: 'out/extension.js',
    external: ['vscode'],
    format: 'cjs',
  });

  // Webview React bundle
  const webCtx = await esbuild.context({
    ...baseConfig,
    platform: 'browser',
    entryPoints: ['src/webview/index.tsx'],
    outfile: 'out/webview/index.js',
    format: 'iife',
  });

  if (isWatch) {
    await extCtx.watch();
    await webCtx.watch();
    console.log('Watching...');
  } else {
    await extCtx.rebuild();
    await webCtx.rebuild();
    await extCtx.dispose();
    await webCtx.dispose();
    console.log('Build complete.');
  }
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});
