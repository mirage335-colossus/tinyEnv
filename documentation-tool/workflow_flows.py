"""Existing build, test and release routes, described from captured source only.

These diagrams do not execute tools or evaluate CMake/workflow configuration.
Process arrows distinguish executable handoffs from ordinary function calls.
"""


def make_workflow_flows(ref, node, edge, finish):
    """Return bounded, source-backed process diagrams using flow_maps helpers."""
    build = 'tools/build.py'
    cmake = 'CMakeLists.txt'
    rust = 'cmake/RustComponent.cmake'
    runner = 'tools/run_tests.py'
    delivery = 'tools/github_release.py'
    lifecycle = '.github/scripts/lifecycle.py'
    hosted = '.github/workflows/_release-latest.yml'

    def evidence(label, path, needle):
        return ref(label, path, needle)

    shell_entry = evidence('Shell wrapper replaces itself with Python', 'build.sh',
                           'exec "${PYTHON:-python3}" "$root/tools/build.py" "$@"')
    parse_entry = evidence('Build CLI parses arguments', build, 'def main(argv=None):')
    execute_call = evidence('main calls execute', build, 'result = execute(args, parser, timings)')
    configure_call = evidence('Configuration subprocess', build,
                              'timings.call("configure", run, configure, env=child_environment)')
    timing_call = evidence('Timing wrapper calls the supplied function', build,
                           'def call(self, name, function, *args, **kwargs):')
    process_call = evidence('Build helper calls the platform process wrapper', build,
                            'windows_compiler.run(command, cwd=ROOT, **kwargs)')
    subprocess_call = evidence('Non-Windows child process invocation', 'tools/windows_compiler.py',
                               'return subprocess.run(command, cwd=cwd, env=env, check=True)')
    compile_call = evidence('Selected targets passed to cmake --build', build,
                            'timings.call("compile", run, [programs["cmake"], "--build", str(build), "--parallel", str(jobs), "--target", *targets], env=child_environment)')
    source_check = evidence('Source identity checked after compilation', build,
                            'raise ValueError("source changed during compilation; rebuild a stable candidate")')
    sdk_check = evidence('Selected SDK identity checked before success', build,
                         'if args.sdk and timings.call("sdk_verification", sdk_identity, args.sdk.resolve()) != identity["sdk"]["sha256"]:')
    core_target = evidence('Declared C++ core source files', cmake,
                           'add_library(foundation_core STATIC src/store.cpp src/text_validation.cpp)')
    cli_target = evidence('Declared CLI source file', cmake,
                          'add_executable(foundation-cli src/main.cpp)')
    cli_link = evidence('CLI links the core library', cmake,
                        'target_link_libraries(foundation-cli PRIVATE foundation::core)')
    rust_target = evidence('CMake custom Rust build command', rust,
                           'COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/rust_build.py" build --config "${selected_config}"')
    rust_verify = evidence('CMake custom Rust archive verification command', rust,
                           'COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/rust_build.py" verify --config "${selected_config}"')
    cargo_call = evidence('Rust builder creates the Cargo command', 'tools/rust_build.py',
                          "argv = [data['tools']['cargo']['path'], 'build', '--frozen', '--jobs', '1',")
    rust_link = evidence('Selected Rust component linked into the C++ core', rust,
                         'target_link_libraries(${core} PRIVATE foundation::rust_component)')

    compile_map = finish(
        'compile', 'Compile the application',
        'What code and tools are called when I ask to compile?',
        'Representative build route: build.sh build dev enters the Python wrapper, configures CMake and builds selected targets. '
        'The CLI/core path is shown, with a conditional Rust component; optional GUI and other targets follow the configured graph. '
        'CMake source declarations describe inputs, while the selected generator actually schedules compiler/linker processes. '
        'The diagram does not resolve presets, variables, conditions or generator expressions.',
        'CALL means a literal function call; PROCESS means an executable or generated build step; STEP means ordered orchestration. '
        'The Rust branch is conditional. Parallel target prerequisites are not a fixed chronological trace.',
        [
            node('compile-entry', 'ENTRY', 'build.sh', 'exec → tools/build.py',
                 'The shell wrapper finds its directory and replaces itself with the selected Python interpreter, '
                 'passing the requested action, preset and remaining arguments to tools/build.py.',
                 'This is the user entry point, and exec is a process handoff.',
                 0, 0, [shell_entry]),
            node('compile-main', 'CALL', 'main → execute', 'Parse action, preset and options',
                 'main parses the CLI, creates PhaseTimings, then calls execute. execute selects build/dependency/provider '
                 'inputs and rejects incompatible or changed configuration identities before invoking build tools.',
                 'Arguments and retained input identity determine the configured path.',
                 1, 0, [parse_entry, execute_call,
                        evidence('Build operation implementation', build, 'def execute(args, parser, timings):')]),
            node('compile-configure', 'PROCESS', 'run → cmake --preset', 'Configure the build directory',
                 'execute constructs the configure command and calls PhaseTimings.call("configure", run, ...). '
                 'run delegates to windows_compiler.run, which launches the child process using the selected platform wrapper.',
                 'Configuration produces the target graph; reading CMake alone does not configure it.',
                 2, 0, [configure_call, timing_call, process_call, subprocess_call,
                        evidence('Symbolic configure command construction', build,
                                 'configure = ["cmake", "--preset", preset, "-B", str(build),')]),
            node('compile-build', 'PROCESS', 'cmake --build', 'Build selected target prerequisites',
                 'The same process wrapper runs cmake --build with the chosen build directory, concurrency and targets. '
                 'A plain build selects all. The configured generator schedules each target and its prerequisites.',
                 'Compiler commands and their ordering depend on configuration and generator.',
                 3, 0, [compile_call, evidence('Plain-build default target selection', build, 'targets = ["all"]')]),
            node('compile-cpp', 'PROCESS', 'C++ compiler → core', 'store.cpp + text_validation.cpp; main.cpp',
                 'The generated build compiles foundation_core from the declared store and text-validation C++ files, '
                 'and foundation-cli from main.cpp. The Rust provider still retains this C++ Store/front-end layer.',
                 'These are declarative source inputs to generated compiler processes.',
                 3, 1, [core_target, cli_target]),
            node('compile-rust', 'PROCESS', 'foundation-rust → Cargo', 'Conditional provider prerequisite',
                 'When the Rust provider is selected, the custom target invokes rust_build.py build and verify. '
                 'The builder runs Cargo build --frozen with the selected target/configuration and one job, '
                 'then the configured Rust static component becomes a core link prerequisite.',
                 'C++ provider selection omits this branch. Cargo build and Cargo test are distinct operations.',
                 2, 1, [rust_target, rust_verify, cargo_call, rust_link,
                        evidence('Default provider selection', cmake,
                                 'set(FOUNDATION_CORE_PROVIDER "rust" CACHE STRING "Text validation implementation: rust (default) or cpp")')]),
            node('compile-link', 'PROCESS', 'Link foundation-cli', 'CLI → foundation::core',
                 'The generated linker step combines the CLI object with foundation::core and its selected dependencies. '
                 'Optional GUI executable targets have their own configured source and link declarations.',
                 'Both relevant C++ objects and any selected Rust prerequisite must be ready; their work may overlap.',
                 1, 1, [cli_link, rust_link]),
            node('compile-result', 'OUTPUT', 'execute → success / error', 'Compiled outputs and final input checks',
                 'After compilation, the wrapper rechecks source identity and selected SDK/tool inputs. '
                 'Only an unchanged, successful operation returns zero; child-process and identity failures produce an error exit.',
                 'A compiler-produced binary alone does not establish a stable input identity.',
                 0, 1, [source_check, sdk_check,
                        evidence('Build CLI failure exit', build,
                                 'except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:')]),
        ], [
            edge('compile-entry', 'compile-main', 'exec Python', 'process'),
            edge('compile-main', 'compile-configure', 'execute → timing → run', 'call'),
            edge('compile-configure', 'compile-build', 'back in execute: --build', 'step'),
            edge('compile-build', 'compile-cpp', 'generated compiler steps', 'process'),
            edge('compile-build', 'compile-rust', 'if provider = rust', 'conditional'),
            edge('compile-cpp', 'compile-link', 'generator: objects ready', 'step'),
            edge('compile-rust', 'compile-link', 'if Rust: link prerequisite', 'conditional'),
            edge('compile-link', 'compile-result', 'process result + identity', 'return'),
        ])

    test_map = finish(
        'test', 'Run selected tests',
        'What code is called when I ask to test, and where does execution enter a test?',
        'Representative test route: build.sh test dev configures and compiles the selected registered prerequisites '
        'before invoking CTest. The two child branches below illustrate core.store and tools.*; they are not the entire '
        'test inventory. Labels, named tests, full selection and platform conditions determine which programs actually run. '
        'This documentation only reads declarations and never invokes the test runner.',
        'CALL means a source-visible call; PROCESS means a launched program; STEP means ordered orchestration. Conditional branches are representative '
        'CTest dispatch choices, not an assertion that these tests always execute.',
        [
            node('test-entry', 'ENTRY', 'build.sh test', 'Python wrapper receives the test action',
                 'The shell entry passes test, preset and selection arguments into tools/build.py. '
                 'An explicit test action is an application-tool invocation; the documentation generator never calls it.',
                 'The same wrapper owns both compilation prerequisites and test dispatch.',
                 0, 0, [shell_entry, parse_entry]),
            node('test-main', 'CALL', 'main → execute', 'Parse test selection and options',
                 'main calls execute. The action, --tests or --label/--full choice, test concurrency and optional JUnit '
                 'output are parsed before configuration and selection.',
                 'Selected tests and configured platform decide the runtime branch.',
                 1, 0, [execute_call,
                        evidence('Named test prerequisite selection', build,
                                 'exact_selection = timings.call("test_selection", named_selection, build, args.tests, programs, child_environment)')]),
            node('test-configure', 'PROCESS', 'CMake → CTest inventory', 'Configure registered tests and prerequisites',
                 'The configure subprocess evaluates add_test declarations and registered prerequisite targets. '
                 'foundation_finalize_test_prerequisites writes the configured inventory and creates aggregate foundation-tests targets.',
                 'The documentation shows declarations; the real configured inventory is produced by CMake.',
                 2, 0, [configure_call,
                        evidence('Registered prerequisite metadata', 'cmake/TestPrerequisites.cmake',
                                 'function(foundation_test_prerequisites name)'),
                        evidence('Aggregate test prerequisite target', 'cmake/TestPrerequisites.cmake',
                                 'add_custom_target(foundation-tests DEPENDS ${all_targets})')]),
            node('test-build', 'PROCESS', 'cmake --build', 'Compile selected test prerequisites',
                 'Named test selection supplies its registered prerequisite targets; label/full selection uses '
                 'foundation-tests or its label-specific aggregate. The wrapper builds them before starting CTest.',
                 'CTest does not implicitly compile an EXCLUDE_FROM_ALL test executable.',
                 3, 0, [compile_call,
                        evidence('Label/full aggregate selection', build,
                                 'targets = ["foundation-tests" + ("-" + args.label if args.label else "")]'),
                        evidence('Core test executable is excluded from plain all', cmake,
                                 'add_executable(foundation_core_test EXCLUDE_FROM_ALL tests/store_test.cpp)')],
                 link_map='compile'),
            node('test-ctest', 'PROCESS', 'run → ctest', 'Configured child-program dispatch',
                 'execute constructs ctest --test-dir ... --output-on-failure --no-tests=error and applies selection/concurrency. '
                 'PhaseTimings calls run to launch it. Optional --show-only discovery is a timing probe, not test execution.',
                 'CTest uses the configured test commands, including native, Python and conditional Rust/GUI programs.',
                 3, 1, [evidence('CTest command construction', build,
                                'command = [programs["ctest"], "--test-dir", str(build), "--output-on-failure",'),
                        evidence('CTest execution subprocess', build,
                                 'timings.call("test_execution", run, command, env=child_environment)')]),
            node('test-core', 'CALL', 'core.store → main', 'Native foundation_core_test example',
                 'For a selected native core.store test, CTest launches foundation_core_test, entering '
                 'tests/store_test.cpp main. It calls Store operations and checks accepted/rejected input and identity behavior. '
                 'The browser configuration instead wraps the compiled test with its retained Node runtime.',
                 'This is an actual test-program entry point, not the application CLI main.',
                 2, 1, [evidence('Native core.store test command', cmake,
                                'add_test(NAME core.store COMMAND foundation_core_test)'),
                        evidence('Core contract test entry', 'tests/store_test.cpp', 'int main() {'),
                        evidence('Core contract test calls Store', 'tests/store_test.cpp',
                                 'const auto a = store.add("Alpha");')]),
            node('test-python', 'CALL', 'run_tests → unittest', 'Selected tools.* suite example',
                 'For a selected tools.* test, CTest launches run_tests.py with a registered suite. main loads that suite '
                 'and calls execute; execute invokes unittest.TextTestRunner and records individual results and platform exclusions.',
                 'The selected suite is dynamic; incomplete required outcomes do not become a passing result.',
                 1, 1, [evidence('Configured Python-suite command', cmake,
                                'add_test(NAME tools.${suite} COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tools/run_tests.py"'),
                        evidence('Suite main calls execute', runner,
                                 'result = execute(unittest.defaultTestLoader.loadTestsFromModule(module))'),
                        evidence('unittest child calls', runner,
                                 'result = unittest.TextTestRunner(stream=stream or sys.stderr, verbosity=2, resultclass=Recorded).run(unittest.TestSuite(selected))')]),
            node('test-result', 'OUTPUT', 'Results → wrapper exit', 'Selected results and final identity checks',
                 'Child programs return results to CTest; failed CTest execution fails the wrapper. Python suites publish '
                 'their result file and return zero only for passed status. After execution, execute rechecks source and selected '
                 'dependency/tool identity before reporting success.',
                 'A selected passing subset is not a claim of complete release certification.',
                 0, 1, [evidence('Python suite result publication', runner, 'publish(args.output, result)'),
                        evidence('Python suite pass/fail exit', runner,
                                 "return 0 if result['status'] == 'passed' else 1"),
                        evidence('Final source identity after additional writers', build,
                                 'if args.action != "build" and timings.call("source_verification", source_tree, ROOT, args.gui_source) != source_before:'),
                        sdk_check]),
        ], [
            edge('test-entry', 'test-main', 'exec Python', 'process'),
            edge('test-main', 'test-configure', 'execute → configure', 'process'),
            edge('test-configure', 'test-build', 'execute: build prerequisites', 'step'),
            edge('test-build', 'test-ctest', 'back in execute: CTest', 'step'),
            edge('test-ctest', 'test-core', 'if native core.store selected', 'conditional'),
            edge('test-ctest', 'test-python', 'if tools.* suite selected', 'conditional'),
            edge('test-core', 'test-result', 'program → CTest result', 'return'),
            edge('test-python', 'test-result', 'suite → CTest result', 'return'),
        ])

    release_map = finish(
        'release', 'Package, publish and promote a release',
        'Which code creates archives, and which code changes a remote release or Latest?',
        'The ordinary hosted lifecycle below links separate workflow jobs/processes. The manual RELEASE procedure may '
        'stop at a complete local release and certify it locally first; delivered bytes must still be certified before promotion. '
        'Hosted production requires full regression before assembly/publication. Remote helpers default to planning '
        '(execute=False); an execute-enabled lifecycle is a distinct explicit choice. This diagram reads those routes only.',
        'STEP arrows mean workflow/manual handoffs, not one Python call stack. Conditional arrows mark explicit '
        'remote execution. Archive creation, local assembly, certificate attachment and Latest promotion are separate boundaries.',
        [
            node('release-entry', 'DECISION', 'Manual / hosted release', 'RELEASE or _release-latest.yml',
                 'RELEASE documents manual local steps. The hosted ordinary lifecycle calls sdk-application with '
                 'require_regression=true, then certification and promotion when execute is selected. Its receipt gate checks '
                 'the nested full regression rather than rerunning it.',
                 'A local package request does not itself publish a candidate or change Latest.',
                 0, 0, [evidence('Manual release entry and ordering', 'RELEASE',
                                'Software Foundation — release and recovery order'),
                        evidence('Hosted application workflow handoff', hosted,
                                 'uses: ./.github/workflows/sdk-application.yml'),
                        evidence('Hosted full-regression requirement', hosted, 'require_regression: true')]),
            node('release-package', 'PROCESS', 'build.py → CPack', 'Compile/package exact selected inputs',
                 'The package action configures/builds, then calls CPack with CPackConfig.cmake. Hosted prepared_package '
                 'first runs build.py test release --full against prepared inputs, then changes that command to package. '
                 'The selected archive is copied into the producer handoff.',
                 'CPack creates an archive; it neither assembles a complete release nor uploads it.',
                 1, 0, [evidence('Package action invokes CPack', build,
                                'timings.call("package", run, [programs["cpack"], "--config", str(build / "CPackConfig.cmake"), "-C", "Release"], env=child_environment)'),
                        evidence('Hosted producer starts with full test action', 'tools/ci_plan.py',
                                 "command = [sys.executable, str(root / 'tools/build.py'), 'test', 'release', '--full',"),
                        evidence('Hosted producer switches to package action', 'tools/ci_plan.py',
                                 "package_command[2] = 'package'")], link_map='test'),
            node('release-inventory', 'CALL', 'artifact.describe / verify', 'Inventory and verify the actual archive',
                 'The manual procedure calls artifact.py create and verify. Hosted prepared_package calls artifact.describe '
                 'and artifact.verify on the selected archive. The build wrapper also offers these subprocesses through '
                 '--verify-package; ordinary package creation alone does not run them.',
                 'These checks describe/verify archive contents and relocation, not certification or remote publication.',
                 2, 0, [evidence('Hosted archive descriptor call', 'tools/ci_plan.py',
                                "module('coverage').write_new(descriptor, a.describe(archive))"),
                        evidence('Hosted actual archive verification', 'tools/ci_plan.py',
                                 "a.verify(archive, descriptor, sdk=work / 'sdk' if (work / 'sdk/sdk.json').is_file() else None,"),
                        evidence('Artifact creation CLI', 'tools/artifact.py',
                                 'args.manifest.write_text(json.dumps(describe(args.archive), indent=2) + "\\n")')]),
            node('release-assemble', 'CALL', 'release.assemble', 'Complete verified local candidate',
                 'ci_plan.assemble_release or the manual release CLI calls release.assemble. It copies the prebuilt source/archive '
                 'inputs and exact dependency groups into new staging, verifies the complete release, then commits the new local directory. '
                 'The hosted assembly job also requires its full regression result to succeed.',
                 'Assembly consumes existing archives. It neither recompiles them nor publishes remotely.',
                 3, 0, [evidence('Hosted helper calls local assembly', 'tools/ci_plan.py',
                                "return module('release').assemble(spec_path, base, output)"),
                        evidence('Local assembly implementation', 'tools/release.py', 'def assemble(spec_path, base, output):'),
                        evidence('Hosted publication waits for required regression', '.github/workflows/sdk-application.yml',
                                 "if: ${{ always() && needs.prepare.result == 'success' && needs.application.result == 'success' && ((inputs.require_regression && needs.regression.result == 'success') || (!inputs.require_regression && needs.regression.result == 'skipped')) }}")]),
            node('release-publish', 'PROCESS', 'publish_candidate', 'Explicit execute → remote prerelease',
                 'An execute-enabled publisher creates a new tag/draft, uploads immutable candidate assets, verifies the '
                 'remote inventory/digests, then publishes it as a prerelease. execute=False returns a plan. '
                 'The candidate deliberately remains outside Latest while certification is pending.',
                 'The remote helper is a separate operation after local assembly; existing tags/releases are not overwritten.',
                 3, 1, [evidence('Remote candidate helper and default planning', delivery,
                                'def publish_candidate(repository, tag, directory, source_commit, packager_commit, publication_id,'),
                        evidence('Candidate publication explicitly keeps Latest false', delivery,
                                 'remote.change(f\'/releases/{info["id"]}\', method=\'PATCH\', body={\'draft\':False,\'prerelease\':True,\'make_latest\':\'false\'})'),
                        evidence('Hosted explicit publication call', lifecycle,
                                 "write('build/receipts/publication.json', delivery.publish_candidate(**request, execute=True))")]),
            node('release-certificate', 'CALL', 'Qualify → certify → attach', 'Reports bound to delivered bytes',
                 'The hosted certify workflow qualifies exact downloaded candidate bytes in required environments. '
                 'lifecycle calls qualification_tasks.prepare/run, then certify_release.certify merges the exact reports, '
                 'checks inventory/policy/environment coverage and emits eligibility. attach_certificate appends that attempt.',
                 'A green packaging job alone is insufficient. Certification neither publishes nor promotes, and experiments are ineligible.',
                 2, 1, [evidence('Hosted delivered-byte certification boundary', hosted,
                                'name: Certify exact remotely downloaded bytes and attach immutable evidence'),
                        evidence('Physical qualification dispatch', lifecycle,
                                 "operation = qualification_tasks.prepare if command == 'check-prerequisites' else qualification_tasks.run"),
                        evidence('Certificate calculation call', lifecycle,
                                 'result = certify_release.certify(directory, ci.module(\'release\').verify_metadata(directory), plan, reports,'),
                        evidence('Certification eligibility rule', 'tools/certify_release.py',
                                 '"eligible_for_promotion": passed and not experiment, "experiment": experiment,'),
                        evidence('Certificate attachment implementation', delivery,
                                 'def attach_certificate(repository, tag, directory, delivery, certificate, check_plan, policy, profile,')]),
            node('release-promote', 'CALL', 'github_release.promote', 'Exact certificate → change Latest',
                 'An explicit execute=True promotion requires the exact certification run, attempt and certificate SHA. '
                 'It verifies the remote asset inventory and certificate, rejects experiments/ineligible evidence, then changes '
                 'the ordinary release to stable Latest. The hosted metadata-only handoff uses verified API digests and bound evidence.',
                 'Changing Latest is a separate remote mutation. Helper defaults remain planning-only.',
                 1, 1, [evidence('Promotion implementation and planning default', delivery,
                                'def promote(repository,tag,directory,delivery,policy,profile,run_id,attempt,certificate_sha256,*,execute=False,transport=None,metadata_only=False):'),
                        evidence('Exact remote certificate revalidation', delivery,
                                 'evidence=verify_certificate(remote,assets,delivery,directory,policy,profile,run_id,attempt,certificate_sha256,metadata_only=metadata_only)'),
                        evidence('Hosted promotion call and execute choice', lifecycle,
                                 "write('build/receipts/' + command + '.json', delivery.promote(**request, execute=command == 'promote'))")]),
            node('release-result', 'OUTPUT', 'Verify Latest identity', 'Read back the exact promoted release',
                 'promote rechecks the release lifecycle, assets, tag and /releases/latest pointer. The hosted final job '
                 'independently calls latest_release.py verify and retains its receipt. A preparation-only run records that no '
                 'public candidate/certification/Latest change was requested.',
                 'A successful HTTP mutation is followed by identity checks; a local release may stop before any remote step.',
                 0, 1, [evidence('Promotion reads the remote Latest pointer', delivery,
                                "latest=remote.transport.json(remote.base+'/releases/latest')"),
                        evidence('Hosted final independent verification', hosted,
                                 'run: python3 -B tools/latest_release.py verify --output build/latest-verification.json'),
                        evidence('Manual separately authorized publication boundary', 'RELEASE',
                                 '10. When separately authorized, publish immutable assets, reverify downloads,')]),
        ], [
            edge('release-entry', 'release-package', 'manual / hosted producer', 'step'),
            edge('release-package', 'release-inventory', 'actual final archive', 'step'),
            edge('release-inventory', 'release-assemble', 'complete producer handoffs', 'step'),
            edge('release-assemble', 'release-publish', 'if remote execution requested', 'conditional'),
            edge('release-publish', 'release-certificate', 'hosted delivered-byte qualification', 'step'),
            edge('release-certificate', 'release-promote', 'eligible + explicit execute', 'conditional'),
            edge('release-promote', 'release-result', 'readback + final receipt', 'step'),
        ])

    return [compile_map, test_map, release_map]
