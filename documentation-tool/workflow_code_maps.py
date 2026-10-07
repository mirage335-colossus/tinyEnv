"""Small literal-source diagrams beneath the curated workflow overviews.

Only the caller's captured-text resolver is used. No application module, CMake
configuration, test program or release operation is imported or executed.
"""


def make_workflow_code_maps(code, edge, diagram):
    """Return source excerpt maps and drill bindings for every workflow step."""
    positions = ((0, 0), (1, 0), (1, 1), (0, 1), (0, 2), (1, 2))
    build = 'tools/build.py'
    cmake = 'CMakeLists.txt'
    rust = 'cmake/RustComponent.cmake'
    runner = 'tools/run_tests.py'
    producer = 'tools/ci_plan.py'
    lifecycle = '.github/scripts/lifecycle.py'
    delivery = 'tools/github_release.py'
    hosted = '.github/workflows/_release-latest.yml'
    maps = []

    def c(id, title, path, excerpt, slot, *, child=None, note='', supporting=False):
        column, row = positions[slot]
        return code(id, title, path, excerpt, column=column, row=row,
                    child=child, note=note,
                    emphasis='supporting' if supporting else 'primary')

    def jump(map, node=None):
        return {'map': map, **({'node': node} if node else {})}

    maps.append(diagram(
        'build-entry', 'Shell entry, Python dispatch and process plumbing',
        'The primary route is shell exec → argument parser → execute. The supporting cards show the timing/process '
        'helpers used by execute; the connecting label explicitly skips into execute rather than implying main calls them directly.',
        [
            c('entry', 'Shell exec enters the Python wrapper', 'build.sh',
              'exec "${PYTHON:-python3}" "$root/tools/build.py" "$@"', 0),
            c('arguments', 'main declares action and preset arguments', build,
              'def main(argv=None):\n'
              '    parser = argparse.ArgumentParser(description=__doc__)\n'
              '    parser.add_argument("action", nargs="?", choices=("build", "test", "package", "portable-package"), default="build")\n'
              '    parser.add_argument("preset", nargs="?", choices=("dev", "release", "asan"), default=None)', 1,
              note='The remaining parser options continue in the source; this is the shared build/test/package entry.'),
            c('execute', 'main calls execute after parsing', build,
              'result = execute(args, parser, timings)\n'
              '        status = "passed"\n'
              '        return result', 2, child=jump('build-sequence', 'configure')),
            c('timing', 'PhaseTimings.call calls its supplied function', build,
              'def call(self, name, function, *args, **kwargs):\n'
              '        if self.destination is None:\n'
              '            return function(*args, **kwargs)', 3, supporting=True,
              note='The opt-in timing branch below calls the same function and records its duration.'),
            c('run', 'run delegates to the platform wrapper', build,
              'def run(command, **kwargs):\n'
              '    print("+ " + subprocess.list2cmdline([str(x) for x in command]), flush=True)\n'
              '    windows_compiler.run(command, cwd=ROOT, **kwargs)', 4, supporting=True),
            c('native-process', 'Non-Windows branch launches the child process', 'tools/windows_compiler.py',
              "if os.name != 'nt':\n"
              '        return subprocess.run(command, cwd=cwd, env=env, check=True)', 5, supporting=True,
              note='The Windows branch continues below with its owned BuildSession/process_tree launcher.'),
        ], [
            edge('entry', 'arguments', 'exec Python', 'process'),
            edge('arguments', 'execute', 'parse options; then invoke', 'step'),
            edge('execute', 'timing', 'via execute command calls', 'call', emphasis='supporting'),
            edge('timing', 'run', 'supplied function = run', 'call', emphasis='supporting'),
            edge('run', 'native-process', 'platform wrapper; if not Windows', 'conditional', emphasis='supporting'),
        ], scope='Literal wrapper entry and representative non-Windows subprocess boundary.'))

    maps.append(diagram(
        'build-sequence', 'execute: configure, select, compile and dispatch',
        'These are ordered statements and conditional dispatch inside execute. Input selection, identity guards, cache stamps '
        'and some command arguments are omitted between cards. CMake configuration does not itself launch the next build command.',
        [
            c('configure-argv', 'Construct the configure argument list', build,
              'configure = ["cmake", "--preset", preset, "-B", str(build),\n'
              '                 "-DFOUNDATION_CORE_PROVIDER=" + args.core_provider,\n'
              '                 "-DFOUNDATION_RUST_SDK_ROOT=",\n'
              '                 "-DFOUNDATION_BUILD_GUI=" + ("ON" if args.gui_source else "OFF"),', 0,
              child=jump('cmake-core', 'provider'),
              note='The literal list continues with other flags, then selected SDK/toolchain arguments. Values remain symbolic.'),
            c('configure', 'Launch CMake configuration', build,
              'timings.call("configure", run, configure, env=child_environment)', 1,
              child=jump('cmake-core', 'project'),
              note='Earlier source/input checks precede this call; cache identity is written immediately afterwards.'),
            c('selection', 'Test branch chooses exact or aggregate targets', build,
              'exact_selection = timings.call("test_selection", named_selection, build, args.tests, programs, child_environment)\n'
              '            targets = exact_selection["targets"]\n'
              '        else:\n'
              '            targets = ["foundation-tests" + ("-" + args.label if args.label else "")]', 2,
              child=jump('test-registration', 'aggregate'),
              note='This block is inside action==test; the preceding default is targets=["all"].'),
            c('compile', 'Launch the selected prerequisite build', build,
              'if not args.configure_only and targets:\n'
              '        timings.call("compile", run, [programs["cmake"], "--build", str(build), "--parallel", str(jobs), "--target", *targets], env=child_environment)', 3,
              child=jump('cmake-core', 'core'),
              note='Generated build tools schedule target prerequisites. The wrapper checks source/selection stability next.'),
            c('ctest', 'Test branch launches CTest', build,
              'timings.call("test_execution", run, command, env=child_environment)', 4,
              child=jump('test-registration', 'core-command'),
              note='Only action==test reaches this call; command is constructed above with selections and optional JUnit. Package is a separate elif branch.'),
            c('final-source', 'Final source check after test/package writers', build,
              'if args.action != "build" and timings.call("source_verification", source_tree, ROOT, args.gui_source) != source_before:\n'
              '        raise ValueError("source changed during the operation; outputs are not qualification")', 5,
              supporting=True,
              child=jump('build-result', 'final-source'),
              note='Plain build already checks source immediately after compilation. SDK/Rust/dependency checks continue below before return 0.'),
        ], [
            edge('configure-argv', 'configure', 'after input checks and stamps', 'step'),
            edge('configure', 'selection', 'back in execute: if test', 'conditional'),
            edge('selection', 'compile', 'selected prerequisites', 'step'),
            edge('configure', 'compile', 'plain build/package: all', 'conditional'),
            edge('compile', 'ctest', 'if test; after identity checks', 'conditional'),
            edge('ctest', 'final-source', 'after test return', 'step', emphasis='supporting'),
            edge('compile', 'final-source', 'package branch omitted', 'step', emphasis='supporting'),
        ], scope='Wrapper statement order; not a configured target execution trace.'))

    maps.append(diagram(
        'build-result', 'The wrapper rechecks inputs before its success/error exit',
        'The post-compile source check applies to every action. Test/package run additional writers and therefore have a second '
        'source observation. Selected dependency/tool checks follow; failures throw to the CLI error boundary.',
        [
            c('post-compile', 'Every action rechecks source after compilation', build,
              'if timings.call("source_verification", source_tree, ROOT, args.gui_source) != source_before:\n'
              '        raise ValueError("source changed during compilation; rebuild a stable candidate")', 0,
              note='The named-test branch also compares configured selection/prerequisites immediately before this check.'),
            c('final-source', 'Test/package recheck after their later execution', build,
              'if args.action != "build" and timings.call("source_verification", source_tree, ROOT, args.gui_source) != source_before:\n'
              '        raise ValueError("source changed during the operation; outputs are not qualification")', 1,
              note='This guard deliberately excludes plain build, whose terminal source check is the preceding card.'),
            c('sdk', 'Recheck the selected prepared SDK', build,
              'if args.sdk and timings.call("sdk_verification", sdk_identity, args.sdk.resolve()) != identity["sdk"]["sha256"]:\n'
              '        raise ValueError("prepared SDK changed during execution; evidence is invalid")', 2,
              supporting=True,
              note='GUI input-group verification precedes this card when selected.'),
            c('rust-tools', 'Native Rust branch rechecks selected tool identity', build,
              'elif args.core_provider == "rust":\n'
              '        if timings.call("rust_tool_verification", native_rust_identity) != (native_rust_tools, native_rust_before):\n'
              '            raise ValueError("selected Rust tools changed during execution; evidence is invalid")', 3,
              supporting=True,
              note='This elif follows the prepared Rust SDK check. The remaining Windows/native-prefix/Wasm checks continue below.'),
            c('success', 'execute returns zero after all selected checks', build,
              'return 0\n\n\nif __name__ == "__main__":', 4,
              note='The module entry calls sys.exit(main()); main returns execute\'s result and finishes optional timing output.'),
            c('failure', 'CLI boundary reports failures and returns exit 1', build,
              'except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:\n'
              '        print("build: " + str(error), file=sys.stderr)\n'
              '        sys.exit(1)', 5,
              supporting=True),
        ], [
            edge('post-compile', 'final-source', 'after test/package execution', 'conditional'),
            edge('final-source', 'sdk', 'source unchanged; other selected checks', 'step', emphasis='supporting'),
            edge('post-compile', 'sdk', 'plain build skips second source check', 'conditional', emphasis='supporting'),
            edge('sdk', 'rust-tools', 'if native Rust tools selected', 'conditional', emphasis='supporting'),
            edge('rust-tools', 'success', 'after remaining input checks', 'step', emphasis='supporting'),
            edge('sdk', 'success', 'other provider path; remaining guards omitted', 'conditional', emphasis='supporting'),
            edge('post-compile', 'failure', 'if identity check throws', 'conditional', emphasis='supporting'),
        ], scope='Real terminal source checks and representative input/failure boundaries; omitted guards remain in source.'))

    maps.append(diagram(
        'cmake-core', 'CMake declarations: provider, core sources and CLI link',
        'Cards show real configuration statements and declared relationships. Dependency arrows mean source/link/provider '
        'relationships, not compilation order. Variables, platform conditions, options helpers and generator expressions are not evaluated.',
        [
            c('project', 'Project language and configured test support', cmake,
              'cmake_minimum_required(VERSION 3.24)\n'
              'project(Foundation VERSION 0.1.0 LANGUAGES CXX)', 0,
              note='The file includes CTest and build helpers later; the selected preset/toolchain establishes actual compiler configuration.'),
            c('provider', 'Provider cache selection', cmake,
              'set(FOUNDATION_CORE_PROVIDER "rust" CACHE STRING "Text validation implementation: rust (default) or cpp")\n'
              'set_property(CACHE FOUNDATION_CORE_PROVIDER PROPERTY STRINGS cpp rust)', 1,
              child=jump('rust-component', 'provider-guard'),
              note='Fresh configuration defaults to Rust. Validation and frozen-provider checks follow these declarations.'),
            c('core', 'Declare the C++ core and alias', cmake,
              'add_library(foundation_core STATIC src/store.cpp src/text_validation.cpp)\n'
              'add_library(foundation::core ALIAS foundation_core)\n'
              'set_target_properties(foundation_core PROPERTIES EXPORT_NAME core CXX_EXTENSIONS OFF)\n'
              'target_compile_features(foundation_core PUBLIC cxx_std_20)', 2,
              note='Store and its C++ boundary remain compiled with either text-validation provider.'),
            c('includes', 'Publish core header search paths', cmake,
              'target_include_directories(foundation_core PUBLIC\n'
              '  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>\n'
              '  $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/generated>\n'
              '  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)', 3,
              supporting=True,
              note='Generator expressions distinguish build and installed consumers; they stay literal in this chart.'),
            c('cli', 'Declare CLI sources and its core link', cmake,
              'add_executable(foundation-cli src/main.cpp)\n'
              'target_link_libraries(foundation-cli PRIVATE foundation::core)\n'
              'target_include_directories(foundation-cli PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/generated")\n'
              'foundation_options(foundation-cli)', 4,
              note='foundation_options adds selected platform/runtime/warning flags; optional GUI targets have separate declarations.'),
            c('rust-helper', 'Call the provider-specific configuration helper', cmake,
              'find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)\n'
              'include(cmake/RustComponent.cmake)\n'
              'foundation_rust_component(foundation_core)', 5,
              child=jump('rust-component', 'provider-guard')),
        ], [
            edge('project', 'provider', 'configuration continues; intervening options omitted', 'step'),
            edge('provider', 'core', 'provider does not replace the C++ Store', 'dependency'),
            edge('core', 'includes', 'public include properties', 'dependency', emphasis='supporting'),
            edge('core', 'cli', 'CLI links foundation::core', 'dependency'),
            edge('provider', 'rust-helper', 'selected value enters helper', 'dependency'),
            edge('core', 'rust-helper', 'core target argument', 'dependency'),
        ], scope='Configuration declarations and target relationships; no compile/link chronological ordering.'))

    maps.append(diagram(
        'rust-component', 'CMake selects and declares the Rust component',
        'The non-Rust branch returns. For Rust, omitted platform/SDK checks resolve symbolic tools and configuration; '
        'describe runs during configuration, while build/verify commands are deferred to the generated custom target.',
        [
            c('provider-guard', 'Return unless Rust is selected', rust,
              'if(NOT FOUNDATION_CORE_PROVIDER STREQUAL "rust")\n'
              '    return()\n'
              '  endif()', 0),
            c('imported', 'Declare an imported static archive target', rust,
              'add_library(foundation::rust_component STATIC IMPORTED)', 1,
              note='Platform/SDK/tool identity checks precede this declaration; each configuration gets an imported location.'),
            c('describe', 'Configuration invokes Rust input description', rust,
              'execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/rust_build.py"\n'
              '      describe --source-root "${CMAKE_SOURCE_DIR}" --build-dir "${CMAKE_BINARY_DIR}/rust/${configuration}"\n'
              '      --target "${target}" --cargo "${cargo}" --rustc "${rustc}" --profile "${profile}"\n'
              '      ${sdk_arguments} --output "${config_file}" COMMAND_ERROR_IS_FATAL ANY)', 2,
              supporting=True,
              note='This describe subprocess is configuration work, not Cargo compilation.'),
            c('custom-target', 'Declare deferred build and verify commands', rust,
              'add_custom_target(foundation-rust\n'
              '    COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/rust_build.py" build --config "${selected_config}"\n'
              '    COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/rust_build.py" verify --config "${selected_config}"', 3,
              child=jump('rust-build', 'entry'),
              note='BYPRODUCTS and VERBATIM complete this declaration below. Commands run when the configured target is built.'),
            c('dependency', 'Imported archive requires the custom target', rust,
              'add_dependencies(foundation::rust_component foundation-rust)', 4,
              note='This is a generated target dependency, not a configure-time call to Cargo.'),
            c('core-link', 'Select the private ABI provider and core link', rust,
              'target_compile_definitions(${core} PRIVATE FOUNDATION_USE_RUST=1)\n'
              '  target_link_libraries(${core} PRIVATE foundation::rust_component)', 5,
              note='The C++ core remains the owner of Store; only its private text validator is supplied by Rust.'),
        ], [
            edge('provider-guard', 'imported', 'if provider = rust; after omitted checks', 'conditional'),
            edge('imported', 'describe', 'per-configuration description', 'process', emphasis='supporting'),
            edge('describe', 'custom-target', 'later declarations use described paths', 'step', emphasis='supporting'),
            edge('custom-target', 'dependency', 'generated prerequisite', 'dependency'),
            edge('dependency', 'core-link', 'selected static component link', 'dependency'),
        ], scope='Configure-time commands versus deferred build-target commands.'))

    maps.append(diagram(
        'rust-build', 'Rust custom target enters the frozen Cargo builder',
        'The custom target process dispatches build(config), which resolves captured configuration and invokes Cargo. '
        'Prior-receipt/cache checks and artifact validation are omitted between short cards; verify is a separate subsequent custom command.',
        [
            c('entry', 'CLI dispatch calls build(config)', 'tools/rust_build.py',
              "elif args.command == 'build':\n"
              '            build(args.config)', 0),
            c('config', 'Load checked build configuration', 'tools/rust_build.py',
              'def build(config_path):\n'
              '    data, config_identity = _load_config(config_path)\n'
              '    _output_directories(data)\n'
              "    receipt_path = Path(data['receipt_path'])", 1,
              supporting=True,
              note='Previous receipt and input identity checks continue before Cargo is invoked.'),
            c('environment', 'Create a private selected-tool environment', 'tools/rust_build.py',
              "environment = child_environment(data['build_dir'], data['tools']['cargo']['path'],\n"
              "                                    data['tools']['rustc']['path'], data['flags'])", 2,
              supporting=True,
              note='Changed identified inputs also invalidate the private Cargo package cache.'),
            c('cargo-argv', 'Construct the literal Cargo build command', 'tools/rust_build.py',
              "argv = [data['tools']['cargo']['path'], 'build', '--frozen', '--jobs', '1',\n"
              "            '--manifest-path', str(Path(data['source_root']) / 'rust/Cargo.toml'),\n"
              "            '--target', data['target'], '--target-dir', str(Path(data['build_dir']) / 'target'),\n"
              "            '--message-format', 'json-render-diagnostics']", 3,
              note='The release profile condition appends --release below; all tool/target paths remain symbolic here.'),
            c('cargo-run', 'Invoke Cargo through _run', 'tools/rust_build.py',
              "raw = _run(argv, cwd=data['build_dir'], environment=environment, compiler=True, timeout=600)\n"
              '    artifacts = []', 4,
              note='The builder then validates parsed compiler-artifact output and writes its bound receipt. Cargo test is a different command.'),
            c('verify', 'CMake invokes the separate verifier afterwards', rust,
              'COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/rust_build.py" verify --config "${selected_config}"', 5,
              note='This card returns to the generated custom target declaration; it is not a direct Python call from build to verify.'),
        ], [
            edge('entry', 'config', 'build(args.config)', 'call'),
            edge('config', 'environment', 'after prior receipt checks', 'step', emphasis='supporting'),
            edge('environment', 'cargo-argv', 'after cache invalidation if needed', 'step', emphasis='supporting'),
            edge('cargo-argv', 'cargo-run', 'run selected Cargo process', 'process'),
            edge('cargo-run', 'verify', 'custom target next command; intervening receipt checks', 'step'),
        ], scope='Actual builder code and the separate generated verification command.'))

    maps.append(diagram(
        'test-registration', 'Configured test commands and their compile prerequisites',
        'CTest command declarations and foundation_test_prerequisites registration are configuration relationships. '
        'The wrapper builds selected registered targets before CTest launches a child. These examples do not enumerate every test.',
        [
            c('core-target', 'Declare the native core test executable', cmake,
              'add_executable(foundation_core_test EXCLUDE_FROM_ALL tests/store_test.cpp)\n'
              '  target_link_libraries(foundation_core_test PRIVATE foundation::core)', 0,
              note='The native branch uses this executable. Browser configuration uses its retained Node executor.'),
            c('core-command', 'Register core.store command', cmake,
              'add_test(NAME core.store COMMAND foundation_core_test)', 1,
              child=jump('native-test', 'entry'),
              note='This declaration tells CTest what to launch when native core.store is selected.'),
            c('prerequisite', 'Register core.store compile prerequisites', cmake,
              'foundation_test_prerequisites(core.store foundation_core_test)', 2,
              note='Registration does not execute the test or compile it.'),
            c('aggregate', 'Declare aggregate prerequisite targets', 'cmake/TestPrerequisites.cmake',
              'add_custom_target(foundation-tests DEPENDS ${all_targets})\n'
              '  foreach(label core tools integration fast gui)\n'
              '    add_custom_target(foundation-tests-${label} DEPENDS ${group_${label}})', 3,
              note='Finalization validates registrations and writes test-prerequisites.json. Actual lists/labels are configured values.'),
            c('python-command', 'Register a tools.* Python suite command', cmake,
              'add_test(NAME tools.${suite} COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tools/run_tests.py"\n'
              '        --suite "${suite}" --output "${CMAKE_BINARY_DIR}/test-reports/${suite}.json")', 4,
              child=jump('python-test', 'entry'),
              note='The CMake loop supplies the registered suite; this chart does not expand that inventory.'),
            c('rust-command', 'Register exact-host native Rust unit tests', rust,
              'if(BUILD_TESTING AND NOT EMSCRIPTEN AND compiler_host STREQUAL target)\n'
              '    add_test(NAME rust.unit COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/rust_build.py"\n'
              '      test --config "${selected_config}")', 5, supporting=True,
              note='Conditional rust.unit calls the distinct Cargo test path; it is not the custom target Cargo build command.'),
        ], [
            edge('core-target', 'core-command', 'declared executable command', 'dependency'),
            edge('core-command', 'prerequisite', 'registered test identity', 'dependency'),
            edge('prerequisite', 'aggregate', 'configured target list', 'dependency'),
            edge('python-command', 'aggregate', 'other registrations join aggregates', 'dependency'),
            edge('rust-command', 'aggregate', 'only when enabled/registered', 'dependency', emphasis='supporting'),
        ], scope='Configured declarations/prerequisites; actual child entry code is one level below.'))

    maps.append(diagram(
        'native-test', 'core.store enters the C++ contract test',
        'A representative path through the existing native test main. The full test includes more invalid-input and all-byte checks '
        'between excerpts. Assertions/helpers can throw; the enclosing catch maps failures to exit 1.',
        [
            c('entry', 'Native executable enters main', 'tests/store_test.cpp',
              'int main() {\n'
              '    try {\n'
              '        rejects<std::invalid_argument>([] { foundation::Store store(0); });\n'
              '        rejects<std::invalid_argument>([] { foundation::Store store(4097); });', 0,
              note='rejects executes its callable and expects the specified exception.'),
            c('add', 'Create a Store and call add', 'tests/store_test.cpp',
              'foundation::Store store(2);\n'
              '        const auto a = store.add("Alpha");\n'
              '        const auto b = store.add("Beta");\n'
              '        require(a == 1 && b == 2, "initial IDs");', 1),
            c('reject-update', 'Check rejected replacement input', 'tests/store_test.cpp',
              'rejects_text([&] { store.update(a, std::string_view{}); }, length_error);\n'
              '        rejects_text([&] { store.update(a, std::string(257, \'x\')); }, length_error);', 2,
              note='Additional ASCII/NUL/missing-ID checks continue below; these are literal test calls, not proposed examples.'),
            c('owned-state', 'Verify update and owning-copy behavior', 'tests/store_test.cpp',
              'require(store.update(a, std::string(256, \'x\')), "maximum length rejected");\n'
              '        auto copy = store.get(a);\n'
              '        copy->text = "local";\n'
              '        require(store.get(a)->text.size() == 256, "copy modified owned state");', 3),
            c('erase', 'Verify erase and monotonically allocated IDs', 'tests/store_test.cpp',
              'require(store.erase(a) && !store.get(a), "erase failed");\n'
              '        require(store.add("Gamma") == 3, "ID reused or failure consumed ID");', 4),
            c('result', 'Success output or exception exit', 'tests/store_test.cpp',
              'std::cout << "store contract passed\\n";\n'
              '    } catch (const std::exception& error) {\n'
              "        std::cerr << error.what() << '\\n';\n"
              '        return 1;', 5,
              note='The all-byte loop precedes this excerpt. Falling out of main after success returns zero.'),
        ], [
            edge('entry', 'add', 'after invalid-capacity assertions', 'step'),
            edge('add', 'reject-update', 'after capacity/text checks', 'step'),
            edge('reject-update', 'owned-state', 'after remaining rejection assertions', 'step'),
            edge('owned-state', 'erase', 'next state assertions', 'step'),
            edge('erase', 'result', 'after all-byte loop', 'step'),
            edge('reject-update', 'result', 'if assertion/helper throws', 'conditional', emphasis='supporting'),
        ], scope='Representative existing C++ test statements, with omitted assertions named explicitly.'))

    maps.append(diagram(
        'python-test', 'tools.* enters the recorded unittest suite runner',
        'The selected suite name resolves an existing module, which is loaded before execute runs the discovered unittest suite. '
        'Recorded outcomes must cover every applicable required test; platform exclusions are explicit.',
        [
            c('entry', 'Resolve the suite after CLI parsing', runner,
              'name, path = suite_source(args.suite)\n'
              '    args.output.unlink(missing_ok=True)', 0,
              note='suite_source validates the registered name and native diagnostic platform, then resolves an existing module path.'),
            c('load', 'Load that existing test module', runner,
              'spec = importlib.util.spec_from_file_location(name, path)\n'
              '    module = importlib.util.module_from_spec(spec)\n'
              '    spec.loader.exec_module(module)', 1,
              note='Only the application runner executes test modules. The documentation generator reads their captured source.'),
            c('execute', 'Discover suite and call execute', runner,
              'result = execute(unittest.defaultTestLoader.loadTestsFromModule(module))', 2),
            c('inventory', 'execute validates the test inventory', runner,
              'def execute(suite, system=None, stream=None):\n'
              '    tests = list(flatten(suite))\n'
              '    names = [test.id() for test in tests]\n'
              '    if not names or len(set(names)) != len(names):', 3, supporting=True,
              note='The omitted body rejects empty/duplicate inventories and separates explicitly inapplicable tests.'),
            c('unittest', 'Run applicable tests and require complete outcomes', runner,
              'result = unittest.TextTestRunner(stream=stream or sys.stderr, verbosity=2, resultclass=Recorded).run(unittest.TestSuite(selected))\n'
              '    required = {test.id() for test in selected}\n'
              '    complete = (result.wasSuccessful() and set(result.outcomes) == required and\n'
              "                all(item['status'] == 'passed' for item in result.outcomes.values()))", 4),
            c('result', 'Back in main: publish result and return status', runner,
              'publish(args.output, result)\n'
              "    return 0 if result['status'] == 'passed' else 1", 5),
        ], [
            edge('entry', 'load', 'selected module path', 'step'),
            edge('load', 'execute', 'loaded module', 'step'),
            edge('execute', 'inventory', 'execute(suite)', 'call'),
            edge('inventory', 'unittest', 'after applicable-test selection', 'step', emphasis='supporting'),
            edge('unittest', 'result', 'execute returns result to main', 'return'),
        ], scope='Existing Python suite entry, dynamic module selection and actual unittest call.'))

    maps.append(diagram(
        'release-entry', 'Manual and hosted release entry boundaries',
        'Manual RELEASE is a procedure, not an executable Python entry. The hosted ordinary route calls reusable workflows, '
        'requires full regression before assembly/publication, and schedules certification/promotion only for execute-enabled requests. '
        'Workflow dependency arrows are scheduling constraints, not function calls.',
        [
            c('manual', 'Manual procedure starts with frozen inputs', 'RELEASE',
              '1. Freeze source, version, target/backend inventory and qualification policy.\n'
              '2. Verify supplier terms, pinned inputs and notices. Resolve GUI terms before\n'
              '   distributing optional GUI code. Select exact immutable prepared recipes.', 0,
              child=jump('release-package', 'cpack'),
              note='This is the alternative local procedure; its later publication step is separately authorized.'),
            c('hosted', 'Hosted entry calls SDK application production', hosted,
              'uses: ./.github/workflows/sdk-application.yml\n'
              '    with:\n'
              '      preserve_artifacts: ${{ inputs.preserve_artifacts }}', 1,
              child=jump('release-package', 'test-command')),
            c('required-regression', 'Ordinary candidate requires full regression', hosted,
              'experiment: false\n'
              '      require_regression: true\n'
              '      jobs: ${{ inputs.jobs }}\n'
              '      execute: ${{ inputs.execute }}', 2,
              note='The reusable application workflow launches nested candidate regression. execute gates remote writes, not local production.'),
            c('assembly-gate', 'Assembly/publication job waits for required results', '.github/workflows/sdk-application.yml',
              "if: ${{ always() && needs.prepare.result == 'success' && needs.application.result == 'success' && ((inputs.require_regression && needs.regression.result == 'success') || (!inputs.require_regression && needs.regression.result == 'skipped')) }}\n"
              '    needs: [prepare, application, regression]', 3,
              child=jump('release-assemble', 'call')),
            c('certification', 'Hosted certification follows the candidate and receipt gate', hosted,
              'name: Certify exact remotely downloaded bytes and attach immutable evidence\n'
              '    if: inputs.execute\n'
              '    needs: [application, regression]', 4,
              child=jump('release-certify', 'physical-checks'),
              note='The top-level regression job checks the nested regression receipt; it does not rerun the suite.'),
            c('promotion', 'Hosted promotion requires certification', hosted,
              'name: Revalidate exact certificate and assets before changing Latest\n'
              '    if: inputs.execute\n'
              '    needs: [application, certification]', 5,
              child=jump('release-promote', 'entry')),
        ], [
            edge('hosted', 'required-regression', 'workflow inputs', 'dependency'),
            edge('required-regression', 'assembly-gate', 'required successful regression', 'dependency'),
            edge('assembly-gate', 'certification', 'after publication; execute-enabled', 'conditional'),
            edge('certification', 'promotion', 'successful certificate handoff', 'dependency'),
        ], scope='Manual alternative plus hosted scheduling declarations; local work still runs in preparation-only mode.'))

    maps.append(diagram(
        'release-package', 'Prepared producer: full test, package, archive verification',
        'The normal prepared producer runs a full release test action, then a separate package action. Windows graphics '
        'production has an explicit alternate qualification wrapper. CPack and archive verification are separate calls.',
        [
            c('test-command', 'Prepared producer constructs the full test command', producer,
              "command = [sys.executable, str(root / 'tools/build.py'), 'test', 'release', '--full',\n"
              "               '--portable', '--build-dir', str(build), '--build-jobs', str(jobs), '--test-jobs', '2', '--junit', str(output / 'source.junit.xml')]", 0,
              child=jump('build-sequence', 'ctest'),
              note='Selected verified SDK/provider/GUI flags are appended below before execution.'),
            c('test-run', 'Normal branch executes that test action', producer,
              'else:\n'
              '        subprocess.run(command, cwd=root, check=True)\n'
              '    # Host DLLs must already be removed before installation or package creation.', 1,
              note='The preceding graphics-needed branch runs windows_gui_qualification instead.'),
            c('package-command', 'Change a copied command to package', producer,
              'package_command = command.copy()\n'
              "    package_command[2] = 'package'\n"
              "    package_command.remove('--full')", 2,
              note='The next statements also remove the test-only --junit argument/value.'),
            c('package-run', 'Execute package action and select the platform archive', producer,
              'subprocess.run(package_command, cwd=root, check=True)\n'
              "    choices = sorted((build / 'packages').glob('*.zip' if target.startswith('windows-') else '*.tar.gz'))", 3,
              note='The producer requires exactly one archive and copies it into the output handoff.'),
            c('cpack', 'Inside build.execute: launch CPack', build,
              'timings.call("package", run, [programs["cpack"], "--config", str(build / "CPackConfig.cmake"), "-C", "Release"], env=child_environment)', 4,
              note='The package wrapper first configures/builds. --verify-package is its separate opt-in subprocess verification branch.'),
            c('artifact', 'Back in producer: describe and verify copied archive', producer,
              "module('coverage').write_new(descriptor, a.describe(archive))\n"
              "    a.verify(archive, descriptor, sdk=work / 'sdk' if (work / 'sdk/sdk.json').is_file() else None,\n"
              "             abi=target.startswith('linux-'), processor=target.split('-', 1)[1])", 5,
              note='These helper calls do not publish or certify. Further source/provider identity checks and artifact.json follow.'),
        ], [
            edge('test-command', 'test-run', 'after selected input flags', 'process'),
            edge('test-run', 'package-command', 'test returned successfully', 'step'),
            edge('package-command', 'package-run', 'separate package process', 'process'),
            edge('package-run', 'cpack', 'inside build.py package dispatch', 'process'),
            edge('cpack', 'artifact', 'package returns; copy selected archive first', 'return'),
        ], scope='Actual prepared producer and its package subprocess; not candidate publication.'))

    maps.append(diagram(
        'release-assemble', 'Assemble complete local releases from existing archives',
        'ci_plan prepares an exact assembly specification and calls release.assemble. The assembler stages existing source, '
        'application archives and dependency groups, verifies the inventory, and renames new staging into place. No compile/publish call exists here.',
        [
            c('call', 'Prepared assembly helper calls release.assemble', producer,
              "spec_path = output.parent / 'assembly.json'\n"
              '    c.write_new(spec_path, spec)\n'
              "    return module('release').assemble(spec_path, base, output)", 0,
              note='The omitted earlier helper code verifies complete target/backend inventory before writing spec.'),
            c('new-output', 'Assembler rejects reused output paths', 'tools/release.py',
              'if output.exists() or output.is_symlink():\n'
              "        raise ValueError('release output must be new')", 1,
              supporting=True,
              note='assemble reads the spec first and creates temporary sibling staging after this guard.'),
            c('retain', 'Nested retain copies and checks exact input bytes', 'tools/release.py',
              'shutil.copyfile(path, staged / filename)\n'
              "            if digest(path) != digest(staged / filename): raise ValueError('input changed during release assembly')\n"
              '            return filename', 2,
              note='retain is called for source and archive/manifest files. Source hash/archive verification follows before artifact processing.'),
            c('package-check', 'Validate each retained application package', 'tools/release.py',
              "validate_package(staged / archive, entry, source_manifest['tree_sha256'], read_json(staged / manifest))\n"
              '            recipes.update(dependency_recipes(entry))', 3,
              note='The surrounding artifact loop first compares the archive digest with its frozen entry.'),
            c('dependencies', 'Copy exact required retained dependency groups', 'tools/release.py',
              'for recipe in sorted(recipes):\n'
              "            files = copy_dependency_group(Path(base) / recipe, staged / 'dependencies' / recipe, recipe, kinds[recipe])\n"
              "            group = {'recipe_id': recipe, 'files': files}", 4),
            c('commit', 'Inventory, verify and commit the local directory', 'tools/release.py',
              "metadata['files'] = file_inventory(staged)\n"
              "        write_json(staged / 'release.json', metadata)\n"
              '        verify_release(staged)\n'
              '        staged.rename(output)', 5,
              note='The output remains a local candidate. A separate caller may subsequently plan or execute remote publication.'),
        ], [
            edge('call', 'new-output', 'assemble(spec_path, base, output)', 'call'),
            edge('new-output', 'retain', 'after new temporary staging', 'step', emphasis='supporting'),
            edge('retain', 'package-check', 'source verified; process each artifact', 'step'),
            edge('package-check', 'dependencies', 'after all artifact entries', 'step'),
            edge('dependencies', 'commit', 'complete local inputs', 'step'),
        ], scope='Actual local helper calls/statements with staging and loop steps explicitly omitted.'))

    maps.append(diagram(
        'release-publish', 'Candidate publication has a plan branch and an execute branch',
        'The lifecycle dispatcher explicitly calls execute=True for publication. Other callers can receive a plan. The executing '
        'helper creates a fresh draft/tag, uploads and verifies the draft bytes, then publishes a prerelease with Latest false.',
        [
            c('entry', 'Explicit hosted publication invokes the helper', lifecycle,
              "write('build/receipts/publication.json', delivery.publish_candidate(**request, execute=True))", 0,
              note='The surrounding publish-candidate dispatcher reads the frozen request and checks source/packager revision first.'),
            c('plan', 'The helper returns early unless execute is true', delivery,
              "result = plan('publish-candidate', repository, delivery=delivery, lifecycle='draft upload, verify every byte, publish prerelease until certified promotion; never Latest')\n"
              '    if not execute:return result', 1,
              supporting=True,
              note='The function default is execute=False. Local assemble calls it without execute to record a plan.'),
            c('draft', 'Executing branch creates a fresh tag and draft', delivery,
              "remote.change('/git/refs', body={'ref':'refs/tags/'+tag,'sha':delivery['tag_commit']})\n"
              "        info = remote.info(remote.change('/releases', body={'tag_name':tag,'target_commitish':delivery['tag_commit'],\n"
              "            'name':'experiment' if experiment else tag,'body':'Certification pending. Immutable application assets.',\n"
              "            'draft':True,'prerelease':True,'make_latest':'false'}), tag)", 2,
              note='Existing releases/tags are rejected before these writes. The remote draft is observed before upload.'),
            c('upload', 'Upload immutable candidate payloads', delivery,
              "upload_files(remote, tag, [Path(directory) / name for name in delivery['files']], release_info=info)", 3,
              note='The bound delivery.json descriptor is uploaded next; payload upload batches are bounded.'),
            c('verify', 'Verify the uploaded draft identity and bytes', delivery,
              'current, assets = verified_remote(remote, delivery, directory, draft=True, prerelease=True, metadata_only=True)\n'
              "        if current['id'] != info['id']:raise DeliveryError('draft release identity changed')", 4,
              supporting=True,
              note='Here readback keeps its default true: verified_remote downloads payloads and verifies the reconstructed release.'),
            c('prerelease', 'Publish prerelease and ensure it is outside Latest', delivery,
              'remote.change(f\'/releases/{info["id"]}\', method=\'PATCH\', body={\'draft\':False,\'prerelease\':True,\'make_latest\':\'false\'})\n'
              '        final, final_assets = verified_remote(remote, delivery, directory, prerelease=True, readback=False, metadata_only=True)\n'
              "        if final['id'] != info['id'] or final_assets != assets:raise DeliveryError('publication identity changed')\n"
              '        remote.not_latest(final)', 5,
              child=jump('release-certify', 'physical-checks'),
              note='Certification is a subsequent workflow/manual operation, not a call from publish_candidate.'),
        ], [
            edge('entry', 'plan', 'publish_candidate(**request)', 'call'),
            edge('plan', 'draft', 'only if execute=True; identity checks omitted', 'conditional'),
            edge('draft', 'upload', 'after observing draft', 'step'),
            edge('upload', 'verify', 'after delivery descriptor upload', 'step', emphasis='supporting'),
            edge('verify', 'prerelease', 'verified draft identity', 'step'),
        ], scope='Actual remote mutation branch; prerelease publication does not promote Latest.'))

    maps.append(diagram(
        'release-certify', 'Qualify exact bytes, calculate eligibility and attach an attempt',
        'Physical qualification and certificate calculation are separate dispatched workflow operations with reports handed across jobs. '
        'The certificate binds source/inventory/policy/environment coverage. Attachment appends an immutable attempt; it does not change Latest.',
        [
            c('physical-checks', 'Dispatcher invokes prepare or run for a physical check', lifecycle,
              "operation = qualification_tasks.prepare if command == 'check-prerequisites' else qualification_tasks.run\n"
              "        result = operation(ROOT, value('CHECK'), value('GITHUB_RUN_ID'), int(value('GITHUB_RUN_ATTEMPT')))\n"
              "        if command == 'check' and result['status'] != 'passed':\n"
              "            raise ValueError('required qualification did not pass')", 0,
              note='The plan/matrix assigns each physical execution its required environment. This is not one local test loop.'),
            c('calculate', 'Certificate dispatcher calls certify', lifecycle,
              "result = certify_release.certify(directory, ci.module('release').verify_metadata(directory), plan, reports,\n"
              "                       evidence.load(policy), value('PROFILE'), identity['experiment'],\n"
              "                       adoption=evidence.load(ROOT / 'build/adoption.json') if (ROOT / 'build/adoption.json').exists() else None)", 1,
              note='The dispatcher gathers exact logical report paths first; certify checks their bound subject and required scopes.'),
            c('coverage', 'certify merges reports and checks actual host evidence', 'tools/certify_release.py',
              'result = coverage.merge(plan, reports, adoption=adoption)\n'
              '    report_paths = {coverage.load(path)["check"]: path for path in reports}\n'
              '    for check in plan["checks"]:\n'
              "        coverage.check_host(plan, check['id'], result['checks'][check['id']], report_paths[check['id']].parent)", 2,
              supporting=True,
              note='Source/inventory/policy and target/backend/scope guards precede this excerpt.'),
            c('eligibility', 'Returned certificate marks promotion eligibility', 'tools/certify_release.py',
              '"eligible_for_promotion": passed and not experiment, "experiment": experiment,', 3,
              note='passed is derived from merged coverage. The return also records exact subject, reports, run identity and limitations.'),
            c('attachment', 'A separate dispatcher operation executes attachment', lifecycle,
              "write('build/receipts/attachment.json', delivery.attach_certificate(value('GITHUB_REPOSITORY'), value('TAG'), directory,\n"
              "                    identity, Path('build/certificate.json'), Path('build/check-plan.json'), policy, value('PROFILE'),\n"
              "                    reports, ci_retry.origin_attempt(value('CERTIFICATE_ATTEMPT'), int(value('GITHUB_RUN_ATTEMPT'))),\n"
              '                    execute=True, metadata_only=True))', 4,
              note='The certificate operation previously planned attachment; this branch explicitly executes the append-only write.'),
            c('attachment-helper', 'Attachment helper defaults to planning', delivery,
              'def attach_certificate(repository, tag, directory, delivery, certificate, check_plan, policy, profile,\n'
              '                       reports, attempt, *, execute=False, transport=None, metadata_only=False):', 5,
              supporting=True,
              child=jump('release-promote', 'entry'),
              note='It validates/bundles the exact attempt before remote attachment. Promotion is a separate caller after successful handoff.'),
        ], [
            edge('physical-checks', 'calculate', 'reports handed to certificate job', 'step'),
            edge('calculate', 'coverage', 'certify(...); after subject guards', 'call'),
            edge('coverage', 'eligibility', 'compute and return certificate', 'step'),
            edge('eligibility', 'attachment', 'separate execute-enabled attachment operation', 'step'),
            edge('attachment', 'attachment-helper', 'attach_certificate(...)', 'call'),
        ], scope='Grouped physical execution, exact certificate calculation and separate immutable attachment boundary.'))

    maps.append(diagram(
        'release-promote', 'Exact certificate verification precedes the Latest mutation',
        'A separate promotion dispatcher chooses execute. The helper rejects unsupported subjects, revalidates remote assets and '
        'the exact certificate, changes Latest, then reads it back. Hosted metadata-only handoffs use verified API digests and bound evidence.',
        [
            c('entry', 'Promotion dispatcher explicitly selects plan or execution', lifecycle,
              "write('build/receipts/' + command + '.json', delivery.promote(**request, execute=command == 'promote'))", 0,
              note='request above binds run/attempt/certificate SHA and sets metadata_only=True. promotion-plan leaves execute false.'),
            c('subject', 'Promote rejects experiment/base/mismatched subjects', delivery,
              'def promote(repository,tag,directory,delivery,policy,profile,run_id,attempt,certificate_sha256,*,execute=False,transport=None,metadata_only=False):\n'
              '    location(repository,tag);validate_delivery(delivery,directory,metadata_only=metadata_only)\n'
              "    if (repository,tag)!=(delivery['repository'],delivery['tag']) or delivery['experiment'] or tag=='base':\n"
              "        raise DeliveryError('only this ordinary application release can be promoted')", 1,
              supporting=True,
              note='Exact run/attempt/certificate-SHA validation follows. execute=False returns a plan before remote mutation.'),
            c('certificate', 'Executing branch revalidates assets and certificate', delivery,
              'remote.visible();info,assets=verified_remote(remote,delivery,directory,readback=not metadata_only,metadata_only=metadata_only)\n'
              '        evidence=verify_certificate(remote,assets,delivery,directory,policy,profile,run_id,attempt,certificate_sha256,metadata_only=metadata_only)', 2,
              supporting=True,
              note='Remote identity and policy are checked again before changing Latest; metadata_only controls repeated payload downloads.'),
            c('latest-write', 'Change the exact release to stable Latest', delivery,
              'remote.change(f\'/releases/{info["id"]}\',method=\'PATCH\',body={\'draft\':False,\'prerelease\':False,\'make_latest\':\'true\'})', 3),
            c('latest-readback', 'Read back and verify the Latest pointer', delivery,
              "latest=remote.transport.json(remote.base+'/releases/latest')\n"
              '        remote.info(latest,tag)\n'
              "        if latest['id']!=info['id'] or latest['draft'] or latest['prerelease']:\n"
              "            raise DeliveryError('Latest pointer does not identify the exact certified release')", 4,
              note='Promoted lifecycle, assets and tag are also rechecked immediately before this excerpt.'),
            c('independent-final', 'Hosted final job independently verifies the outcome', hosted,
              'run: python3 -B tools/latest_release.py verify --output build/latest-verification.json', 5,
              supporting=True,
              note='This is a later workflow process, not a call from promote. Preparation-only runs verify that remote publication was not requested.'),
        ], [
            edge('entry', 'subject', 'promote(**request)', 'call'),
            edge('subject', 'certificate', 'only execute=True; more guards omitted', 'conditional'),
            edge('certificate', 'latest-write', 'exact evidence + unchanged identity/policy', 'step'),
            edge('latest-write', 'latest-readback', 'after lifecycle/assets/tag recheck', 'step'),
            edge('latest-readback', 'independent-final', 'separate final workflow job', 'step', emphasis='supporting'),
        ], scope='Actual promotion branch plus separately scheduled final verification.'))

    for item in maps:
        item['category'] = 'workflow'
    bindings = {
        'compile/compile-entry': jump('build-entry', 'entry'),
        'compile/compile-main': jump('build-entry', 'execute'),
        'compile/compile-configure': jump('build-sequence', 'configure'),
        'compile/compile-build': jump('build-sequence', 'compile'),
        'compile/compile-cpp': jump('cmake-core', 'core'),
        'compile/compile-rust': jump('rust-component', 'custom-target'),
        'compile/compile-link': jump('cmake-core', 'cli'),
        'compile/compile-result': jump('build-result', 'post-compile'),
        'test/test-entry': jump('build-entry', 'entry'),
        'test/test-main': jump('build-entry', 'arguments'),
        'test/test-configure': jump('test-registration', 'aggregate'),
        'test/test-build': jump('build-sequence', 'selection'),
        'test/test-ctest': jump('build-sequence', 'ctest'),
        'test/test-core': jump('native-test', 'entry'),
        'test/test-python': jump('python-test', 'execute'),
        'test/test-result': jump('build-result', 'final-source'),
        'release/release-entry': jump('release-entry', 'hosted'),
        'release/release-package': jump('release-package', 'cpack'),
        'release/release-inventory': jump('release-package', 'artifact'),
        'release/release-assemble': jump('release-assemble', 'call'),
        'release/release-publish': jump('release-publish', 'entry'),
        'release/release-certificate': jump('release-certify', 'calculate'),
        'release/release-promote': jump('release-promote', 'entry'),
        'release/release-result': jump('release-promote', 'latest-readback'),
    }
    return {'maps': maps, 'bindings': bindings}
