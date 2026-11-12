import { copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, realpathSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"

const repoRoot = path.resolve(import.meta.dirname, "..")
const projectRoot = process.cwd()
const outputDir = path.join(projectRoot, "dist", "licenses")
const project = JSON.parse(readFileSync(path.join(projectRoot, "package.json"), "utf8"))

if (!existsSync(path.join(projectRoot, "dist"))) {
  throw new Error("Build the project before copying its license files")
}

mkdirSync(outputDir, { recursive: true })
for (const name of ["LICENSE", "NOTICE", "LICENSING.md", "CONTRIBUTORS.md", "THIRD_PARTY_NOTICES.md"]) {
  copyFileSync(path.join(repoRoot, name), path.join(outputDir, name))
}

for (const font of ["jetbrains-mono", "plus-jakarta-sans"]) {
  const packageName = `@fontsource-variable/${font}`
  if (project.dependencies?.[packageName]) {
    copyFileSync(
      path.join(projectRoot, "node_modules", packageName, "LICENSE"),
      path.join(outputDir, `${font}-LICENSE.txt`),
    )
  }
}

// Preserve Lucide's full notice, including the MIT attribution for Feather icons.
if (project.dependencies?.["lucide-react"]) {
  copyFileSync(
    path.join(projectRoot, "node_modules", "lucide-react", "LICENSE"),
    path.join(outputDir, "lucide-react-LICENSE.txt"),
  )
}

// Pagefind emits assets outside Vite's bundle graph and has its own notice directory.
if (project.dependencies?.["@astrojs/starlight"]) {
  const starlightPackage = realpathSync(
    path.join(projectRoot, "node_modules", "@astrojs", "starlight", "package.json"),
  )
  const searchPaths = createRequire(starlightPackage).resolve.paths("pagefind") ?? []
  const pagefindRoot = searchPaths
    .map((directory) => path.join(directory, "pagefind"))
    .find((directory) => existsSync(path.join(directory, "package.json")))
  if (!pagefindRoot) {
    throw new Error("Pagefind's license directory could not be located")
  }
  cpSync(path.join(pagefindRoot, "LICENSE"), path.join(outputDir, "pagefind"), { recursive: true })
}
