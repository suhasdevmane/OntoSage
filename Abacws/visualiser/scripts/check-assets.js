#!/usr/bin/env node
/*
 Detect and fail if GLB assets are Git LFS pointer stubs. This prevents building an image that
 serves tiny text files instead of real 3D models, which results in a blank canvas.
*/
const fs = require('fs');
const path = require('path');

const assetsDir = path.join(__dirname, '..', 'public', 'assets');
const suspectGlbs = [];

function isPointerStub(buf) {
  // Git LFS pointer files are small text files that start with
  // 'version https://git-lfs.github.com/spec/v1' and contain 'oid sha256:'
  const txt = buf.toString('utf8');
  return txt.includes('git-lfs.github.com/spec/v1') && txt.includes('oid sha256:');
}

if (!fs.existsSync(assetsDir)) {
  process.exit(0);
}

for (const entry of fs.readdirSync(assetsDir)) {
  if (!entry.toLowerCase().endsWith('.glb')) continue;
  const p = path.join(assetsDir, entry);
  try {
    const stat = fs.statSync(p);
    if (stat.size <= 256) {
      const buf = fs.readFileSync(p);
      if (isPointerStub(buf)) suspectGlbs.push({ file: entry, size: stat.size });
    }
  } catch {}
}

if (suspectGlbs.length) {
  console.error('\n\x1b[31mERROR:\x1b[0m One or more GLB assets appear to be Git LFS pointer files (placeholders):');
  for (const s of suspectGlbs) console.error(` - ${s.file} (${s.size} bytes)`);
  console.error('\nFix this by installing Git LFS and pulling the real binaries:');
  console.error('  git lfs install');
  console.error('  git lfs pull');
  console.error('\nAlternatively, replace the files in visualiser/public/assets with actual GLB binaries.');
  process.exit(1);
}
