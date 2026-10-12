import { createHash } from 'node:crypto';
import { readFile, readdir, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createExtensionRuntime, DefaultResourceLoader, parseFrontmatter, type ResourceDiagnostic, type ResourceLoader, type Skill } from '@earendil-works/pi-coding-agent';

const textSuffixes = new Set(['.md', '.txt', '.json', '.yaml', '.yml', '.css', '.js', '.html']);
const inside = (root: string, target: string) => target === root || target.startsWith(root + path.sep);
const posix = (value: string) => value.split(path.sep).join('/');
export type SkillIndex = {skillId: string; title: string; command: string; bodyHash: string; bodyBytes: number; description: string; path: string; version: string; disableModelInvocation: boolean};
export type SkillResources = {
 version: string; legacyReads?: Record<string,{canonicalId:string;path:string;bodyHash:string;bodyBytes:number;skillVersion:string}>; skills: SkillIndex[]; diagnostics: ResourceDiagnostic[]; loadError?: string;
};
type Snapshot = SkillResources & {resources: Record<string, Record<string, string>>};

function pinnedSkills(root: string, resources: SkillResources): Skill[] {
 return resources.skills.map(item => ({name: item.skillId, description: item.description,
  filePath: path.join(root, 'skills', 'agent-runtime', item.path),
  baseDir: path.dirname(path.join(root, 'skills', 'agent-runtime', item.path)),
  disableModelInvocation: item.disableModelInvocation,
  sourceInfo: {source:'local',scope:'project',origin:'top-level',path:item.path}}));
}

export function createSkillLoader(root: string, agentDir: string, system: string, resources: SkillResources) {
 return new DefaultResourceLoader({cwd: root, agentDir, additionalSkillPaths: [],
  noSkills: true, noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
  systemPrompt: system,
  skillsOverride: () => ({skills: pinnedSkills(root, resources), diagnostics: resources.diagnostics}),
  systemPromptOverride: base => {
   const index = resources.skills.filter(s => !s.disableModelInvocation).map(s =>
    `- ${s.skillId}: ${s.description} (读取：read_skill ${JSON.stringify({skillId: s.skillId, path: 'SKILL.md'})}; 根路径：${s.path})`).join('\n');
   return (base ?? system) + (index ? `\n<available_course_skills>\n${index}\n</available_course_skills>\n` +
    'Skill 正文不会自动注入。按需使用 read_skill 和同一 Skill 内的相对 path。' : '');
  }});
}

export function minimalSkillLoader(system: string, resources: SkillResources): ResourceLoader {
 const extensions={extensions:[],errors:[],runtime:createExtensionRuntime()};
 return {
  getSkills: () => ({skills:[],diagnostics:resources.diagnostics}),
  getExtensions: () => extensions,
  getPrompts: () => ({prompts:[],diagnostics:[]}), getThemes: () => ({themes:[],diagnostics:[]}),
  getAgentsFiles: () => ({agentsFiles:[]}), getSystemPrompt: () => system,
  getSystemPromptSource: () => undefined, getAppendSystemPrompt: () => [], getAppendSystemPromptSources: () => [],
  extendResources: () => {}, reload: async () => {},
 };
}

export async function discoverSkills(root: string, agentDir: string): Promise<Snapshot> {
 const skillRoot = path.join(root, 'skills', 'agent-runtime');
 const diagnostics: ResourceDiagnostic[] = [];
 const resources: Snapshot['resources'] = {};
 const seen = new Set<string>();
 const files: string[] = [];
 const diagnostic = (message: string, file: string) => diagnostics.push({type: 'warning', message, path: file});
 try {
  const boundary = await realpath(skillRoot);
  if (!inside(await realpath(root), boundary)) throw Error('Skill 根目录超出项目范围');
  // Enumerate within the boundary before handing files to the SDK's parser.
  async function walk(directory: string) {
   const resolved = await realpath(directory);
   if (!inside(boundary, resolved)) {diagnostic('Skill 目录或符号链接越界', directory); return;}
   if (seen.has(resolved)) return;
   seen.add(resolved);
   const entries = await readdir(directory, {withFileTypes: true});
   if (entries.some(e => e.name === 'SKILL.md')) {
    const file = path.join(directory, 'SKILL.md');
    try {
     if (inside(boundary, await realpath(file)) && (await stat(file)).isFile()) files.push(file);
     else diagnostic('Skill 文件或符号链接越界', file);
    } catch (error) {diagnostic(String(error),file);}
    return;
   }
   for (const entry of entries.sort((a,b) => a.name.localeCompare(b.name))) {
    if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
    const target = path.join(directory, entry.name);
    try {if ((await stat(target)).isDirectory()) await walk(target);}
    catch (error) {diagnostic(String(error), target);}
   }
  }
  await walk(skillRoot);
  const bodies = new Map<string, string>();
  const validFiles: string[] = [];
  for (const file of files) {
   try {
    const text = await readFile(file, 'utf8');
    const {frontmatter} = parseFrontmatter(text);
    const name = frontmatter.name, description = frontmatter.description;
    if (typeof name !== 'string' || name.length > 64 || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name))
     throw Error('Skill 必须提供有效的 name');
    if (typeof description !== 'string' || !description.trim() || description.length > 1024)
     throw Error('Skill 必须提供非空且不超过 1024 字符的 description');
    bodies.set(file, text); validFiles.push(file);
   } catch (error) {diagnostic(String(error), file);}
  }
  const loader = new DefaultResourceLoader({cwd: root, agentDir, additionalSkillPaths: validFiles,
   noSkills: true, noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true});
  await loader.reload();
  const result = loader.getSkills();
  diagnostics.push(...result.diagnostics);
  const skills: SkillIndex[] = [];
  for (const skill of result.skills) {
   if (await readFile(skill.filePath,'utf8') !== bodies.get(skill.filePath)) {
    diagnostic('Skill 文件在发现期间发生变化，本轮跳过；请重新加载',skill.filePath); continue;
   }
   const directory = await realpath(path.dirname(skill.filePath));
   const texts: Record<string, string> = {'SKILL.md': bodies.get(skill.filePath)!};
   const visited = new Set<string>();
   async function collect(folder: string) {
    const resolved = await realpath(folder);
    if (!inside(directory, resolved)) {diagnostic('Skill 资源或符号链接越界', folder); return;}
    if (visited.has(resolved)) return;
    visited.add(resolved);
    for (const entry of (await readdir(folder, {withFileTypes: true})).sort((a,b) => a.name.localeCompare(b.name))) {
     if (entry.name.startsWith('.')) continue;
     const target = path.join(folder, entry.name);
     try {
      if (!inside(directory, await realpath(target))) {diagnostic('Skill 资源或符号链接越界', target); continue;}
      const info = await stat(target);
      if (info.isDirectory()) await collect(target);
      else if (info.isFile() && textSuffixes.has(path.extname(target).toLowerCase())) {
       if (info.size > 2_000_000) {diagnostic('Skill 文本资源超过 2 MB', target); continue;}
       texts[posix(path.relative(path.dirname(skill.filePath), target))] = await readFile(target, 'utf8');
      }
     } catch (error) {diagnostic(String(error), target);}
    }
   }
   for (const folder of ['references', 'assets']) {
    const target = path.join(path.dirname(skill.filePath), folder);
    try {await collect(target);} catch (error: any) {if (error.code !== 'ENOENT') diagnostic(String(error), target);}
   }
   resources[skill.name] = texts;
   const version = createHash('sha256').update(JSON.stringify(texts)).digest('hex');
   const {frontmatter} = parseFrontmatter(texts['SKILL.md']);
   const metadata = frontmatter.metadata as Record<string, unknown> | undefined;
   const title = String(metadata?.title || frontmatter.title || skill.name);
   skills.push({skillId: skill.name, title, command: '/' + skill.name,
    bodyHash: createHash('sha256').update(texts['SKILL.md']).digest('hex'), bodyBytes: Buffer.byteLength(texts['SKILL.md']),
    description: skill.description, path: posix(path.relative(skillRoot, skill.filePath)),
    version, disableModelInvocation: skill.disableModelInvocation});
  }
  const version = createHash('sha256').update(JSON.stringify(skills)).digest('hex');
  return {version, skills, resources, diagnostics: diagnostics.map(d => ({...d,
   path: d.path ? posix(path.relative(skillRoot, d.path)) : undefined,
   collision: d.collision ? {...d.collision, winnerPath: posix(path.relative(skillRoot,d.collision.winnerPath)),
    loserPath: posix(path.relative(skillRoot,d.collision.loserPath))} : undefined}))};
 } catch (error) {
  return {version: 'unavailable', skills: [], resources: {}, diagnostics: [{type: 'error', message: String(error)}], loadError: String(error)};
 }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
 const root = await realpath(process.argv[2] || process.cwd());
 const result = await discoverSkills(root, path.join(root, 'data', 'pi'));
 process.stdout.write(JSON.stringify(result) + '\n');
}
