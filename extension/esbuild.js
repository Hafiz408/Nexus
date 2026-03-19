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
    // Extension host bundle — must succeed
    await extCtx.rebuild();
    await extCtx.dispose();

    // Webview bundle — may fail if src/webview/index.tsx not yet created (Plans 03+)
    try {
      await webCtx.rebuild();
      await webCtx.dispose();
    } catch (webviewErr) {
      await webCtx.dispose();
      console.warn('Webview bundle skipped (entry point not yet created):', webviewErr.message.split('\n')[0]);
    }

    console.log('Build complete.');
  }
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});
