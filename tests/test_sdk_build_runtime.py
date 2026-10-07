from pathlib import Path
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from dependency_archive import digest, file_inventory, write_json
import sdk_build_runtime
from verify_abi import inspect


class DevelopmentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sdk = self.root / 'sdk'
        self.libs = self.sdk / 'sysroot/usr/lib'
        self.libs.mkdir(parents=True)
        self.binary = self.root / 'build/application'
        self.binary.parent.mkdir()
        self.processor = {'arm64':'aarch64', 'AMD64':'x86_64'}.get(platform.machine(), platform.machine())
        self.assertIn(self.processor, ('x86_64', 'aarch64'))
        for tool in ('cc', 'c++', 'cmake', 'ninja', 'readelf'):
            self.assertIsNotNone(shutil.which(tool), 'required Linux fixture tool: ' + tool)
        self.run_command(['cc', '-x', 'c', '-shared', '-fPIC', '-Wl,-soname,libleaf.so.1',
                          '-o', str(self.libs / 'libleaf.so.1'), '-'], 'int leaf(void){return 7;}')
        self.run_command(['cc', '-x', 'c', '-shared', '-fPIC', '-Wl,-soname,libmiddle.so.1',
                          '-Wl,-rpath,', '-L' + str(self.libs), '-o', str(self.libs / 'libmiddle.so.1'),
                          '-', '-l:libleaf.so.1'], 'extern int leaf(void); int middle(void){return leaf();}')
        (self.sdk / 'bin').mkdir()
        clean = self.sdk / 'fixture-middle-without-path.so'
        self.run_command(['cc', '-x', 'c', '-shared', '-fPIC', '-Wl,-soname,libmiddle.so.1',
                          '-L' + str(self.libs), '-o', str(clean), '-', '-l:libleaf.so.1'],
                         'extern int leaf(void); int middle(void){return leaf();}')
        # Independently linked real ELF protocol fixture, as in test_portability:
        # preserve the contract while replacing only the wholly-empty search tag.
        # Actual retained patchelf qualification is separate from host fixtures.
        editor = self.sdk / 'bin/patchelf'
        editor.write_text('#!' + sys.executable + '\nimport pathlib, shutil, sys\n'
            'assert len(sys.argv)==3 and sys.argv[1]=="--remove-rpath"\n'
            'assert pathlib.Path(sys.argv[2]).name=="libmiddle.so.1"\n'
            'shutil.copyfile(' + repr(str(clean)) + ', sys.argv[2])\n')
        editor.chmod(0o755)
        self.compile_application()
        self.seal()

    def run_command(self, command, source=None):
        result = subprocess.run(command, input=source, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def compile_application(self, private=True):
        source = 'extern int middle(void); int main(void){return middle()==7 ? 0 : 1;}' if private else 'int main(void){return 0;}'
        args = ['cc', '-x', 'c', '-', '-Wl,--disable-new-dtags,-rpath,$ORIGIN/.sdk-runtime/application',
                '-o', str(self.binary)]
        if private:
            args += ['-L' + str(self.libs), '-Wl,-rpath-link,' + str(self.libs), '-l:libmiddle.so.1']
        self.run_command(args, source)

    def seal(self):
        write_json(self.sdk / 'sdk.json', {'schema_version':1,
            'target':{'system':'Linux','processor':self.processor,'sysroot':'sysroot'},
            'files':file_inventory(self.sdk, exclude=('sdk.json',))})
        self.manifest = digest(self.sdk / 'sdk.json')

    def stage(self):
        return sdk_build_runtime.stage_build_runtime(self.sdk, self.binary, 'application', self.processor, self.manifest)

    def test_recursive_closure_runs_after_relocation_without_sdk_and_rebuild_removes_stale_libraries(self):
        original = file_inventory(self.sdk)
        result = self.stage()
        private = self.binary.parent / '.sdk-runtime/application'
        self.assertEqual(result['audit']['runtime_resolution'], 'passed')
        self.assertEqual(file_inventory(self.sdk), original)
        self.assertTrue((private / 'libleaf.so.1').is_file())
        self.assertEqual(inspect(private / 'libmiddle.so.1')['rpaths'], [])
        relocated = self.root / 'relocated'
        shutil.copytree(self.binary.parent, relocated)
        hidden = self.root / 'sdk-unavailable'
        self.sdk.rename(hidden)
        subprocess.run([str(relocated / 'application')], cwd=relocated, env={'PATH':'/usr/bin:/bin'}, check=True)
        hidden.rename(self.sdk)
        self.compile_application(private=False)
        self.stage()
        self.assertFalse((private / 'libleaf.so.1').exists())
        subprocess.run([str(self.binary)], check=True)

    def test_provider_mutation_cannot_replace_last_verified_closure(self):
        self.stage()
        private = self.binary.parent / '.sdk-runtime/application'
        before = file_inventory(private)
        self.run_command(['cc', '-x', 'c', '-shared', '-fPIC', '-Wl,-soname,libleaf.so.1',
                          '-o', str(self.libs / 'libleaf.so.1'), '-'], 'int leaf(void){return 9;}')
        with self.assertRaisesRegex(ValueError, 'differs from.*SDK inventory'):
            self.stage()
        self.assertEqual(file_inventory(private), before)
        subprocess.run([str(self.binary)], check=True)

    def test_manifest_change_and_unowned_or_modified_runtime_destination_fail_closed(self):
        self.stage()
        private = self.binary.parent / '.sdk-runtime/application'
        before = file_inventory(private)
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            sdk_build_runtime.stage_build_runtime(self.sdk, self.binary, 'application', self.processor, 'f' * 64)
        self.assertEqual(file_inventory(private), before)
        (private / 'foreign').write_text('preserve me')
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            self.stage()
        self.assertEqual((private / 'foreign').read_text(), 'preserve me')

    def test_publish_failure_restores_previous_and_uncertain_rollback_preserves_backup(self):
        from unittest.mock import patch
        self.stage()
        private = self.binary.parent / '.sdk-runtime/application'
        before = file_inventory(private)
        rename = Path.rename
        for rollback_fails in (False, True):
            def fail(path, destination):
                if Path(destination) == private and (path.name == 'application' or rollback_fails):
                    raise OSError('injected publication failure')
                return rename(path, destination)
            with self.subTest(rollback_fails=rollback_fails), patch.object(Path, 'rename', fail):
                with self.assertRaisesRegex(ValueError if rollback_fails else OSError,
                                            'retained at' if rollback_fails else 'injected'):
                    self.stage()
            backups = list(private.parent.glob('.sdk-runtime-previous-*'))
            if rollback_fails:
                self.assertFalse(private.exists())
                self.assertEqual(len(backups), 1)
                self.assertEqual(file_inventory(backups[0] / 'runtime'), before)
            else:
                self.assertEqual(backups, [])
                self.assertEqual(file_inventory(private), before)

    def test_nonempty_supplier_search_path_is_not_erased(self):
        self.run_command(['cc', '-x', 'c', '-shared', '-fPIC', '-Wl,-soname,libmiddle.so.1',
                          '-Wl,-rpath,' + str(self.libs), '-L' + str(self.libs),
                          '-o', str(self.libs / 'libmiddle.so.1'), '-', '-l:libleaf.so.1'],
                         'extern int leaf(void); int middle(void){return leaf();}')
        self.seal()
        with self.assertRaisesRegex(ValueError, 'runtime search path'):
            self.stage()
        self.assertFalse((self.binary.parent / '.sdk-runtime/application').exists())
        self.assertEqual(inspect(self.libs / 'libmiddle.so.1')['runpath'], [str(self.libs)])

    def test_cmake_module_ordinary_build_links_static_language_runtime_and_stages_closure(self):
        # This is a real native compiler fixture for the module, not a claim that
        # an externally prepared/cold-built SDK has passed platform qualification.
        root = Path(__file__).resolve().parents[1]
        source = self.root / 'source'
        source.mkdir()
        (source / 'main.cpp').write_text('#include <array>\nint main(){std::array<int,1> value{7}; return value[0]!=7;}\n')
        (source / 'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.24)
project(SdkRuntimeFixture LANGUAGES CXX)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(FOUNDATION_SDK_ROOT "''' + self.sdk.as_posix() + '''")
include("''' + (root / 'cmake/StaticCxxRuntime.cmake').as_posix() + '''")
include("''' + (root / 'cmake/SdkBuildRuntime.cmake').as_posix() + '''")
add_executable(application main.cpp)
foundation_sdk_runtime(application)
''')
        tree = self.root / 'cmake-build'
        self.run_command(['cmake','-S',str(source),'-B',str(tree),'-G','Ninja','-DCMAKE_BUILD_TYPE=Debug'])
        self.run_command(['cmake','--build',str(tree),'--parallel','2'])
        # Keep this fixture independent of the host libstdc++ ABI floor: newer
        # distros can make std::string's static closure require newer glibc.
        rules = (tree / 'build.ninja').read_text()
        self.assertIn('-static-libstdc++', rules)
        self.assertIn('-static-libgcc', rules)
        info = inspect(tree / 'application')
        self.assertNotIn('libstdc++.so.6', info['needed'])
        self.assertNotIn('libgcc_s.so.1', info['needed'])
        self.assertEqual(info['rpath'], ['$ORIGIN/.sdk-runtime/application'])
        self.assertFalse(info['runpath'])
        self.assertTrue((tree / '.sdk-runtime/application/build-runtime.json').is_file())
        subprocess.run([str(tree / 'application')], check=True)
        private = tree / '.sdk-runtime/application'
        before = ((tree / 'application').stat().st_mtime_ns, digest(tree / 'application'))
        shutil.rmtree(private)
        self.run_command(['cmake','--build',str(tree),'--target','application'])
        self.assertTrue((private / 'build-runtime.json').is_file())
        self.assertEqual(before, ((tree / 'application').stat().st_mtime_ns, digest(tree / 'application')),
                         'missing runtime repair must not recompile/relink unchanged application')
        with (private / 'runtime-inventory.json').open('a') as stream:
            stream.write(' ')  # Valid JSON with changed bytes is not an audited closure.
        rejected = subprocess.run(['cmake','--build',str(tree),'--target','application'],
                                  capture_output=True,text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('changed outside', rejected.stdout + rejected.stderr)
        self.assertEqual(before, ((tree / 'application').stat().st_mtime_ns, digest(tree / 'application')))


if __name__ == '__main__':
    unittest.main()
