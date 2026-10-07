# Shared verified GUI inputs; no application, test or installation targets.
include_guard(GLOBAL)
get_filename_component(foundation_gui_module_root "${CMAKE_CURRENT_LIST_DIR}/../gui" REALPATH)

macro(foundation_gui_inputs)
    # Preserved local input by default; explicit source/group selections take precedence.
    # Configuration never fetches dependencies.
    get_filename_component(foundation_gui_project_root "${foundation_gui_module_root}/.." REALPATH)
    set(FOUNDATION_GUI_SOURCE "" CACHE PATH "Verified gui-boundary source checkout or archive")
    set(FOUNDATION_GUI_INPUT_GROUP "" CACHE PATH "Retained complete GUI input group")
    if(NOT FOUNDATION_GUI_SOURCE AND NOT FOUNDATION_GUI_INPUT_GROUP)
        set(FOUNDATION_GUI_INPUT_GROUP "${foundation_gui_project_root}/third_party/gui-inputs")
    endif()
    if(FOUNDATION_GUI_INPUT_GROUP)
        get_filename_component(FOUNDATION_GUI_INPUT_GROUP "${FOUNDATION_GUI_INPUT_GROUP}" REALPATH)
        if(FOUNDATION_GUI_SOURCE)
            message(FATAL_ERROR "Select FOUNDATION_GUI_INPUT_GROUP or FOUNDATION_GUI_SOURCE, not both")
        endif()
        execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${foundation_gui_module_root}/source_group.py"
            restore "${FOUNDATION_GUI_INPUT_GROUP}" --output "${CMAKE_CURRENT_BINARY_DIR}/retained-inputs"
            OUTPUT_VARIABLE restored_gui COMMAND_ERROR_IS_FATAL ANY)
        string(JSON FOUNDATION_GUI_SOURCE GET "${restored_gui}" source)
        get_directory_property(gui_parent PARENT_DIRECTORY)
        if(gui_parent)
            set(FOUNDATION_GUI_SOURCE "${FOUNDATION_GUI_SOURCE}" PARENT_SCOPE)
        endif()
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
            "${FOUNDATION_GUI_INPUT_GROUP}/manifest.json" "${FOUNDATION_GUI_INPUT_GROUP}/SHA256SUMS"
            "${FOUNDATION_GUI_INPUT_GROUP}/gui-inputs.tar.gz" "${foundation_gui_module_root}/source_group.py"
            "${foundation_gui_project_root}/tools/dependency_archive.py")
    endif()
    if(NOT IS_DIRECTORY "${FOUNDATION_GUI_SOURCE}/include/gui")
        message(FATAL_ERROR "Set FOUNDATION_GUI_SOURCE to pinned gui-boundary sources; see docs/gui-boundary.md")
    endif()
    get_filename_component(FOUNDATION_GUI_SOURCE "${FOUNDATION_GUI_SOURCE}" REALPATH)
    get_filename_component(lock_path "${foundation_gui_module_root}/../third_party/gui-boundary.lock.json" ABSOLUTE)
    file(READ "${lock_path}" lock)
    string(JSON file_count LENGTH "${lock}" files)
    math(EXPR last_file "${file_count} - 1")
    set(FOUNDATION_GUI_DISTRIBUTABLE FALSE)
    # This is reviewed dependency metadata, never a bypassable configuration option.
    string(JSON redistribution_approved GET "${lock}" redistribution approved)
    string(JSON license_id GET "${lock}" license)
    string(JSON license_count LENGTH "${lock}" redistribution license_files)
    if(redistribution_approved AND NOT license_id STREQUAL "NOASSERTION" AND license_count GREATER 0)
        math(EXPR license_last "${license_count} - 1")
        foreach(index RANGE 0 ${license_last})
            string(JSON license_file GET "${lock}" redistribution license_files ${index})
            string(JSON license_hash ERROR_VARIABLE missing_license GET "${lock}" files "${license_file}")
            if(missing_license)
                message(FATAL_ERROR "Redistribution license must be in the verified input inventory")
            endif()
        endforeach()
        set(FOUNDATION_GUI_DISTRIBUTABLE TRUE)
    endif()
    get_directory_property(gui_parent PARENT_DIRECTORY)
    if(gui_parent)
        set(FOUNDATION_GUI_DISTRIBUTABLE ${FOUNDATION_GUI_DISTRIBUTABLE} PARENT_SCOPE)
    endif()
    set(verified_files)
    foreach(index RANGE 0 ${last_file})
        string(JSON relative MEMBER "${lock}" files ${index})
        string(JSON expected GET "${lock}" files "${relative}")
        set(path "${FOUNDATION_GUI_SOURCE}/${relative}")
        if(NOT EXISTS "${path}")
            message(FATAL_ERROR "Pinned GUI input missing: ${relative}")
        endif()
        file(SHA256 "${path}" actual)
        if(NOT actual STREQUAL expected)
            message(FATAL_ERROR "Pinned GUI input differs: ${relative}. Review upgrade and lock together.")
        endif()
        list(APPEND verified_files "${path}")
    endforeach()
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${lock_path}" ${verified_files})
    if(NOT EMSCRIPTEN)
        find_package(Threads REQUIRED)
    endif()
    add_library(foundation_gui_boundary INTERFACE)
    add_library(gui_boundary ALIAS foundation_gui_boundary)
    target_include_directories(foundation_gui_boundary INTERFACE "${CMAKE_CURRENT_BINARY_DIR}/include")
    target_include_directories(foundation_gui_boundary SYSTEM INTERFACE "${FOUNDATION_GUI_SOURCE}/include")
    target_compile_features(foundation_gui_boundary INTERFACE cxx_std_20)
    if(WIN32)
        # Native toolkit headers must not replace standard C++ min/max calls.
        target_compile_definitions(foundation_gui_boundary INTERFACE NOMINMAX)
    endif()
    if(NOT EMSCRIPTEN)
        target_link_libraries(foundation_gui_boundary INTERFACE Threads::Threads)
    endif()
endmacro()

function(foundation_gui_patch source patch output)
    get_filename_component(output_directory "${CMAKE_CURRENT_BINARY_DIR}/${output}" DIRECTORY)
    file(MAKE_DIRECTORY "${output_directory}")
    execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${foundation_gui_module_root}/patches/apply.py"
        "${FOUNDATION_GUI_SOURCE}/${source}" "${foundation_gui_module_root}/patches/${patch}"
        "${CMAKE_CURRENT_BINARY_DIR}/${output}" COMMAND_ERROR_IS_FATAL ANY)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
        "${foundation_gui_module_root}/patches/${patch}" "${foundation_gui_module_root}/patches/apply.py")
endfunction()
# Continue a verified patch sequence without exposing intermediate assets in the
# installed web directory. The exact patcher preserves unchanged output mtimes.
function(foundation_gui_repatch source patch output)
    get_filename_component(output_directory "${CMAKE_CURRENT_BINARY_DIR}/${output}" DIRECTORY)
    file(MAKE_DIRECTORY "${output_directory}")
    execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${foundation_gui_module_root}/patches/apply.py"
        "${CMAKE_CURRENT_BINARY_DIR}/${source}" "${foundation_gui_module_root}/patches/${patch}"
        "${CMAKE_CURRENT_BINARY_DIR}/${output}" COMMAND_ERROR_IS_FATAL ANY)
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
        "${foundation_gui_module_root}/patches/${patch}")
endfunction()

macro(foundation_gui_headers)
    # Quoted sibling includes must see the patched contract consistently. Mirror the
    # complete verified header closure before applying any local extensions.
    # Patched headers are written only by the exact patcher, preserving their mtime
    # when final bytes are unchanged across incremental configuration.
    set(foundation_gui_mirrored_headers)
    foreach(path IN LISTS verified_files)
        file(RELATIVE_PATH relative "${FOUNDATION_GUI_SOURCE}" "${path}")
        if(relative MATCHES "^include/gui/")
            list(APPEND foundation_gui_mirrored_headers "${CMAKE_CURRENT_BINARY_DIR}/${relative}")
            if(NOT relative MATCHES "^include/gui/(contract|memory_adapter|interaction|web|runtime|terminal)\\.hpp$")
                configure_file("${path}" "${CMAKE_CURRENT_BINARY_DIR}/${relative}" COPYONLY)
            endif()
        endif()
    endforeach()
    # This generated directory belongs to the mirror. Remove obsolete outputs after
    # a reviewed inventory upgrade so incremental and fresh builds see the same API.
    file(GLOB_RECURSE foundation_gui_existing_headers LIST_DIRECTORIES FALSE
        "${CMAKE_CURRENT_BINARY_DIR}/include/gui/*")
    foreach(path IN LISTS foundation_gui_existing_headers)
        if(NOT path IN_LIST foundation_gui_mirrored_headers)
            file(REMOVE "${path}")
        endif()
    endforeach()
    foundation_gui_patch(include/gui/runtime.hpp file-services.patch include/gui/runtime.hpp)
    foundation_gui_patch(include/gui/contract.hpp touch-contract.patch include/gui/contract.hpp)
    foundation_gui_patch(include/gui/memory_adapter.hpp touch-memory.patch include/gui/memory_adapter.hpp)
    foundation_gui_patch(include/gui/interaction.hpp touch-interaction.patch include/gui/interaction.hpp)
    foundation_gui_patch(include/gui/terminal.hpp terminal-caret.patch include/gui/terminal.hpp)
endmacro()
