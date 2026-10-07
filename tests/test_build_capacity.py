import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_capacity as c
import build as b


class Capacity(unittest.TestCase):
    def candidate_capacity_scripts(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/candidate.yml').read_text()
        self.assertNotIn('CMAKE_BUILD_PARALLEL_LEVEL: ${{ inputs.build_jobs }}', workflow)
        scripts = {}
        for job, following, first_child in (
                ('source', 'package', '    - if: runner.os'),
                ('sanitizer', 'distribution', '    - name: Explicit pinned Rust host preparation')):
            block = workflow.split('  ' + job + ':\n', 1)[1].split('  ' + following + ':\n', 1)[0]
            self.assertIn('      BUILD_JOBS: ${{ inputs.build_jobs }}', block)
            marker = '    - name: Resolve compile capacity\n'
            self.assertEqual(block.count(marker), 1)
            self.assertLess(block.index(marker), block.index(first_child))
            step = block.split(marker, 1)[1].split('    - ', 1)[0]
            self.assertIn('      shell: python\n', step)
            scripts[job] = textwrap.dedent(step.split('      run: |\n', 1)[1])
        return scripts

    def test_candidate_exports_resolved_auto_and_explicit_capacity_to_later_steps(self):
        for job, script in self.candidate_capacity_scripts().items():
            for selector, expected in (('auto', '3'), ('4', '4')):
                with self.subTest(job=job, selector=selector), tempfile.TemporaryDirectory() as temporary:
                    environment_file = Path(temporary) / 'environment'
                    environment_file.write_text('EXISTING=value\n', encoding='utf-8')
                    with patch.dict(os.environ, {'BUILD_JOBS': selector, 'GITHUB_ENV': str(environment_file)}), \
                            patch.object(c, 'default_jobs', return_value=3) as automatic, \
                            patch.object(sys, 'path', list(sys.path)):
                        exec(compile(script, 'candidate-' + job, 'exec'), {})
                    self.assertEqual(environment_file.read_text(encoding='utf-8'),
                                     'EXISTING=value\nCMAKE_BUILD_PARALLEL_LEVEL=' + expected + '\n')
                    self.assertEqual(automatic.call_count, 1 if selector == 'auto' else 0)

    def test_candidate_rejects_invalid_capacity_before_export(self):
        for job, script in self.candidate_capacity_scripts().items():
            for selector in ('0', '-1', '1.5', 'many'):
                with self.subTest(job=job, selector=selector), tempfile.TemporaryDirectory() as temporary:
                    environment_file = Path(temporary) / 'environment'
                    environment_file.write_text('EXISTING=value\n', encoding='utf-8')
                    with patch.dict(os.environ, {'BUILD_JOBS': selector, 'GITHUB_ENV': str(environment_file)}), \
                            patch.object(sys, 'path', list(sys.path)), \
                            self.assertRaisesRegex(ValueError, 'compile jobs must be auto or a positive integer'):
                        exec(compile(script, 'candidate-' + job, 'exec'), {})
                    self.assertEqual(environment_file.read_text(encoding='utf-8'), 'EXISTING=value\n')

    def test_candidate_descendant_cmake_build_uses_numeric_capacity(self):
        scripts = self.candidate_capacity_scripts()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source'; source.mkdir(); build = root / 'build'
            (source / 'CMakeLists.txt').write_text(
                'cmake_minimum_required(VERSION 3.21)\nproject(capacity NONE)\n'
                'add_custom_target(probe ALL COMMAND ${CMAKE_COMMAND} -E touch "${CMAKE_BINARY_DIR}/built")\n')
            environment = dict(os.environ, CMAKE_BUILD_PARALLEL_LEVEL='1')
            subprocess.run(['cmake', '-G', 'Ninja', '-S', str(source), '-B', str(build)],
                           env=environment, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            rejected = subprocess.run(['cmake', '--build', str(build)],
                                      env=dict(environment, CMAKE_BUILD_PARALLEL_LEVEL='auto'),
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('CMAKE_BUILD_PARALLEL_LEVEL', rejected.stdout)
            self.assertIn("'auto'", rejected.stdout)
            self.assertFalse((build / 'built').exists())
            for job, script in scripts.items():
                for selector in ('auto', '4'):
                    with self.subTest(job=job, selector=selector):
                        environment_file = root / 'environment'
                        environment_file.write_text('', encoding='utf-8')
                        with patch.dict(os.environ, {'BUILD_JOBS': selector, 'GITHUB_ENV': str(environment_file)}), \
                                patch.object(c, 'default_jobs', return_value=3), \
                                patch.object(sys, 'path', list(sys.path)):
                            exec(compile(script, 'candidate-' + job, 'exec'), {})
                        key, value = environment_file.read_text(encoding='utf-8').strip().split('=', 1)
                        subprocess.run(['cmake', '--build', str(build)], env=dict(environment, **{key: value}),
                                       check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                        self.assertTrue((build / 'built').is_file())
                        (build / 'built').unlink()

    def test_auto_and_explicit_compile_limits(self):
        with patch.object(c, 'default_jobs', return_value=7) as automatic:
            for value in (None, '', 'auto'):
                self.assertEqual(c.compile_jobs(value), 7)
            for value in (1, '2', 9):
                self.assertEqual(c.compile_jobs(value), int(value))
            self.assertEqual(automatic.call_count, 3)
        for value in (0, '0', '-1', '1.5', 'many', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.compile_jobs(value)

    def test_auto_and_explicit_test_limits(self):
        with patch.object(c, 'default_test_jobs', return_value=7) as automatic:
            for value in (None, '', 'auto'):
                self.assertEqual(c.test_jobs(value), 7)
            for value in (1, '2', 9):
                self.assertEqual(c.test_jobs(value), int(value))
            self.assertEqual(automatic.call_count, 3)
        for value in (0, '0', '-1', '1.5', 'many', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.test_jobs(value)

    def test_memory_reserve_and_cpu_headroom_are_independent(self):
        self.assertEqual(c.select_jobs(16, c.MEMORY_PER_JOB * 3), 2)
        self.assertEqual(c.select_jobs(2, 32 * 1024**3), 1)
        self.assertEqual(c.select_jobs(64, None), 2)
        self.assertEqual(c.select_jobs(32, 0), 1)

    def test_default_uses_tightest_container_limits(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(c.sys, 'platform', 'linux'), patch.object(c, 'usable_cpus', return_value=32), \
             patch.object(c, 'available_memory', return_value=64*1024**3), \
             patch.object(c, 'linux_limits', return_value=([4,2],[c.MEMORY_PER_JOB*2])):
            self.assertEqual(c.default_jobs(),1)
        with patch.object(c, 'usable_cpus', side_effect=ValueError('unavailable')):
            self.assertEqual(c.default_jobs(),1)

    def test_automatic_test_workers_observe_resources_without_fixed_cap(self):
        for cpus, memory, expected in [(16, 32 * 1024**3, 15),
                                      (3, 32 * 1024**3, 2),
                                      (16, c.MEMORY_PER_JOB * 3, 2),
                                      (16, None, 2), (1, 0, 1)]:
            with self.subTest(cpus=cpus, memory=memory), \
                    patch.dict(os.environ, {}, clear=True), \
                    patch.object(c.sys, 'platform', 'linux'), \
                    patch.object(c, 'usable_cpus', return_value=cpus), \
                    patch.object(c, 'available_memory', return_value=memory), \
                    patch.object(c, 'linux_limits', return_value=([], [])):
                self.assertEqual(c.default_test_jobs(), expected)
        with patch.object(c, 'usable_cpus', side_effect=OSError('unavailable')):
            self.assertEqual(c.default_test_jobs(), 1)

    def test_cpu_affinity_restricts_the_host_count(self):
        with patch.object(c.os, 'cpu_count', return_value=32), \
                patch.object(c.os, 'sched_getaffinity', return_value={2, 4}, create=True), \
                patch.object(c.sys, 'platform', 'linux'):
            self.assertEqual(c.usable_cpus(), 2)
            self.assertEqual(c.select_jobs(c.usable_cpus(), 32 * 1024**3), 1)

    def test_nested_automatic_limits_keep_parent_budget_and_explicit_overrides(self):
        args = argparse.Namespace(build_jobs=None, test_jobs=None, jobs=None)
        with patch.dict(os.environ, {c.WORKER_BUDGET: '3'}, clear=True), \
                patch.object(c.sys, 'platform', 'linux'), \
                patch.object(c, 'usable_cpus', return_value=64), \
                patch.object(c, 'available_memory', return_value=64 * 1024**3), \
                patch.object(c, 'linux_limits', return_value=([], [])):
            self.assertEqual(c.default_jobs(), 3)
            self.assertEqual(c.default_test_jobs(), 3)
            self.assertEqual(b.job_limits(args), (3, 3))
            args.jobs = 9
            self.assertEqual(b.job_limits(args), (9, 9))
            args.jobs = None
            with patch.dict(os.environ, {'CMAKE_BUILD_PARALLEL_LEVEL': '7',
                                         'CTEST_PARALLEL_LEVEL': '5'}):
                self.assertEqual(b.job_limits(args), (7, 5))

    def test_malformed_inherited_budget_never_becomes_full_host_capacity(self):
        for value in ('', 'auto', '0', '-1', '1.5', 'many'):
            with self.subTest(value=value), patch.dict(os.environ, {c.WORKER_BUDGET: value}), \
                    self.assertRaisesRegex(ValueError, c.WORKER_BUDGET):
                c.default_jobs()
        with patch.dict(os.environ, {c.WORKER_BUDGET: 'invalid'}):
            # A direct operator override does not invoke automatic admission.
            self.assertEqual(c.compile_jobs(5), 5)
            self.assertEqual(c.test_jobs(7), 7)

    def test_child_budget_divides_once_and_cannot_grow_at_a_nested_layer(self):
        parent = {'UNCHANGED': 'value'}
        with patch.object(c, 'default_jobs', return_value=15):
            child = c.worker_environment(parent, 4)
            grandchild = c.worker_environment(child, 2)
        self.assertEqual(parent, {'UNCHANGED': 'value'})
        self.assertEqual(child, {'UNCHANGED': 'value', c.WORKER_BUDGET: '3',
                                'CMAKE_BUILD_PARALLEL_LEVEL': '3', 'CTEST_PARALLEL_LEVEL': '3'})
        self.assertEqual(grandchild, {'UNCHANGED': 'value', c.WORKER_BUDGET: '1',
                                     'CMAKE_BUILD_PARALLEL_LEVEL': '1', 'CTEST_PARALLEL_LEVEL': '1'})
        self.assertLessEqual(4 * int(child[c.WORKER_BUDGET]), 15)
        self.assertLessEqual(2 * int(grandchild[c.WORKER_BUDGET]), 3)

    def test_child_budget_scopes_parent_explicit_and_resolved_defaults(self):
        for environment, capacity, expected in (
                ({}, 4, '1'),
                ({'CMAKE_BUILD_PARALLEL_LEVEL': '8'}, None, '2'),
                ({'CMAKE_BUILD_PARALLEL_LEVEL': 'auto'}, None, '3'),
                ({'CTEST_PARALLEL_LEVEL': '4'}, None, '1'),
                ({'CMAKE_BUILD_PARALLEL_LEVEL': '1', 'CTEST_PARALLEL_LEVEL': '1'}, 8, '2'),
                ({c.WORKER_BUDGET: '8'}, None, '2')):
            with self.subTest(environment=environment, capacity=capacity), \
                    patch.object(c, 'default_jobs', return_value=15):
                child = c.worker_environment(environment, 4, capacity=capacity)
            for key in (c.WORKER_BUDGET, 'CMAKE_BUILD_PARALLEL_LEVEL', 'CTEST_PARALLEL_LEVEL'):
                self.assertEqual(child[key], expected)
        with patch.object(c, 'default_jobs', return_value=1):
            self.assertEqual(c.worker_environment({}, 20)[c.WORKER_BUDGET], '1')
        for environment in ({c.WORKER_BUDGET: 'bad'}, {'CMAKE_BUILD_PARALLEL_LEVEL': 'bad'},
                            {'CTEST_PARALLEL_LEVEL': 'bad'}):
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                c.worker_environment(environment, 2)

    def test_child_process_receives_budget_without_changing_parent(self):
        parent = dict(os.environ)
        child = c.worker_environment(parent, 1, capacity=1)
        program = ('import sys; sys.path.insert(0, sys.argv[1]); import build_capacity as c; '
                   'print(c.default_jobs(), c.default_test_jobs(), c.compile_jobs(5), c.test_jobs(7))')
        actual = subprocess.check_output([sys.executable, '-B', '-c', program,
                                          str(Path(c.__file__).parent)], env=child, text=True)
        self.assertEqual(actual.strip(), '1 1 5 7')
        self.assertEqual(dict(os.environ), parent)

    def test_build_wrapper_preserves_parent_overrides_and_scopes_only_test_children(self):
        import source_identity
        parent = {'CMAKE_BUILD_PARALLEL_LEVEL': '8', 'CTEST_PARALLEL_LEVEL': '4',
                  'UNCHANGED': 'value'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with patch.dict(os.environ, parent, clear=True), \
                    patch.object(c, 'default_jobs', return_value=15), \
                    patch.object(b, 'ROOT', root), patch.object(b, 'run') as run, \
                    patch.object(b, 'cache_identity', return_value={}), \
                    patch.object(source_identity, 'source_tree', return_value={}):
                self.assertEqual(b.main(['test', 'dev', '--core-provider', 'cpp', '--jobs', '2']), 0)
                self.assertEqual(dict(os.environ), parent)
            calls = run.call_args_list
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0].kwargs['env'], parent)
            self.assertEqual(calls[1].kwargs['env'], parent)
            compile_command = calls[1].args[0]
            test_command = calls[2].args[0]
            self.assertEqual(compile_command[compile_command.index('--parallel') + 1], '2')
            self.assertEqual(test_command[test_command.index('--parallel') + 1], '2')
            self.assertEqual(calls[2].kwargs['env'], {'UNCHANGED': 'value', c.WORKER_BUDGET: '1',
                                                    'CMAKE_BUILD_PARALLEL_LEVEL': '1',
                                                    'CTEST_PARALLEL_LEVEL': '1'})

    def test_parent_cgroup_memory_and_quota_are_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);proc=root/'proc';(proc/'self').mkdir(parents=True)
            group=root/'group';leaf=group/'child';leaf.mkdir(parents=True)
            (proc/'self/cgroup').write_text('0::/child\n')
            (proc/'self/mountinfo').write_text('1 2 0:1 / '+str(group)+' rw - cgroup2 cgroup rw\n')
            for directory,cpu,memory,current in ((group,'200000 100000','1000','800'),(leaf,'max 100000','max','0')):
                (directory/'cpu.max').write_text(cpu);(directory/'memory.max').write_text(memory);(directory/'memory.current').write_text(current)
            cpus,memory=c.linux_limits(proc)
            self.assertEqual(cpus,[2]);self.assertEqual(memory,[200])
            (group/'memory.current').unlink()
            with self.assertRaises(ValueError):c.linux_limits(proc)

    def test_explicit_scope_flags_then_shared_then_environment_then_defaults(self):
        args=argparse.Namespace(build_jobs=None,test_jobs=None,jobs=None)
        with patch.dict(b.os.environ,{},clear=True),patch.object(b,'default_jobs',return_value=7), \
                patch.object(c,'default_test_jobs',return_value=4) as automatic_tests:
            self.assertEqual(b.job_limits(args),(7,4))
            with patch.dict(b.os.environ,{'CMAKE_BUILD_PARALLEL_LEVEL':'5','CTEST_PARALLEL_LEVEL':'3'}):
                self.assertEqual(b.job_limits(args),(5,3))
                with patch.dict(b.os.environ,{'CMAKE_BUILD_PARALLEL_LEVEL':'auto'}), patch.object(c,'default_jobs',return_value=9):
                    self.assertEqual(b.job_limits(args),(9,3))
                with patch.dict(b.os.environ,{'CTEST_PARALLEL_LEVEL':'auto'}):
                    self.assertEqual(b.job_limits(args),(5,4))
                args.jobs=4;self.assertEqual(b.job_limits(args),(4,4))
                args.build_jobs=8;args.test_jobs=1;self.assertEqual(b.job_limits(args),(8,1))
                self.assertEqual(automatic_tests.call_count,2)
            args.jobs=None;args.test_jobs=None
            self.assertEqual(b.job_limits(args),(8,4))


if __name__=='__main__':unittest.main()
