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

compile_args = ["-Wall", "-Wextra"]

ext_module = [
    Extension(
        "maxminddb.extension",
        libraries=["maxminddb"],
        sources=["extension/maxminddb.c"],
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


if PYPY or JYTHON:
    run_setup(False)
    status_msgs(
        "WARNING: Disabling C extension due to Python platform.",
        "Plain-Python build succeeded.",
    )
else:
    try:
        run_setup(True)
    except BuildFailed as exc:
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
