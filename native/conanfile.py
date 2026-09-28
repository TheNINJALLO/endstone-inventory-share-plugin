from conan import ConanFile
from conan.tools.cmake import CMakeDeps, CMakeToolchain


class InventorySyncDependencies(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    default_options = {"boost/*:header_only": True, "raknet/*:minecraft_version": "r26u3"}

    def requirements(self):
        for dependency in ("boost/1.91.0", "entt/3.16.0", "expected-lite/0.9.0",
                           "glm/1.0.3", "ms-gsl/4.2.2",
                           "raknet/4.081-mojang#4400acf2eaeb2178bde13693f403466e", "pybind11/3.0.1"):
            self.requires(dependency)

    def generate(self):
        CMakeDeps(self).generate()
        CMakeToolchain(self).generate()
