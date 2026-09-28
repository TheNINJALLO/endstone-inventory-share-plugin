"""Build the pinned inventory bridge using Clang 20 and Conan 2."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sdk", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    windows = os.name == "nt"
    compiler = shutil.which("clang-cl" if windows else "clang++-20")
    c_compiler = shutil.which("clang-cl" if windows else "clang-20")
    if not compiler or not c_compiler:
        parser.error("Install Clang 20; on Windows use an x64 Visual Studio developer shell")
    profile = "inventory-share-native"
    environment = dict(os.environ, CC="cl" if windows else c_compiler,
                       CXX="cl" if windows else compiler)
    run("conan", "profile", "detect", "--name", profile, "--force", env=environment)
    profile_path = Path(subprocess.check_output(
        ["conan", "profile", "path", profile], text=True).strip())
    with profile_path.open("a", encoding="utf-8") as stream:
        stream.write("\n[conf]\ntools.cmake.cmaketoolchain:generator=Ninja\n")
        stream.write("tools.build:compiler_executables=" + json.dumps(
            {"c": c_compiler, "cpp": compiler}) + "\n")
    settings = [] if windows else ["-s", "compiler.libcxx=libc++"]
    run("conan", "install", root / "native", "--output-folder", output,
        "--profile:host", profile, "--profile:build", profile, "--build=missing",
        "-s", "build_type=Release", "-s", "compiler.cppstd=20", *settings)
    overrides = [f"-DFETCHCONTENT_SOURCE_DIR_ENDSTONE={args.sdk.resolve()}"] if args.sdk else []
    run("cmake", "--fresh", "-S", root / "native", "-B", output, "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_TOOLCHAIN_FILE={output / 'conan_toolchain.cmake'}",
        f"-DPython3_EXECUTABLE={sys.executable}", *overrides)
    run("cmake", "--build", output, "--parallel", "4")


if __name__ == "__main__":
    main()
