#!/usr/bin/env python3
"""Execute the actual issue dispatcher with mocked GitHub APIs; never dispatch live."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.load((ROOT / '.github/workflows/bot-dispatch.yml').read_text(encoding='utf-8'),
                     Loader=yaml.BaseLoader)
SCRIPT = WORKFLOW['jobs']['dispatch']['steps'][0]['with']['script']
NODE = shutil.which('node') or shutil.which('node.exe')
HARNESS = r'''
let data = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => data += chunk);
process.stdin.on('end', async () => {
  const input = JSON.parse(data);
  const calls = [];
  let gets = 0;
  const github = {rest: {
    issues: {
      get: async () => ({data: gets++ && input.latestIssue ? input.latestIssue : input.issue}),
      listForRepo: 'issues',
      addLabels: async args => {calls.push({kind: 'label', args});}
    },
    pulls: {list: 'prs', listFiles: 'files'},
    repos: {getCollaboratorPermissionLevel: async args => {
      calls.push({kind: 'permission', username: args.username});
      if (input.permissionError) throw Error('permission lookup failed');
      return {data: {permission: input.permissions[args.username] || 'read'}};
    }}
  }};
  github.paginate = async (method, args) => {
    calls.push({kind: 'list', method, args});
    if (input.listError === method) throw Error('list lookup failed');
    if (method === 'issues') return input.activeIssues || [];
    if (method === 'prs') return input.prs || [];
    if (method === 'files') return (input.files || {})[args.pull_number] || [];
    throw Error('Unexpected API');
  };
  const context = {repo: {owner: 'fixture-owner', repo: 'fixture-repo'}, actor: input.actor,
    payload: {issue: {number: 42}}};
  try {
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    await new AsyncFunction('github', 'context', 'core', input.script)(github, context, {info: () => {}});
    console.log(JSON.stringify({calls}));
  } catch (error) {
    console.log(JSON.stringify({calls, error: error.message}));
  }
});
'''


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.body = ('### Task category\n\nDocumentation\n\n'
                     '### Allowed paths\n\nreadme.md\n\n'
                     '### Requested change\n\nFix the documented typo.\n\n'
                     '### Acceptance criteria\n\nOnly the typo changes; checks pass.\n\n'
                     '### Validation command\n\npython3 scripts/governance-docs-check.py\n\n'
                     '### Authorization\n\n- [x] I authorize Jules to implement only this scoped task.\n'
                     '- [x] I verified dependencies, available quota, and exclusive file ownership.')
        self.input = {'script': SCRIPT, 'actor': 'maintainer',
                      'permissions': {'maintainer': 'admin'},
                      'issue': {'number': 42, 'state': 'open', 'user': {'login': 'maintainer'},
                                'labels': [{'name': 'bot:request'}], 'body': self.body}}

    def run_dispatch(self, expected, expect_error=False):
        self.assertIsNotNone(NODE, 'Node.js is required to execute the github-script regression')
        result = subprocess.run([NODE, '-e', HARNESS], input=json.dumps(self.input),
                                text=True, encoding='utf-8', capture_output=True, check=True)
        output = json.loads(result.stdout)
        if expect_error:
            self.assertIn('error', output, output)
        else:
            self.assertNotIn('error', output, output)
        labels = [call for call in output['calls'] if call['kind'] == 'label']
        self.assertEqual(len(labels), int(expected), output)
        if expected:
            self.assertEqual(labels[0]['args'], {'owner': 'fixture-owner', 'repo': 'fixture-repo',
                                                'issue_number': 42, 'labels': ['jules']})
        return output

    def test_authorized_documentation_and_test_requests(self):
        for category, paths in [('Documentation', 'readme.md'),
                                ('Documentation', 'README.md'),
                                ('Tests', 'tests/tools/example.py\ntests/package-readiness.py')]:
            with self.subTest(category=category):
                self.input['issue']['body'] = self.body.replace('Documentation', category).replace('readme.md', paths)
                self.run_dispatch(True)

    def test_exactly_three_paths_and_nested_docs_path_are_allowed(self):
        for paths in ('tests/a.py\ntests/b.sh\ndocs/howto.md',
                      'docs/guides/setup.md'):
            with self.subTest(paths=paths):
                self.input['issue']['body'] = self.body.replace('readme.md', paths).replace('Documentation', 'Tests')
                self.run_dispatch(True)

    def test_live_permission_is_required_for_author_and_actor(self):
        for target in ('actor', 'author'):
            with self.subTest(target=target):
                saved = copy.deepcopy(self.input)
                if target == 'actor':
                    self.input['actor'] = 'outsider'
                else:
                    self.input['issue']['user']['login'] = 'outsider'
                    self.input['issue']['author_association'] = 'OWNER'
                self.run_dispatch(False)
                self.input = saved

    def test_write_and_maintain_permissions_are_required_for_both_people(self):
        self.input['issue']['user']['login'] = 'issue-author'
        self.input['actor'] = 'trigger-actor'
        for author_permission, actor_permission in (('write', 'maintain'),
                                                      ('maintain', 'write')):
            with self.subTest(author=author_permission, actor=actor_permission):
                self.input['permissions'] = {'issue-author': author_permission,
                                             'trigger-actor': actor_permission}
                output = self.run_dispatch(True)
                permission_calls = [call['username'] for call in output['calls']
                                    if call['kind'] == 'permission']
                self.assertCountEqual(permission_calls, ['issue-author', 'trigger-actor'])

        for person in ('issue-author', 'trigger-actor'):
            for permission in ('triage', 'read'):
                with self.subTest(person=person, permission=permission):
                    self.input['permissions'] = {'issue-author': 'write',
                                                 'trigger-actor': 'maintain'}
                    self.input['permissions'][person] = permission
                    self.run_dispatch(False)

    def test_bot_cannot_dispatch(self):
        self.input['actor'] = 'github-actions[bot]'
        self.input['permissions'][self.input['actor']] = 'admin'
        self.run_dispatch(False)

    def test_closed_pull_request_and_removed_request_label(self):
        for patch in ({'state': 'closed'}, {'pull_request': {}}, {'labels': []}):
            with self.subTest(patch=patch):
                original = copy.deepcopy(self.input['issue'])
                self.input['issue'].update(patch)
                self.run_dispatch(False)
                self.input['issue'] = original

    def test_protected_and_already_dispatched_tasks(self):
        for name in ('risk:high', 'security', 'data-loss', 'arm64', 'qemu',
                     'kernel', 'power', 'firmware', 'storage', 'build',
                     'needs:hardware-test', 'hardware-testing', 'phase-acceptance',
                     'agent:codex', 'jules', 'dependencies', 'ci', 'docker', 'guest'):
            with self.subTest(name=name):
                self.input['issue']['labels'] = [{'name': 'bot:request'}, {'name': name}]
                self.run_dispatch(False)

    def test_paths_are_literal_and_limited(self):
        for path in ('src/install.sh', '.github/workflows/test.yml', '../readme.md',
                     'tests/../src/install.sh', 'tests/**', 'tests/a.py;echo x',
                     'docs/AI_RULES.md', 'docs/ADR/0008-test.md', 'docs/ci.md',
                     'docs/platforms.md', 'docs/lessons/governance.md',
                     'tests/qemu-patches.sh', 'tests/surveillance/installer.py',
                     'tests/governance-docs.py', 'tests/test_power.py', 'tests/reliability.py',
                     'power/bq25970_charger.c', 'dts/xiaomi-umi-battery.dtsi',
                     'patches/panel-xiaomi-umi.c', 'initramfs/init',
                     'docs/archive/test.md',
                     'tests/a.py\ntests/b.py\ntests/c.py\ntests/d.py', ''):
            with self.subTest(path=path):
                self.input['issue']['body'] = self.body.replace('readme.md', path)
                self.run_dispatch(False)

    def test_nested_protected_test_paths_cannot_bypass_exclusions(self):
        """The Tests allowlist keeps protected families blocked at every nesting depth."""
        paths = (
            'tests/nested/qemu-x.sh',
            'tests/nested/surveillance-probe.py',
            'tests/nested/arm-runtime.py',
            'tests/nested/production-check.py',
            'tests/nested/official-pat.py',
            'tests/nested/bootloader-audit.py',
            'tests/nested/ci-policy.py',
            'tests/nested/bot-dispatch-extra.py',
            'tests/nested/jules-setup-helper.py',
            'tests/nested/proprietary-check.py',
            'tests/nested/x86-installer-check.py',
            'tests/nested/platform.snapshot.py',
            'tests/nested/more/fixtures/sample.py',
            'tests/nested/more/dev/helper.sh',
        )
        for path in paths:
            with self.subTest(path=path):
                self.input['issue']['body'] = self.body.replace('Documentation', 'Tests').replace('readme.md', path)
                self.run_dispatch(False)

    def test_pat_acquisition_wrapper_is_excluded_at_any_depth(self):
        """The dispatch wrapper is protected, while unrelated nested tests remain eligible."""
        for path in ('tests/pat-acquisition.sh',
                     'tests/nested/pat-acquisition.sh',
                     'tests/nested/more/pat-acquisition.sh'):
            with self.subTest(path=path):
                self.input['issue']['body'] = self.body.replace('Documentation', 'Tests').replace('readme.md', path)
                self.run_dispatch(False)

        self.input['issue']['body'] = self.body.replace('Documentation', 'Tests').replace(
            'readme.md', 'tests/nested/ordinary-regression.py')
        self.run_dispatch(True)

    def test_missing_fields_approval_and_ambiguous_headings(self):
        for body in (None, '', self.body.replace('[x]', '[ ]'),
                     self.body.replace('Documentation', 'Runtime'),
                     self.body.replace('### Validation command', '### Missing command'),
                     self.body.replace('### Acceptance criteria', '### Missing criteria'),
                     self.body.replace('[x] I verified', '[ ] I verified'),
                     self.body + '\n### Allowed paths\nreadme.md'):
            with self.subTest(body=body):
                self.input['issue']['body'] = body
                self.run_dispatch(False)

    def test_crlf_issue_body(self):
        self.input['issue']['body'] = self.body.replace('\n', '\r\n')
        self.run_dispatch(True)

    def test_authorization_checkbox_is_case_insensitive(self):
        self.input['issue']['body'] = self.body.replace('[x]', '[X]')
        self.run_dispatch(True)

    def test_api_failure_stops_without_label(self):
        self.input['permissionError'] = True
        output = self.run_dispatch(False, expect_error=True)
        self.assertIn('permission lookup failed', output['error'])

    def test_workflow_uses_minimal_permissions_and_no_checkout(self):
        self.assertEqual(WORKFLOW['permissions'], {'issues': 'write', 'pull-requests': 'read'})
        self.assertEqual(WORKFLOW['concurrency']['group'], 'bot-dispatch-${{ github.repository }}')
        self.assertEqual(WORKFLOW['concurrency']['cancel-in-progress'], 'false')
        self.assertEqual(WORKFLOW['on']['issues']['types'], ['opened', 'labeled', 'reopened'])
        self.assertEqual(len(WORKFLOW['jobs']['dispatch']['steps']), 1)
        self.assertRegex(WORKFLOW['jobs']['dispatch']['steps'][0]['uses'],
                         r'^actions/github-script@[0-9a-f]{40}$')
        self.assertNotIn('$' + '{{', SCRIPT)
        template = yaml.safe_load((ROOT / '.github/ISSUE_TEMPLATE/0-bot-task.yml').read_text(encoding='utf-8'))
        self.assertEqual(template['labels'], ['bot:request'])
        category = next(item for item in template['body'] if item.get('id') == 'category')
        self.assertEqual(category['attributes']['options'], ['Documentation', 'Tests', 'Tooling'])

    def test_tooling_requires_admitted_bundle_and_implementation(self):
        """Only the admitted tool and its companion files can enter Tooling."""
        for paths, accepted in (
            ('scripts/dev/summarize-test-results.py', True),
            ('scripts/dev/summarize-test-results.py\ntests/dev/summarize-test-results.py\ndocs/dev/test-results.md', True),
            ('tests/dev/summarize-test-results.py', False),
            ('scripts/dev/arbitrary.py', False),
            ('scripts/jules-setup.sh', False),
            ('scripts/check-bootloader-admission.py', False),
            ('scripts/dev/summarize-test-results.py\nreadme.md', False),
            ('scripts/dev/summarize-test-results.py\n' * 7, False),
        ):
            with self.subTest(paths=paths):
                self.input['issue']['body'] = self.body.replace('Documentation', 'Tooling').replace('readme.md', paths)
                self.run_dispatch(accepted)

    def test_categories_cannot_bypass_protected_paths(self):
        """A test extension or documentation category is not permission to edit a gate."""
        for category in ('Documentation', 'Tests', 'Tooling'):
            for path in ('tests/bootloader-component-admission.py', 'tests/bot-dispatch.py',
                         'tests/ci-policy.py', 'tests/jules-setup.py', 'tests/arm-runtime.py', 'tests/platform.sh',
                         'docs/bot-automation.md', 'docs/jules-environment.md',
                         'docs/implementation-plan.md', 'docs/dependency-locks.md',
                         'readme.md\nreadme.md'):
                with self.subTest(category=category, path=path):
                    self.input['issue']['body'] = self.body.replace('Documentation', category).replace('readme.md', path)
                    self.run_dispatch(False)

    def test_open_task_scopes_and_pilot_capacity(self):
        """Reserve paths until issues close; unknown scope fails closed."""
        other = {'number': 10, 'body': self.body.replace('readme.md', 'docs/other.md')}
        for active, accepted in (([other], True),
                                 ([{**other, 'number': n} for n in range(3)], True),
                                 ([{**other, 'number': n} for n in range(4)], False),
                                 ([{'number': 10, 'body': self.body}], False),
                                 ([{'number': 10, 'body': ''}], False),
                                 ([{'number': 10, 'body': self.body.replace('readme.md', 'docs/**')}], False),
                                 ([self.input['issue']], True)):
            with self.subTest(active=active):
                self.input['activeIssues'] = active
                self.run_dispatch(accepted)

    def test_all_open_pr_files_and_renames_reserve_paths(self):
        """Check unlabelled PRs too, including old paths of renamed files."""
        self.input['prs'] = [{'number': 9, 'labels': []}]
        for files, accepted in (([{'filename': 'docs/other.md'}], True),
                                 ([{'filename': 'readme.md'}], False),
                                 ([{'filename': 'other.md', 'previous_filename': 'readme.md'}], False),
                                 ([{'filename': 'other.md'}] * 3000, False)):
            with self.subTest(count=len(files), accepted=accepted):
                self.input['files'] = {'9': files}
                self.run_dispatch(accepted)

    def test_pr_backlog_stops_dispatch(self):
        """Count all open Jules PRs conservatively, including drafts."""
        self.input['prs'] = [{'number': n, 'labels': [{'name': 'jules'}], 'draft': True}
                             for n in range(5)]
        self.run_dispatch(False)
        self.input['prs'].pop()
        self.run_dispatch(True)

    def test_scope_lookup_failures_do_not_write_labels(self):
        """Incomplete remote evidence never permits dispatch."""
        self.input['prs'] = [{'number': 9, 'labels': []}]
        for method in ('issues', 'prs', 'files'):
            with self.subTest(method=method):
                self.input['listError'] = method
                self.run_dispatch(False, expect_error=True)

    def test_issue_changed_during_check_is_rejected(self):
        """Recheck body, state and ownership immediately before requesting Jules."""
        for patch in ({'body': self.body + '\nchanged'}, {'state': 'closed'},
                      {'labels': []}, {'labels': [{'name': 'bot:request'}, {'name': 'jules'}]}):
            with self.subTest(patch=patch):
                self.input['latestIssue'] = {**self.input['issue'], **patch}
                self.run_dispatch(False)


if __name__ == '__main__':
    unittest.main()
