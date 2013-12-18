# This import is apparently needed for Nose on Red Hat's Python
import multiprocessing

try:
    from setuptools import setup, Extension
except ImportError:
    from distutils.core import setup, Extension


module = Extension(
    'maxminddb',
    libraries=['maxminddb'],
    sources=['maxminddb.c'],
    extra_compile_args=[
        '-Wall', '-Wextra'],
)

setup(
    name='maxminddb',
    version='0.2.1',
    description='Python extension for reading the MaxMind DB format',
    ext_modules=[module],
    long_description=open('README.rst').read(),
    url='http://www.maxmind.com/',
    bugtrack_url='https://github.com/maxmind/MaxMind-DB-Reader-python/issues',
    package_data={'': ['LICENSE']},
    include_package_data=True,
    tests_require=['nose'],
    test_suite='nose.collector',
    license=open('LICENSE').read(),
    classifiers=(
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python',
        'Topic :: Internet :: Proxy Servers',
        'Topic :: Internet',
    ),
)
