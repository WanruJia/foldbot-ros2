cmake_minimum_required(VERSION 3.8)
project(foldbot_runtime)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

foreach(module bt execution msgs perception planning)
  ament_python_install_package(${module}
    PACKAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../${module}"
  )
endforeach()

install(PROGRAMS scripts/foldbot_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch config DESTINATION share/${PROJECT_NAME})

ament_package()