from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class DependencyPaths(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='dependency paths ');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.sysroot=self.root/'sdk/target';(self.sysroot/'include').mkdir(parents=True);(self.sysroot/'lib').mkdir()
        self.lib=self.sysroot/'lib/libfixture.a';self.lib.write_bytes(b'archive')
        self.external=self.root/'outside';self.external.mkdir();(self.external/'libfixture.a').write_bytes(b'foreign')
        self.cmake=shutil.which('cmake');self.assertTrue(self.cmake,'CMake is a required build prerequisite')
    def configure(self,body,children=None):
        source=self.root/'source';source.mkdir();build=self.root/'build'
        for name,content in (children or {}).items():
            child=source/name;child.mkdir();(child/'CMakeLists.txt').write_text(content)
        (source/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(Fixture NONE)\nset(CMAKE_SYSTEM_NAME Linux)\nset(FOUNDATION_SDK_ROOT "'+str(self.sysroot.parent)+'")\nset(CMAKE_SYSROOT "'+str(self.sysroot)+'")\nset(Python3_EXECUTABLE "'+sys.executable+'")\ninclude("'+str(ROOT/'cmake/BuildPolicy.cmake')+'")\n'+body+'\nfoundation_finalize_build_policy()\n')
        return subprocess.run([self.cmake,'-G','Ninja','-S',str(source),'-B',str(build)],capture_output=True,text=True)
    def body(self,library=None,include=None):
        return 'add_library(dep STATIC IMPORTED)\nset_target_properties(dep PROPERTIES IMPORTED_LOCATION "'+str(library or self.lib)+'" INTERFACE_INCLUDE_DIRECTORIES "'+str(include or self.sysroot/'include')+'")\n'
    def test_imported_library_and_include_are_physically_contained(self):
        result=self.configure(self.body());self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        result=subprocess.run([self.cmake,'--build',str(self.root/'build'),'--target','foundation-dependency-check'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_child_local_imports_are_checked_in_their_directory_scope(self):
        result=self.configure('add_subdirectory(child)',{'child':'foundation_register_build_directory()\n'+self.body()})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.lib.write_bytes(b'changed child dependency')
        result=subprocess.run([self.cmake,'--build',str(self.root/'build'),'--target','foundation-dependency-check'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('bytes changed',result.stdout+result.stderr)

    def test_supplier_project_is_registered_without_editing_supplier_source(self):
        result=self.configure('add_subdirectory(supplier)',{'supplier':'project(Supplier NONE)\n'+self.body()})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.lib.write_bytes(b'changed supplier dependency')
        result=subprocess.run([self.cmake,'--build',str(self.root/'build'),'--target','foundation-dependency-check'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('bytes changed',result.stdout+result.stderr)

    def test_unregistered_child_cannot_escape_policy(self):
        result=self.configure('add_subdirectory(child)',{'child':self.body(self.external/'libfixture.a')})
        self.assertNotEqual(result.returncode,0);self.assertIn('foundation_register_build_directory',result.stderr)

    def test_same_named_local_imports_retain_distinct_notice_paths(self):
        child='foundation_register_build_directory()\n'+self.body()
        other='foundation_register_build_directory()\n'+self.body(self.external/'libfixture.a')
        result=self.configure('set(FOUNDATION_SDK_ROOT "")\nset(FOUNDATION_GUI_DISTRIBUTABLE TRUE)\nadd_subdirectory(first)\nadd_subdirectory(second)',{'first':child,'second':other})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        fragments=[p.read_text() for p in (self.root/'build/policy').glob('*-notices-.cmake')]
        self.assertTrue(any(str(self.lib) in text for text in fragments));self.assertTrue(any(str(self.external/'libfixture.a') in text for text in fragments))

    def test_external_cached_imported_library_fails_at_configure(self):
        result=self.configure(self.body(self.external/'libfixture.a'))
        self.assertNotEqual(result.returncode,0);self.assertIn('escapes declared roots',result.stdout+result.stderr)
    def test_external_include_fails_at_configure(self):
        result=self.configure(self.body(include=self.external))
        self.assertNotEqual(result.returncode,0);self.assertIn('escapes declared roots',result.stdout+result.stderr)
    def test_alias_changed_after_configure_fails_install_guard(self):
        alias=self.sysroot/'lib/libalias.a';alias.symlink_to(self.lib.name)
        result=self.configure(self.body(alias));self.assertEqual(result.returncode,0,result.stderr)
        alias.unlink();alias.symlink_to(self.external/'libfixture.a')
        result=subprocess.run([self.cmake,'-P',str(self.root/'build/dependency-paths-.cmake')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('escapes declared roots',result.stderr)
    def test_library_bytes_changed_in_place_fail_install_guard(self):
        result=self.configure(self.body());self.assertEqual(result.returncode,0,result.stderr)
        self.lib.write_bytes(b'different archive')
        result=subprocess.run([self.cmake,'-P',str(self.root/'build/dependency-paths-.cmake')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('bytes changed',result.stderr)

    def test_transitive_link_only_expression_is_checked(self):
        body='add_library(dep INTERFACE)\ntarget_link_libraries(dep INTERFACE "$<LINK_ONLY:'+str(self.external/'libfixture.a')+'>")\n'
        result=self.configure(body);self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run([self.cmake,'--build',str(self.root/'build'),'--target','foundation-dependency-check'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('escapes declared roots',result.stdout+result.stderr)

    def test_target_search_options_cannot_bypass_physical_checks(self):
        result=self.configure('add_library(dep INTERFACE)\ntarget_compile_options(dep INTERFACE "-I'+str(self.external)+'")\n')
        self.assertNotEqual(result.returncode,0);self.assertIn('target search overrides',result.stderr)

    def test_linker_flag_search_override_cannot_bypass_physical_checks(self):
        result=self.configure('set(CMAKE_EXE_LINKER_FLAGS "-Wl,-L,'+str(self.external)+'")\n'+self.body())
        self.assertNotEqual(result.returncode,0);self.assertIn('linker search overrides',result.stderr)

    def test_generator_expression_is_checked_before_compilation(self):
        result=self.configure(self.body(include='$<1:'+str(self.external)+'>'))
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run([self.cmake,'--build',str(self.root/'build'),'--target','foundation-dependency-check'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('escapes declared roots',result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
