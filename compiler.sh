g++ -O3 -shared -std=c++17 -fPIC $(python3 -m pybind11 --includes) engine.cpp -o gcode_engine$(python3-config --extension-suffix)
