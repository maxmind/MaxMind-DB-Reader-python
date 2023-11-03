import os
import re
import sys

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
from wheel.bdist_wheel import bdist_wheel


# These were only added to setuptools in 59.0.1.
try:
    from setuptools.errors import CCompilerError
    from setuptools.errors import DistutilsExecError
    from setuptools.errors import DistutilsPlatformError
except ImportError:
    from distutils.errors import CCompilerError
    from distutils.errors import DistutilsExecError
    from distutils.errors import DistutilsPlatformError

cmdclass = {}
PYPY = hasattr(sys, "pypy_version_info")
JYTHON = sys.platform.startswith("java")

if os.name == "nt":
    # Disable unknown pragma warning
    compile_args = ["-wd4068"]
    libraries = ["Ws2_32"]
else:
    compile_args = ["-Wall", "-Wextra", "-Wno-unknown-pragmas"]
    libraries = []


if os.getenv("MAXMINDDB_USE_SYSTEM_LIBMAXMINDDB"):
    ext_module = [
        Extension(
            "maxminddb.extension",
            libraries=["maxminddb"] + libraries,
            sources=["extension/maxminddb.c"],
            extra_compile_args=compile_args,
        )
    ]
else:
    ext_module = [
        Extension(
            "maxminddb.extension",
            libraries=libraries,
            sources=[
                "extension/maxminddb.c",
                "extension/libmaxminddb/src/data-pool.c",
                "extension/libmaxminddb/src/maxminddb.c",
            ],
            define_macros=[
                ("HAVE_CONFIG_H", 0),
                ("MMDB_LITTLE_ENDIAN", 1 if sys.byteorder == "little" else 0),
                # We define these for maximum compatibility. The extension
                # itself supports all variations currently, but probing to
                # see what the compiler supports is a bit annoying to do
                # here, and we aren't using uint128 for much.
                ("MMDB_UINT128_USING_MODE", 0),
                ("MMDB_UINT128_IS_BYTE_ARRAY", 1),
                ("PACKAGE_VERSION", '"maxminddb-python"'),
            ],
            include_dirs=[
                "extension",
                "extension/libmaxminddb/include",
                "extension/libmaxminddb/src",
            ],
            extra_compile_args=compile_args,
        )
    ]

# Cargo cult code for installing extension with pure Python fallback.
# Taken from SQLAlchemy, but this same basic code exists in many modules.
ext_errors = (CCompilerError, DistutilsExecError, DistutilsPlatformError)


class BuildFailed(Exception):
    def __init__(self):
        self.cause = sys.exc_info()[1]


class ve_build_ext(build_ext):
    # This class allows C extension building to fail.

    def run(self):
        try:
            build_ext.run(self)
        except DistutilsPlatformError:
            raise BuildFailed()

    def build_extension(self, ext):
        try:
            build_ext.build_extension(self, ext)
        except ext_errors:
            raise BuildFailed()
        except ValueError:
            # this can happen on Windows 64 bit, see Python issue 7511
            if "'path'" in str(sys.exc_info()[1]):
                raise BuildFailed()
            raise


cmdclass["build_ext"] = ve_build_ext

#

ROOT = os.path.dirname(__file__)

with open(os.path.join(ROOT, "README.rst"), "rb") as fd:
    README = fd.read().decode("utf8")

with open(os.path.join(ROOT, "maxminddb", "__init__.py"), "rb") as fd:
    maxminddb_text = fd.read().decode("utf8")
    VERSION = (
        re.compile(r".*__version__ = \"(.*?)\"", re.S).match(maxminddb_text).group(1)
    )


def status_msgs(*msgs):
    print("*" * 75)
    for msg in msgs:
        print(msg)
    print("*" * 75)


def find_packages(location):
    packages = []
    for pkg in ["maxminddb"]:
        for _dir, subdirectories, files in os.walk(os.path.join(location, pkg)):
            if "__init__.py" in files:
                tokens = _dir.split(os.sep)[len(location.split(os.sep)) :]
                packages.append(".".join(tokens))
    return packages


def run_setup(with_cext):
    kwargs = {}
    loc_cmdclass = cmdclass.copy()
    if with_cext:
        kwargs["ext_modules"] = ext_module
        loc_cmdclass["bdist_wheel"] = bdist_wheel

    setup(version=VERSION, cmdclass=loc_cmdclass, **kwargs)


if JYTHON:
    run_setup(False)
    status_msgs(
        "WARNING: Disabling C extension due to Python platform.",
        "Plain-Python build succeeded.",
    )
else:
    try:
        run_setup(True)
    except BuildFailed as exc:
        if os.getenv("MAXMINDDB_REQUIRE_EXTENSION"):
            raise exc
        status_msgs(
            exc.cause,
            "WARNING: The C extension could not be compiled, "
            + "speedups are not enabled.",
            "Failure information, if any, is above.",
            "Retrying the build without the C extension now.",
        )

        run_setup(False)

        status_msgs(
            "WARNING: The C extension could not be compiled, "
            + "speedups are not enabled.",
            "Plain-Python build succeeded.",
        )
