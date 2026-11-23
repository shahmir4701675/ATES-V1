import { brotliCompressSync, constants, gzipSync } from 'node:zlib'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve, sep } from 'node:path'

/** Uses Node built-ins only; no compression plugin/runtime dependency. */
export default function precompress() {
  return { name: 'precompressed-static-assets', apply: 'build', writeBundle(options, bundle) {
    const root = resolve(options.dir)
    // Vite rewrites preload references during generateBundle. Compress only
    // final bytes already written to disk, never an earlier in-memory chunk.
    for (const name of Object.keys(bundle)) {
      if (!/\.(js|css|svg)$/.test(name)) continue
      const file = resolve(root, name)
      if (!file.startsWith(root + sep)) throw new Error('Asset escaped the build directory')
      const source = readFileSync(file)
      for (const [extension, compressed] of [
        ['gz', gzipSync(source, { level: 6 })],
        ['br', brotliCompressSync(source, { params: { [constants.BROTLI_PARAM_QUALITY]: 5 } })],
      ]) {
        if (compressed.length < source.length) writeFileSync(`${file}.${extension}`, compressed)
      }
    }
  } }
}
