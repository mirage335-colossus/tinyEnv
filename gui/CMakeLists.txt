foundation_register_build_directory()
option(FOUNDATION_GUI_FLTK "Build the FLTK native host" OFF)
option(FOUNDATION_GUI_SDL "Build the SDL framebuffer window host" OFF)
option(FOUNDATION_GUI_REV "Build the Rev native host" OFF)
option(FOUNDATION_GUI_WEB "Build the hosted browser bridge" ON)
option(FOUNDATION_GUI_HOST_TESTS "Run PTY, loopback and native display checks" OFF)
include("${CMAKE_CURRENT_SOURCE_DIR}/../cmake/GuiInputs.cmake")
foundation_gui_inputs()
# Watch every file under the owned source trees, including future source suffixes.
# The Python guard selects source types; CMake must still invalidate its stamp.
file(GLOB_RECURSE foundation_gui_owned_sources LIST_DIRECTORIES FALSE CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/shared/*" "${CMAKE_CURRENT_SOURCE_DIR}/host/*"
    "${CMAKE_CURRENT_SOURCE_DIR}/hosts/*" "${CMAKE_CURRENT_SOURCE_DIR}/../rust/*")
execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_CURRENT_SOURCE_DIR}/check_boundary.py" --dependencies
    OUTPUT_VARIABLE foundation_gui_transitive_sources COMMAND_ERROR_IS_FATAL ANY)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${foundation_gui_transitive_sources})
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/boundary-checked"
    COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_CURRENT_SOURCE_DIR}/check_boundary.py"
    COMMAND "${CMAKE_COMMAND}" -E touch "${CMAKE_CURRENT_BINARY_DIR}/boundary-checked"
    DEPENDS ${foundation_gui_owned_sources} ${foundation_gui_transitive_sources}
        "${CMAKE_CURRENT_SOURCE_DIR}/check_boundary.py" VERBATIM)
add_custom_target(foundation_gui_contract DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/boundary-checked")
if(EMSCRIPTEN)
    set(foundation_task_executor shared/task_cooperative.cpp)
else()
    set(foundation_task_executor shared/task_native.cpp)
endif()
add_library(foundation_gui_application STATIC shared/application.cpp ${foundation_task_executor})
add_dependencies(foundation_gui_application foundation_gui_contract)
target_link_libraries(foundation_gui_application PUBLIC foundation_gui_boundary foundation::core)
target_include_directories(foundation_gui_application PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
set_target_properties(foundation_gui_application PROPERTIES CXX_EXTENSIONS OFF)
foundation_options(foundation_gui_application)

function(gui_warnings target)
    foundation_options(${target})
endfunction()
add_custom_target(foundation-gui-hosts)
function(foundation_gui_executable target source)
    add_executable(${target} "${CMAKE_CURRENT_SOURCE_DIR}/${source}")
    if(WIN32 AND target MATCHES "^foundation-gui-(fltk|rev|sdl)$")
        # Composition-only entry adaptation: shared application code keeps main's
        # ordinary argc/argv contract and knows nothing about the Windows host.
        set_target_properties(${target} PROPERTIES WIN32_EXECUTABLE TRUE)
        target_compile_definitions(${target} PRIVATE main=foundation_gui_main SDL_MAIN_HANDLED)
        if(target STREQUAL "foundation-gui-sdl")
            target_compile_definitions(${target} PRIVATE FOUNDATION_GUI_SDL_ENTRY)
        endif()
        target_sources(${target} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/hosts/windows_gui_entry.cpp")
        if(MSVC)
            target_link_options(${target} PRIVATE /MANIFEST:EMBED
                "/MANIFESTINPUT:${CMAKE_CURRENT_SOURCE_DIR}/hosts/windows_gui.manifest")
        else()
            enable_language(RC)
            target_include_directories(${target} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/hosts")
            target_sources(${target} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/hosts/windows_gui.rc")
        endif()
    endif()
    target_link_libraries(${target} PRIVATE foundation_gui_application)
    target_include_directories(${target} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
    foundation_options(${target})
    if(target MATCHES "^foundation-gui-")
        add_dependencies(foundation-gui-hosts ${target})
    endif()
    if(FOUNDATION_GUI_DISTRIBUTABLE AND target MATCHES "^foundation-gui-" AND NOT EMSCRIPTEN)
        install(TARGETS ${target} RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
    endif()
endfunction()
function(foundation_gui_check name target labels)
    set_target_properties(${target} PROPERTIES EXCLUDE_FROM_ALL TRUE)
    add_test(NAME "foundation.gui.${name}" COMMAND ${target})
    set_tests_properties("foundation.gui.${name}" PROPERTIES LABELS "gui;${labels}" TIMEOUT 90)
    foundation_test_prerequisites("foundation.gui.${name}" ${target})
endfunction()
function(foundation_gui_sdl_display_test name)
    # Qualify the declared native service; minimal SDKs need no dummy driver.
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
        set(driver x11)
    elseif(CMAKE_SYSTEM_NAME STREQUAL "Windows")
        set(driver windows)
    else()
        message(FATAL_ERROR "Declare the native SDL video driver for this qualification host")
    endif()
    set_tests_properties(${name} PROPERTIES ENVIRONMENT "SDL_VIDEODRIVER=${driver}"
        RESOURCE_LOCK foundation_native_display)
endfunction()
if(BUILD_TESTING)
    add_custom_target(foundation-gui-tests)
endif()
find_program(FOUNDATION_NODE_EXECUTABLE NAMES node nodejs)
foundation_gui_headers()
# Keep the browser asset names stable; both transport modes use the same renderer.
foundation_gui_patch(include/gui/web.hpp web-tick.patch patch-inputs/web-ticked.hpp)
foundation_gui_repatch(patch-inputs/web-ticked.hpp web-file-transfer.patch include/gui/web.hpp)
foundation_gui_patch(backends/web/renderer.mjs web-ordering.patch patch-inputs/renderer-ordered.mjs)
foundation_gui_repatch(patch-inputs/renderer-ordered.mjs web-responsiveness.patch patch-inputs/renderer-responsive.mjs)
foundation_gui_repatch(patch-inputs/renderer-responsive.mjs web-file-services.patch patch-inputs/renderer-services.mjs)
foundation_gui_repatch(patch-inputs/renderer-services.mjs web-split.patch web/renderer_dom.mjs)
configure_file(host/renderer_compat.mjs "${CMAKE_CURRENT_BINARY_DIR}/web/renderer.mjs" COPYONLY)
foundation_gui_patch(backends/web/boot.mjs web-lifecycle.patch patch-inputs/boot-lifecycle.mjs)
foundation_gui_repatch(patch-inputs/boot-lifecycle.mjs web-presentation.patch patch-inputs/boot-presentation.mjs)
foundation_gui_repatch(patch-inputs/boot-presentation.mjs web-embedding.patch web/boot.mjs)
foundation_gui_patch(backends/web/host.py web-assets.patch web/host.py)
set(foundation_web_modules browser_lifecycle wasm_transport wasm_worker browser_presenter file_services
    browser_client browser_services browser_limits browser_composition renderer_channel renderer_frame browser_embedding)
set(foundation_web_assets "${CMAKE_CURRENT_BINARY_DIR}/web/boot.mjs"
    "${CMAKE_CURRENT_BINARY_DIR}/web/renderer.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/renderer_dom.mjs")
foreach(module IN LISTS foundation_web_modules)
    configure_file("host/${module}.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/${module}.mjs" COPYONLY)
    list(APPEND foundation_web_assets "${CMAKE_CURRENT_BINARY_DIR}/web/${module}.mjs")
endforeach()
if(BUILD_TESTING AND FOUNDATION_NODE_EXECUTABLE)
    add_test(NAME foundation.gui.worker COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/worker_test.mjs"
        "${CMAKE_CURRENT_BINARY_DIR}/web/wasm_transport.mjs"
        "${CMAKE_CURRENT_BINARY_DIR}/web/wasm_worker.mjs")
    foundation_test_prerequisites(foundation.gui.worker)
    set_tests_properties(foundation.gui.worker PROPERTIES LABELS "gui;focused" TIMEOUT 30)
    add_test(NAME foundation.gui.browser-responsiveness COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/browser_responsiveness_test.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/renderer.mjs")
    add_test(NAME foundation.gui.browser-presenter COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/browser_presenter_test.mjs"
        "${CMAKE_CURRENT_BINARY_DIR}/web/browser_presenter.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/renderer.mjs"
        "${CMAKE_CURRENT_BINARY_DIR}/web/boot.mjs")
    add_test(NAME foundation.gui.file-browser COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/file_services_test.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/file_services.mjs")
    add_test(NAME foundation.gui.browser-channel COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/renderer_channel_test.mjs"
        "${CMAKE_CURRENT_BINARY_DIR}/web/renderer_channel.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/browser_client.mjs")
    add_test(NAME foundation.gui.browser-embedding COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/browser_embedding_test.mjs"
        "${CMAKE_CURRENT_BINARY_DIR}/web/browser_embedding.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/browser_composition.mjs")
    add_test(NAME foundation.gui.browser-services COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/browser_services_test.mjs"
        "${CMAKE_CURRENT_BINARY_DIR}/web/browser_services.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/browser_client.mjs")
    foreach(name browser-responsiveness browser-presenter file-browser browser-channel browser-embedding browser-services)
        foundation_test_prerequisites(foundation.gui.${name})
        set_tests_properties(foundation.gui.${name} PROPERTIES LABELS "gui;focused" TIMEOUT 30)
    endforeach()
    foreach(fixture touch queue)
        add_test(NAME foundation.gui.${fixture}-browser COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/${fixture}_test.mjs" "${CMAKE_CURRENT_BINARY_DIR}/web/renderer.mjs")
        foundation_test_prerequisites(foundation.gui.${fixture}-browser)
        set_tests_properties(foundation.gui.${fixture}-browser PROPERTIES LABELS "gui;focused" TIMEOUT 30)
    endforeach()
endif()
file(COPY "${FOUNDATION_GUI_SOURCE}/backends/web/style.css"
    "${FOUNDATION_GUI_SOURCE}/backends/web/index.html" DESTINATION "${CMAKE_CURRENT_BINARY_DIR}/web")
list(APPEND foundation_web_assets "${CMAKE_CURRENT_BINARY_DIR}/web/style.css"
    "${CMAKE_CURRENT_BINARY_DIR}/web/index.html" "${CMAKE_CURRENT_BINARY_DIR}/web/renderer_child_bundle.mjs")
# Generate only the reviewed renderer graph. This output is pure data when
# imported by the privileged parent; child code runs exclusively in its frame.
execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/browser_bundle.py"
    --assets "${CMAKE_CURRENT_BINARY_DIR}/web"
    --output "${CMAKE_CURRENT_BINARY_DIR}/web/renderer_child_bundle.mjs"
    COMMAND_ERROR_IS_FATAL ANY)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${CMAKE_SOURCE_DIR}/tools/browser_bundle.py")
configure_file(hosts/web_host.py "${CMAKE_CURRENT_BINARY_DIR}/web/serve.py" COPYONLY)
if(FOUNDATION_GUI_DISTRIBUTABLE)
    foreach(notice third_party/rev-deps/glew-LICENSE.txt third_party/rev-deps/freetype-LICENSE.TXT
        third_party/rev-deps/freetype-FTL.TXT third_party/rev-deps/freetype-GPLv2.TXT
        third_party/rev/resources/DejaVu-LICENSE third_party/rev/resources/DejaVu-AUTHORS
        third_party/rev/resources/DejaVu-SOURCES.json third_party/rev/external/glm/LICENSE
        third_party/rev/external/nanosvg/LICENSE third_party/rev/UPSTREAM.json
        third_party/rev/README.md third_party/rev/PATCHES.md third_party/rev-deps/UPSTREAM.json)
        foundation_notice_file("${FOUNDATION_GUI_SOURCE}/${notice}")
    endforeach()
    # Admit only the reviewed production closure. A test asset or stale output
    # placed beside these files must never enter an application package.
    install(FILES ${foundation_web_assets} "${CMAKE_CURRENT_BINARY_DIR}/web/host.py"
        "${CMAKE_CURRENT_BINARY_DIR}/web/serve.py"
        DESTINATION "${CMAKE_INSTALL_DATADIR}/software-foundation/web")
    install(FILES "${lock_path}" DESTINATION "${CMAKE_INSTALL_DOCDIR}/gui-boundary")
    foreach(index RANGE 0 ${license_last})
        string(JSON license_file GET "${lock}" redistribution license_files ${index})
        get_filename_component(license_directory "${license_file}" DIRECTORY)
        install(FILES "${FOUNDATION_GUI_SOURCE}/${license_file}"
            DESTINATION "${CMAKE_INSTALL_DOCDIR}/gui-boundary/${license_directory}")
    endforeach()
endif()
if(EMSCRIPTEN)
    foundation_gui_executable(foundation-gui-web-wasm hosts/wasm_main.cpp)
    set_target_properties(foundation-gui-web-wasm PROPERTIES OUTPUT_NAME gui_web_wasm SUFFIX .js)
    target_compile_options(foundation_gui_application PRIVATE -fexceptions)
    target_compile_options(foundation-gui-web-wasm PRIVATE -fexceptions)
    target_link_options(foundation-gui-web-wasm PRIVATE --no-entry -fexceptions
        -sMODULARIZE=1 -sEXPORT_ES6=1 -sALLOW_MEMORY_GROWTH=1
        "-sEXPORTED_FUNCTIONS=['_gui_web_create','_gui_web_receive','_gui_web_destroy']"
        "-sEXPORTED_RUNTIME_METHODS=['ccall']" -sENVIRONMENT=web,worker,node)
    target_link_options(foundation-gui-web-wasm PRIVATE
        "-sINCOMING_MODULE_JS_API=['wasmBinary','locateFile','print','printErr','onRuntimeInitialized']")
    file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/package.json" "{\"type\":\"module\"}\n")
    set(wasm_notice_args --notice "foundation=${CMAKE_SOURCE_DIR}/LICENSE"
        --notice "gui-boundary=${FOUNDATION_GUI_SOURCE}/LICENSE")
    set(wasm_notices "${CMAKE_SOURCE_DIR}/LICENSE" "${FOUNDATION_GUI_SOURCE}/LICENSE")
    if(FOUNDATION_SDK_ROOT)
        list(APPEND wasm_notice_args --sdk "${FOUNDATION_SDK_ROOT}")
        list(APPEND wasm_notices "${FOUNDATION_SDK_ROOT}/sdk.json")
    endif()
    set(wasm_package "${CMAKE_CURRENT_BINARY_DIR}/wasm-package")
    set(wasm_html "${wasm_package}/software-foundation-wasm.html")
    set(wasm_manifest "${wasm_package}/web-manifest.json")
    set(wasm_checksums "${wasm_package}/manifest.sha256")
    execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/source_identity.py"
        digest --root "${CMAKE_SOURCE_DIR}" OUTPUT_VARIABLE wasm_source_identity
        OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
    file(CONFIGURE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/wasm-package-source.txt"
        CONTENT "${wasm_source_identity}\n" @ONLY)
    add_custom_command(OUTPUT "${wasm_html}" "${wasm_manifest}" "${wasm_checksums}"
        COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_SOURCE_DIR}/tools/package_wasm.py"
            --assets "${CMAKE_CURRENT_BINARY_DIR}/web"
            --module-dir "$<TARGET_FILE_DIR:foundation-gui-web-wasm>"
            --output "${wasm_package}" --source-root "${CMAKE_SOURCE_DIR}" ${wasm_notice_args}
        DEPENDS foundation-gui-web-wasm "${CMAKE_CURRENT_BINARY_DIR}/wasm-package-source.txt"
            "${CMAKE_SOURCE_DIR}/tools/source_identity.py" "${CMAKE_SOURCE_DIR}/tools/package_wasm.py"
            "${CMAKE_SOURCE_DIR}/tools/package_notices.py" "${CMAKE_SOURCE_DIR}/tools/sdk_manifest.py"
            "${CMAKE_SOURCE_DIR}/tools/browser_bundle.py" ${foundation_web_assets}
            ${wasm_notices} VERBATIM)
    add_custom_target(foundation-wasm-package ALL DEPENDS "${wasm_html}" "${wasm_manifest}" "${wasm_checksums}")
    if(FOUNDATION_GUI_DISTRIBUTABLE)
        install(FILES "${wasm_html}" "${wasm_manifest}" "${wasm_checksums}"
            DESTINATION "${CMAKE_INSTALL_DATADIR}/software-foundation/wasm")
    endif()
    if(BUILD_TESTING AND FOUNDATION_NODE_EXECUTABLE)
        add_test(NAME foundation.gui.wasm COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/wasm_test.mjs" $<TARGET_FILE:foundation-gui-web-wasm>)
        set_tests_properties(foundation.gui.wasm PROPERTIES LABELS "gui;host" TIMEOUT 60)
        foundation_test_prerequisites(foundation.gui.wasm foundation-gui-web-wasm foundation-wasm-package)
    endif()
    if(FOUNDATION_GUI_DISTRIBUTABLE)
        install(FILES "$<TARGET_FILE:foundation-gui-web-wasm>"
            "$<TARGET_FILE_DIR:foundation-gui-web-wasm>/gui_web_wasm.wasm"
            DESTINATION "${CMAKE_INSTALL_DATADIR}/software-foundation/web")
    endif()
    return()
endif()
foundation_gui_patch(backends/terminal/main.cpp terminal-runner.patch terminal_runner.hpp)
foundation_gui_executable(foundation-gui-terminal hosts/terminal_main.cpp)
foundation_gui_executable(foundation-gui-framebuffer hosts/framebuffer_main.cpp)
if(FOUNDATION_GUI_WEB)
    foundation_gui_executable(foundation-gui-web hosts/web_main.cpp)
endif()
include("${CMAKE_CURRENT_SOURCE_DIR}/../cmake/GuiNativeBackends.cmake")
if(FOUNDATION_GUI_FLTK)
    foundation_gui_native_backend("fltk")
    foundation_gui_executable(foundation-gui-fltk hosts/fltk_main.cpp)
    target_link_libraries(foundation-gui-fltk PRIVATE foundation_gui_fltk)
endif()
if(FOUNDATION_GUI_SDL)
    foundation_gui_native_backend("sdl")
    foundation_gui_executable(foundation-gui-sdl hosts/sdl_main.cpp)
    target_link_libraries(foundation-gui-sdl PRIVATE foundation_gui_sdl)
endif()
if(FOUNDATION_GUI_REV)
    foundation_gui_native_backend("rev")
    foundation_gui_executable(foundation-gui-rev hosts/rev_main.cpp)
    target_link_libraries(foundation-gui-rev PRIVATE gui_rev_adapter)
endif()
if(BUILD_TESTING)
    if(FOUNDATION_GUI_SDL)
        add_executable(foundation_gui_sdl_touch_test "${CMAKE_SOURCE_DIR}/tests/gui_sdl_touch.cpp")
        target_link_libraries(foundation_gui_sdl_touch_test PRIVATE foundation_gui_application foundation_gui_sdl)
        target_include_directories(foundation_gui_sdl_touch_test PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
        foundation_options(foundation_gui_sdl_touch_test)
        foundation_gui_check(sdl-touch foundation_gui_sdl_touch_test focused)
    endif()
    set(smoke_backends terminal framebuffer)
    if(FOUNDATION_GUI_WEB)
        list(APPEND smoke_backends web)
    endif()
    if(FOUNDATION_GUI_HOST_TESTS)
        foreach(backend fltk rev sdl)
            string(TOUPPER "${backend}" upper)
            if(FOUNDATION_GUI_${upper})
                list(APPEND smoke_backends ${backend})
            endif()
        endforeach()
    endif()
    foreach(backend IN LISTS smoke_backends)
        add_test(NAME foundation.gui.installed-${backend} COMMAND ${Python3_EXECUTABLE} -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/installed_host_test.py" $<TARGET_FILE:foundation-gui-${backend}>)
        foundation_test_prerequisites(foundation.gui.installed-${backend} foundation-gui-${backend})
        set_tests_properties(foundation.gui.installed-${backend} PROPERTIES LABELS "gui;host" TIMEOUT 40)
        if(backend STREQUAL "sdl")
            foundation_gui_sdl_display_test(foundation.gui.installed-${backend})
        elseif(backend STREQUAL "fltk" OR backend STREQUAL "rev")
            set_tests_properties(foundation.gui.installed-${backend} PROPERTIES RESOURCE_LOCK foundation_native_display)
        endif()
    endforeach()
    foreach(example touch embedding)
        add_executable(foundation_gui_${example}_test "${CMAKE_SOURCE_DIR}/tests/gui_${example}.cpp")
        target_link_libraries(foundation_gui_${example}_test PRIVATE foundation_gui_boundary)
        target_include_directories(foundation_gui_${example}_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
        foundation_options(foundation_gui_${example}_test)
        foundation_gui_check(${example} foundation_gui_${example}_test focused)
    endforeach()
    foundation_gui_executable(foundation_gui_test tests/application_test.cpp)
    foundation_gui_check(shared-feature foundation_gui_test focused)
    foundation_gui_executable(foundation_gui_terminal_caret_test tests/terminal_caret_test.cpp)
    foundation_gui_check(terminal-caret foundation_gui_terminal_caret_test focused)
    foundation_gui_executable(foundation_gui_task_test tests/task_test.cpp)
    foundation_gui_check(task-lifecycle foundation_gui_task_test focused)
    if(NOT EMSCRIPTEN)
        foundation_gui_executable(foundation_gui_task_native_test tests/task_native_test.cpp)
        foundation_gui_check(task-native foundation_gui_task_native_test focused)
        foundation_gui_executable(foundation_gui_file_test tests/file_services_test.cpp)
        foundation_gui_check(file-content foundation_gui_file_test focused)
    endif()
    foundation_gui_executable(foundation_gui_bezel_test tests/bezel_test.cpp)
    foundation_gui_check(bezel foundation_gui_bezel_test focused)
    foundation_gui_executable(foundation_gui_file_transfer_test tests/file_transfer_test.cpp)
    foundation_gui_check(file-transfer foundation_gui_file_transfer_test focused)
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
        foundation_gui_executable(foundation_gui_no_socket_test tests/no_socket_test.cpp)
        foundation_gui_check(no-socket foundation_gui_no_socket_test focused)
        if(FOUNDATION_GUI_WEB)
            add_test(NAME foundation.gui.worker-isolation COMMAND "${Python3_EXECUTABLE}" -B
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/worker_isolation_test.py"
                $<TARGET_FILE:foundation-gui-web> "${CMAKE_CURRENT_BINARY_DIR}/web/serve.py")
            foundation_test_prerequisites(foundation.gui.worker-isolation foundation-gui-web)
            set_tests_properties(foundation.gui.worker-isolation PROPERTIES LABELS "gui;focused" TIMEOUT 30)
        endif()
    endif()
    foundation_gui_executable(foundation_gui_parity_test tests/parity_test.cpp)
    foundation_gui_check(parity foundation_gui_parity_test focused)
    add_test(NAME foundation.gui.transport COMMAND ${Python3_EXECUTABLE} -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/web_transport_test.py" "${CMAKE_CURRENT_BINARY_DIR}/web/serve.py")
    foundation_test_prerequisites(foundation.gui.transport)
    set_tests_properties(foundation.gui.transport PROPERTIES LABELS "gui;focused" TIMEOUT 15)
    foreach(test_name contract bitmap adapter layout runtime presentation extension interaction framebuffer terminal web)
        set(test_target "foundation_gui_upstream_${test_name}")
        if(test_name STREQUAL "contract" OR test_name STREQUAL "adapter")
            foundation_gui_patch("tests/${test_name}_test.cpp" "${test_name}-portability.patch" "tests/${test_name}_test.cpp")
            set(test_source "${CMAKE_CURRENT_BINARY_DIR}/tests/${test_name}_test.cpp")
        else()
            set(test_source "${FOUNDATION_GUI_SOURCE}/tests/${test_name}_test.cpp")
        endif()
        add_executable(${test_target} "${test_source}")
        target_link_libraries(${test_target} PRIVATE foundation_gui_boundary)
        foundation_options(${test_target})
        # Generated tests retain their original quoted paths to example headers.
        target_include_directories(${test_target} PRIVATE "${FOUNDATION_GUI_SOURCE}/examples" "${FOUNDATION_GUI_SOURCE}/tests")
        if(MSVC)
            target_compile_options(${test_target} PRIVATE /UNDEBUG /utf-8)
        else()
            target_compile_options(${test_target} PRIVATE -UNDEBUG)
        endif()
        foundation_gui_check("upstream.${test_name}" ${test_target} regression)
    endforeach()
    if(FOUNDATION_NODE_EXECUTABLE)
        foundation_gui_patch(tests/web_renderer_test.mjs web-ordering-test.patch tests/web_renderer_test.mjs)
        add_test(NAME foundation.gui.renderer COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
            "${CMAKE_CURRENT_BINARY_DIR}/tests/web_renderer_test.mjs")
        foundation_test_prerequisites(foundation.gui.renderer)
        set_tests_properties(foundation.gui.renderer PROPERTIES LABELS "gui;regression" TIMEOUT 60)
        add_test(NAME foundation.gui.browser-lifecycle COMMAND "${FOUNDATION_NODE_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/browser_lifecycle_test.mjs"
            "${CMAKE_CURRENT_BINARY_DIR}/web/browser_lifecycle.mjs")
        foundation_test_prerequisites(foundation.gui.browser-lifecycle)
        set_tests_properties(foundation.gui.browser-lifecycle PROPERTIES LABELS "gui;focused" TIMEOUT 30)
    endif()
    if(FOUNDATION_GUI_HOST_TESTS)
        if(UNIX)
            add_test(NAME foundation.gui.terminal-host COMMAND ${Python3_EXECUTABLE} -B
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/terminal_host_test.py" $<TARGET_FILE:foundation-gui-terminal>)
            set_tests_properties(foundation.gui.terminal-host PROPERTIES LABELS "gui;host" TIMEOUT 25)
            foundation_test_prerequisites(foundation.gui.terminal-host foundation-gui-terminal)
        endif()
        if(FOUNDATION_GUI_WEB)
            add_test(NAME foundation.gui.web-host COMMAND ${Python3_EXECUTABLE} -B
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/web_host_test.py"
                "${CMAKE_CURRENT_BINARY_DIR}/web/serve.py" $<TARGET_FILE:foundation-gui-web>)
            set_tests_properties(foundation.gui.web-host PROPERTIES LABELS "gui;host" TIMEOUT 90)
            foundation_test_prerequisites(foundation.gui.web-host foundation-gui-web)
        endif()
        foreach(backend fltk rev)
            string(TOUPPER "${backend}" upper)
            if(FOUNDATION_GUI_${upper})
                foundation_gui_executable(foundation_gui_${backend}_test "tests/${backend}_test.cpp")
                if(backend STREQUAL "rev")
                    target_link_libraries(foundation_gui_${backend}_test PRIVATE gui_rev_adapter)
                else()
                    target_link_libraries(foundation_gui_${backend}_test PRIVATE foundation_gui_fltk)
                endif()
                foundation_gui_check("${backend}-host" foundation_gui_${backend}_test host)
                set_tests_properties("foundation.gui.${backend}-host" PROPERTIES RESOURCE_LOCK foundation_native_display)
                # Qualify the selected adapter, including local appearance changes,
                # against the retained generic supplier scenarios as well as our app.
                set(supplier_target "foundation_gui_supplier_${backend}")
                if(backend STREQUAL "rev")
                    foundation_gui_patch(tests/rev_test.cpp rev-conformance-scale.patch tests/supplier_rev_test.cpp)
                    set(supplier_source "${CMAKE_CURRENT_BINARY_DIR}/tests/supplier_rev_test.cpp")
                else()
                    set(supplier_source "${FOUNDATION_GUI_SOURCE}/tests/${backend}_test.cpp")
                endif()
                add_executable(${supplier_target} "${supplier_source}")
                target_include_directories(${supplier_target} PRIVATE "${FOUNDATION_GUI_SOURCE}/examples")
                target_link_libraries(${supplier_target} PRIVATE foundation_gui_boundary)
                if(backend STREQUAL "rev")
                    target_link_libraries(${supplier_target} PRIVATE gui_rev_adapter)
                else()
                    target_link_libraries(${supplier_target} PRIVATE foundation_gui_fltk)
                endif()
                foundation_options(${supplier_target})
                foundation_gui_check("supplier.${backend}" ${supplier_target} "host;regression")
                set_tests_properties("foundation.gui.supplier.${backend}" PROPERTIES RESOURCE_LOCK foundation_native_display)
                if(backend STREQUAL "rev")
                    add_test(NAME foundation.gui.supplier.rev-scaled COMMAND ${supplier_target})
                    foundation_test_prerequisites(foundation.gui.supplier.rev-scaled ${supplier_target})
                    set_tests_properties(foundation.gui.supplier.rev-scaled PROPERTIES
                        LABELS "gui;host;regression" TIMEOUT 90
                        ENVIRONMENT "REV_SCALE=1.25" RESOURCE_LOCK foundation_native_display)
                endif()
            endif()
        endforeach()
        if(FOUNDATION_GUI_REV)
            foundation_gui_patch(tests/rev_clipboard_test.cpp rev-clipboard-ownership.patch tests/supplier_rev_clipboard_test.cpp)
            add_executable(foundation_gui_supplier_clipboard "${CMAKE_CURRENT_BINARY_DIR}/tests/supplier_rev_clipboard_test.cpp")
            target_link_libraries(foundation_gui_supplier_clipboard PRIVATE foundation_gui_boundary gui_rev_adapter)
            foundation_options(foundation_gui_supplier_clipboard)
            if(MSVC)
                target_compile_options(foundation_gui_supplier_clipboard PRIVATE /UNDEBUG)
            else()
                target_compile_options(foundation_gui_supplier_clipboard PRIVATE -UNDEBUG)
            endif()
            foundation_gui_check(supplier.rev-clipboard foundation_gui_supplier_clipboard "host;regression")
            set_tests_properties(foundation.gui.supplier.rev-clipboard PROPERTIES RESOURCE_LOCK foundation_native_display)
        endif()
        if(FOUNDATION_GUI_FLTK AND FOUNDATION_GUI_REV)
            add_test(NAME foundation.gui.visual COMMAND "${Python3_EXECUTABLE}" -B
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/visual_test.py"
                --parity $<TARGET_FILE:foundation_gui_parity_test>
                --fltk $<TARGET_FILE:foundation_gui_fltk_test>
                --rev $<TARGET_FILE:foundation_gui_rev_test>
                --output "${CMAKE_CURRENT_BINARY_DIR}/visual-evidence")
            foundation_test_prerequisites(foundation.gui.visual foundation_gui_parity_test foundation_gui_fltk_test foundation_gui_rev_test)
            set_tests_properties(foundation.gui.visual PROPERTIES LABELS "gui;host;visual" TIMEOUT 180
                RESOURCE_LOCK foundation_native_display)
        endif()
        if(FOUNDATION_GUI_SDL)
            foundation_gui_executable(foundation_gui_sdl_test tests/sdl_test.cpp)
            target_link_libraries(foundation_gui_sdl_test PRIVATE foundation_gui_sdl)
            foundation_gui_check(sdl-host foundation_gui_sdl_test host)
            foundation_gui_sdl_display_test(foundation.gui.sdl-host)
        endif()
    endif()
endif()
# Install rules activate only after the dependency lock records reviewed license inputs.
