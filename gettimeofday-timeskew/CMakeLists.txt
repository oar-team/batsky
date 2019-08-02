cmake_minimum_required (VERSION 2.6)
project (Gettimeofday-TimeSkew)
add_executable(gettimeofday-timeskew gettimeofday-timeskew.c)
install(TARGETS gettimeofday-timeskew DESTINATION bin)
