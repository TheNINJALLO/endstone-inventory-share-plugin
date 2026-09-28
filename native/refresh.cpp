// Uses the CPython stable ABI and pybind11's checked, ephemeral C++ conduit.
// The Python caller verifies the runtime profile before loading this library.
#define Py_LIMITED_API 0x030A0000
#include <Python.h>
#include <pybind11/conduit/pybind11_conduit_v1.h>
#include "endstone/core/inventory/player_inventory.h"

#ifdef _WIN32
#define INVENTORY_SYNC_EXPORT __declspec(dllexport)
#else
#define INVENTORY_SYNC_EXPORT __attribute__((visibility("default")))
#endif

extern "C" INVENTORY_SYNC_EXPORT int invshare_refresh(PyObject *object)
{
    auto *inventory = pybind11_conduit_v1::get_type_pointer_ephemeral<endstone::PlayerInventory>(object);
    if (!inventory) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_RuntimeError, "Inventory refresh: Endstone C++ ABI mismatch");
        }
        return -1;
    }
    try {
        // Compile this access against the pinned private SDK with access checks
        // disabled. No hard-coded field offsets or guessed function addresses.
        auto &native = static_cast<endstone::core::EndstonePlayerInventory &>(*inventory);
        native.holder_.sendInventory(false);  // Publish native IDs; preserve selection.
        return 1;
    }
    catch (const std::exception &error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return -1;
    }
}
