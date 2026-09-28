# Native inventory synchronization

The bridge calls `Mob::sendInventory(false)` through Endstone's native player inventory wrapper. It uses pinned Endstone v0.11.12 headers and pybind11's checked conduit to obtain the C++ inventory pointer. There are no hand-written object offsets, function addresses, synthetic stack IDs, or client transaction overrides. The private wrapper layout also matches v0.11.11.

The bridge uses the CPython 3.10 stable API (`Py_LIMITED_API=0x030A0000`) and runs on the server thread with the GIL retained. Python verifies the BDS executable SHA-256 and Endstone version before loading it. Unknown builds remain blocked before shared data is applied.

## Build

Install Python 3.11 development headers, Clang 20, Conan 2, CMake 3.29+, Ninja, and Python `build`. On Linux install matching libc++/libc++abi 20 development packages. On Windows use an x64 Visual Studio developer shell with clang-cl on PATH.

```sh
python -m pip install 'conan>=2,<3' 'cmake>=3.29,<4' ninja build
conan remote add endstone https://conan.cloudsmith.io/endstone/conan/ --force
python scripts/build_native.py --output scratch/native
```

Set `INVSHARE_NATIVE_LIBRARY` to `scratch/native/inventory_sync.so` (Linux) or `scratch/native/inventory_sync.dll` (Windows), then run `python -m build --wheel`. The build refuses to package a wheel without the helper. Linux release builds use Ubuntu 22.04 and static libc++; glibc 2.35+ is required. No BDS server files are included in the wheel.

`CMakeLists.txt` fetches Endstone commit `1c71186cba896c5e0bc432384a8a8e72dfb2a626`. Two unsupported formatting expressions in the SDK's `result.h` are replaced for compilation; layouts and inventory behavior are unchanged. `--sdk` may use an already checked-out copy of that same commit. Dependency versions and the RakNet recipe revision are pinned in `conanfile.py`.

Bundled notices and licenses are in `src/endstone_inventory_share_plugin/_native/`. Before adding a new runtime profile, qualify the actual platform wheel with both live fixtures and update the validation record.
