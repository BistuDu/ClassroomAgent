"""Real installed SDK discovery, restricted reads, and per-run snapshots."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import ROOT
from backend.courses import Courses, DomainError
from backend.document_tools import page_text
from backend.skills import SkillRegistry
from backend.store import Store


class Skills(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'data')
        self.root = Path(self.temp.name)
        self.skills = self.root / 'skills' / 'agent-runtime'
        self.skills.mkdir(parents=True)
        self.add('slide-craft', '首次正文', 'description: |\n  普通页面设计\n  生成和修改页面时读取')

    def tearDown(self):
        self.temp.cleanup()

    def add(self, directory, body, description='description: 页面设计', name=None):
        folder = self.skills / directory
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'SKILL.md').write_text(f'---\nname: {name or directory}\n{description}\n---\n{body}', encoding='utf-8')
        return folder

    def test_sdk_yaml_alias_reference_pagination_and_permissions(self):
        folder = self.skills / 'slide-craft'
        (folder / 'references').mkdir()
        (folder / 'references' / 'layout.md').write_text('布局规范' * 80, encoding='utf-8')
        (folder / 'assets').mkdir()
        (folder / 'assets' / 'template.json').write_text('{"width":1280}', encoding='utf-8')
        (folder / 'assets' / 'bad.png').write_bytes(b'not text')
        outside = self.root / 'secret.md'
        outside.write_text('不应读取', encoding='utf-8')
        (folder / 'references' / 'escape.md').symlink_to(outside)
        (self.skills / 'escape').symlink_to(self.root, target_is_directory=True)
        registry = SkillRegistry(self.root)
        self.assertEqual([s['skillId'] for s in registry.index()], ['slide-craft'])
        self.assertIn('普通页面设计', registry.index()[0]['description'])
        self.assertEqual(registry.read('slides')['text'], registry.read('slide-craft')['text'])
        self.assertEqual(registry.read('slides')['requestedId'], 'slides')
        text = registry.read('slide-craft', 'references/layout.md')['text']
        first = page_text(text, 0, 100)
        second = page_text(text, first['nextOffset'], 1000)
        self.assertEqual(first['text'] + second['text'], text)
        self.assertFalse(second['hasMore'])
        self.assertEqual(registry.read('slide-craft', 'assets/template.json')['text'], '{"width":1280}')
        for requested in ['', '/etc/passwd', '../secret.md', 'references/../SKILL.md', './SKILL.md',
                          'references//layout.md', 'references\\layout.md', 'assets/bad.png',
                          'references/escape.md', 'course.md', 'references/missing.md']:
            with self.subTest(path=requested), self.assertRaises(DomainError) as denied:
                registry.read('slide-craft', requested)
            self.assertEqual(denied.exception.code, 'SKILL_SCOPE')
        with self.assertRaises(DomainError) as unpublished:
            registry.read('slides', 'references/layout.md')
        self.assertEqual(unpublished.exception.code, 'SKILL_SCOPE')
        with self.assertRaises(DomainError) as unknown:
            registry.read('unregistered')
        self.assertEqual(unknown.exception.code, 'SKILL_NOT_FOUND')
        self.assertTrue(any('越界' in d['message'] for d in registry.snapshot().public()['diagnostics']))

    def test_invalid_frontmatter_and_collision_diagnostics(self):
        self.add('duplicate', '重复正文', name='slide-craft')
        self.add('missing-description', '缺描述', description='other: value')
        self.add('invalid-yaml', '错误 YAML', description='description: [unclosed')
        self.add('invalid-name', '错误名称', name='Invalid_Name')
        self.add('missing-name', '缺名称')
        (self.skills / 'missing-name' / 'SKILL.md').write_text('---\ndescription: 缺少名称\n---\n正文', encoding='utf-8')
        self.add('no-frontmatter', '正文')
        (self.skills / 'no-frontmatter' / 'SKILL.md').write_text('name: fake\ndescription: fake', encoding='utf-8')
        registry = SkillRegistry(self.root)
        self.assertEqual(len(registry.index()), 1)
        diagnostics = registry.snapshot().public()['diagnostics']
        self.assertTrue(any(d['type'] == 'collision' for d in diagnostics))
        for name in ['missing-description', 'invalid-yaml', 'invalid-name', 'missing-name', 'no-frontmatter']:
            self.assertTrue(any(d.get('path', '').startswith(name + '/') for d in diagnostics), name)

    def test_reload_added_changed_removed_without_replacing_active_run(self):
        store = Store(self.root / 'test.sqlite3')
        try:
            with patch('backend.config.ROOT', self.root):
                courses = Courses(store)
            initial = courses.begin_skill_run('old-run')
            old_text = courses.read_skill('slides', run_id='old-run')['text']
            self.add('slide-craft', '更新后的正文')
            self.add('new-skill', '新增技能')
            reloaded = courses.reload_skills()
            self.assertEqual(reloaded['changes']['changed'], ['slide-craft'])
            self.assertEqual(reloaded['changes']['added'], ['new-skill'])
            self.assertEqual(courses.read_skill('slides', run_id='old-run')['text'], old_text)
            new = courses.begin_skill_run('new-run')
            self.assertNotEqual(initial['version'], new['version'])
            self.assertIn('更新后的正文', courses.read_skill('slides', run_id='new-run')['text'])
            with self.assertRaises(DomainError):
                courses.read_skill('new-skill', run_id='old-run')
            (self.skills / 'new-skill' / 'SKILL.md').unlink()
            self.assertEqual(courses.reload_skills()['changes']['removed'], ['new-skill'])
            self.assertIn('新增技能', courses.read_skill('new-skill', run_id='new-run')['text'])
            courses.end_skill_run('old-run')
            courses.end_skill_run('new-run')
            self.assertEqual(courses.skill_runs, {})
        finally:
            store.close()

    def test_missing_resources_and_sdk_process_failure_report_diagnostics(self):
        registry = SkillRegistry(self.root / 'missing-project')
        public = registry.snapshot().public()
        self.assertEqual(public['skills'], [])
        self.assertTrue(public['loadError'])
        self.assertTrue(public['diagnostics'])
        with patch('backend.skills.subprocess.run', side_effect=OSError('node unavailable')):
            unavailable = registry.reload()
        self.assertEqual(unavailable['skills'], [])
        self.assertIn('OSError', unavailable['loadError'])


if __name__ == '__main__':
    unittest.main()
